"""Command handlers for the bot."""

import csv
import io
import json
import logging
from datetime import date, timedelta
from uuid import UUID

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import (
    category_selection_keyboard,
    currency_keyboard,
    delete_confirmation_keyboard,
    export_format_keyboard,
    llm_provider_keyboard,
    report_period_keyboard,
    settings_keyboard,
)
from src.database.models import User
from src.database.repository import (
    CategoryRepository,
    ExpenseRepository,
    LLMConfigRepository,
    UserRepository,
)
from src.llm.provider import LLMProvider
from src.llm.reporter import generate_expense_report

logger = logging.getLogger(__name__)

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, user: User) -> None:
    """Handle /start command."""
    await message.answer(
        f"Welcome to Expense Manager Bot!\n\n"
        f"I'll help you track your expenses using AI. Just send me:\n\n"
        f"<b>Text:</b> \"Spent $25 on lunch\"\n"
        f"<b>Voice:</b> Record a voice message describing your expense\n"
        f"<b>Photo:</b> Send a photo of a receipt\n"
        f"<b>Video:</b> Record a video note about your purchase\n\n"
        f"<b>Commands:</b>\n"
        f"/report - View spending reports\n"
        f"/categories - Manage expense categories\n"
        f"/settings - Configure bot settings\n"
        f"/export - Export your data\n"
        f"/help - Show this help message"
    )


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Handle /help command."""
    await message.answer(
        "<b>Expense Manager Bot Help</b>\n\n"
        "<b>Track Expenses:</b>\n"
        "Send text, voice, photos, or videos describing expenses.\n\n"
        "<b>Examples:</b>\n"
        "- \"Uber ride $15\"\n"
        "- \"Spent 50 euros on groceries yesterday\"\n"
        "- Send a receipt photo\n"
        "- Voice: \"Just paid thirty bucks for gas\"\n\n"
        "<b>Commands:</b>\n"
        "/start - Welcome message\n"
        "/report - Generate spending reports\n"
        "/categories - View/manage categories\n"
        "/settings - Bot settings (LLM, currency)\n"
        "/export - Export data to CSV/JSON\n"
        "/help - This help message"
    )


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    """Handle /report command."""
    await message.answer(
        "Select a time period for your report:",
        reply_markup=report_period_keyboard(),
    )


@router.callback_query(F.data.startswith("report:"))
async def handle_report_callback(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
) -> None:
    """Handle report period selection."""
    period = callback.data.split(":")[1]
    today = date.today()

    if period == "week":
        start_date = today - timedelta(days=today.weekday())
        end_date = today
        period_name = "This Week"
    elif period == "month":
        start_date = today.replace(day=1)
        end_date = today
        period_name = "This Month"
    elif period == "30days":
        start_date = today - timedelta(days=30)
        end_date = today
        period_name = "Last 30 Days"
    elif period == "year":
        start_date = today.replace(month=1, day=1)
        end_date = today
        period_name = "This Year"
    else:
        await callback.answer("Invalid period")
        return

    await callback.answer()
    await callback.message.edit_text(f"Generating {period_name} report...")

    expense_repo = ExpenseRepository(session)

    expenses = await expense_repo.get_by_date_range(user.id, start_date, end_date)
    category_totals = await expense_repo.get_total_by_category(user.id, start_date, end_date)

    report = await generate_expense_report(
        expenses=expenses,
        category_totals=category_totals,
        start_date=start_date,
        end_date=end_date,
        currency=user.default_currency,
        llm=llm,
    )

    await callback.message.edit_text(
        f"<b>{period_name} Report</b>\n\n{report}",
        reply_markup=None,
    )


@router.message(Command("categories"))
async def cmd_categories(
    message: Message,
    session: AsyncSession,
    user: User,
) -> None:
    """Handle /categories command."""
    cat_repo = CategoryRepository(session)
    categories = await cat_repo.get_by_user(user.id)

    if not categories:
        await message.answer("You have no categories. They will be created automatically.")
        return

    lines = ["<b>Your Expense Categories:</b>\n"]
    for cat in categories:
        icon = f"{cat.icon} " if cat.icon else ""
        lines.append(f"  {icon}{cat.name}")

    lines.append("\n<i>Categories are automatically assigned by AI when you add expenses.</i>")

    await message.answer("\n".join(lines))


@router.message(Command("settings"))
async def cmd_settings(message: Message, user: User) -> None:
    """Handle /settings command."""
    await message.answer(
        f"<b>Settings</b>\n\n"
        f"<b>Current Currency:</b> {user.default_currency}\n\n"
        f"Choose what to configure:",
        reply_markup=settings_keyboard(),
    )


@router.callback_query(F.data == "settings:llm")
async def handle_llm_settings(callback: CallbackQuery) -> None:
    """Handle LLM settings selection."""
    await callback.answer()
    await callback.message.edit_text(
        "Select your preferred AI provider:\n\n"
        "<i>Note: You may need to provide your own API key.</i>",
        reply_markup=llm_provider_keyboard(),
    )


@router.callback_query(F.data.startswith("llm:"))
async def handle_llm_selection(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
) -> None:
    """Handle LLM provider selection."""
    provider = callback.data.split(":")[1]

    llm_repo = LLMConfigRepository(session)

    # Default models for each provider
    models = {
        "openai": "gpt-4o-mini",
        "gemini": "gemini-1.5-flash",
        "grok": "grok-beta",
        "ollama": "llama3.2",
    }

    await llm_repo.create(
        user_id=user.id,
        provider=provider,
        model=models.get(provider, "gpt-4o-mini"),
    )

    await callback.answer("LLM provider updated!")
    await callback.message.edit_text(
        f"AI provider set to <b>{provider.upper()}</b>.\n\n"
        f"Using model: <code>{models.get(provider)}</code>",
        reply_markup=None,
    )


@router.callback_query(F.data == "settings:currency")
async def handle_currency_settings(callback: CallbackQuery) -> None:
    """Handle currency settings selection."""
    await callback.answer()
    await callback.message.edit_text(
        "Select your default currency:",
        reply_markup=currency_keyboard(),
    )


@router.callback_query(F.data.startswith("currency:"))
async def handle_currency_selection(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
) -> None:
    """Handle currency selection."""
    currency = callback.data.split(":")[1]

    user_repo = UserRepository(session)
    await user_repo.update_currency(user.id, currency)

    await callback.answer("Currency updated!")
    await callback.message.edit_text(
        f"Default currency set to <b>{currency}</b>.",
        reply_markup=None,
    )


@router.callback_query(F.data == "settings:back")
async def handle_settings_back(callback: CallbackQuery, user: User) -> None:
    """Handle back button in settings."""
    await callback.answer()
    await callback.message.edit_text(
        f"<b>Settings</b>\n\n"
        f"<b>Current Currency:</b> {user.default_currency}\n\n"
        f"Choose what to configure:",
        reply_markup=settings_keyboard(),
    )


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    """Handle /export command."""
    await message.answer(
        "Select export format:",
        reply_markup=export_format_keyboard(),
    )


@router.callback_query(F.data.startswith("export:"))
async def handle_export(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
) -> None:
    """Handle export format selection."""
    format_type = callback.data.split(":")[1]

    await callback.answer()
    await callback.message.edit_text("Preparing export...")

    expense_repo = ExpenseRepository(session)
    expenses = await expense_repo.get_by_user(user.id, limit=10000)

    if not expenses:
        await callback.message.edit_text("No expenses to export.")
        return

    if format_type == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Amount", "Currency", "Category", "Description", "Source"])

        for exp in expenses:
            writer.writerow([
                exp.expense_date.isoformat(),
                str(exp.amount),
                exp.currency,
                exp.category.name if exp.category else "Uncategorized",
                exp.description or "",
                exp.source_type.value,
            ])

        file_data = output.getvalue().encode("utf-8")
        filename = f"expenses_{date.today().isoformat()}.csv"
        mime_type = "text/csv"

    else:  # JSON
        data = []
        for exp in expenses:
            data.append({
                "date": exp.expense_date.isoformat(),
                "amount": float(exp.amount),
                "currency": exp.currency,
                "category": exp.category.name if exp.category else None,
                "description": exp.description,
                "source_type": exp.source_type.value,
                "created_at": exp.created_at.isoformat(),
            })

        file_data = json.dumps(data, indent=2).encode("utf-8")
        filename = f"expenses_{date.today().isoformat()}.json"
        mime_type = "application/json"

    await callback.message.delete()
    await callback.message.answer_document(
        BufferedInputFile(file_data, filename=filename),
        caption=f"Your expense data ({len(expenses)} records)",
    )


# Expense action callbacks
@router.callback_query(F.data.startswith("expense:delete:"))
async def handle_expense_delete_prompt(callback: CallbackQuery) -> None:
    """Prompt for expense deletion confirmation."""
    expense_id = callback.data.split(":")[2]

    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=delete_confirmation_keyboard(UUID(expense_id))
    )


@router.callback_query(F.data.startswith("delete:confirm:"))
async def handle_expense_delete_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """Confirm expense deletion."""
    expense_id = UUID(callback.data.split(":")[2])

    expense_repo = ExpenseRepository(session)
    deleted = await expense_repo.delete(expense_id)

    if deleted:
        await callback.answer("Expense deleted!")
        await callback.message.edit_text(
            "<i>Expense deleted.</i>",
            reply_markup=None,
        )
    else:
        await callback.answer("Could not delete expense.")


@router.callback_query(F.data.startswith("delete:cancel:"))
async def handle_expense_delete_cancel(callback: CallbackQuery) -> None:
    """Cancel expense deletion."""
    await callback.answer("Deletion cancelled.")
    await callback.message.delete()


@router.callback_query(F.data.startswith("expense:category:"))
async def handle_expense_category_change(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
) -> None:
    """Show category selection for expense."""
    expense_id = UUID(callback.data.split(":")[2])

    cat_repo = CategoryRepository(session)
    categories = await cat_repo.get_by_user(user.id)

    await callback.answer()
    await callback.message.edit_reply_markup(
        reply_markup=category_selection_keyboard(categories, expense_id)
    )


@router.callback_query(F.data.startswith("setcat:"))
async def handle_set_category(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    """Set expense category."""
    parts = callback.data.split(":")
    expense_id = UUID(parts[1])
    category_action = parts[2]

    if category_action == "cancel":
        await callback.answer("Cancelled")
        await callback.message.delete()
        return

    category_id = UUID(category_action)

    expense_repo = ExpenseRepository(session)
    cat_repo = CategoryRepository(session)

    category = await cat_repo.get_by_id(category_id)
    expense = await expense_repo.update(expense_id, category_id=category_id)

    if expense and category:
        await callback.answer(f"Category changed to {category.name}!")
        await callback.message.edit_text(
            f"Category updated to <b>{category.icon} {category.name}</b>",
            reply_markup=None,
        )
    else:
        await callback.answer("Could not update category.")

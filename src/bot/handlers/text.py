"""Text message handler for expense parsing."""

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import expense_confirmation_keyboard
from src.database.models import SourceType, User
from src.database.repository import CategoryRepository, ExpenseItemRepository, ExpenseRepository
from src.llm.categorizer import (
    categorize_expense,
    parse_query,
    QueryType,
    understand_correction,
)
from src.llm.expense_parser import parse_expense
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

router = Router()


class ConversationStates(StatesGroup):
    """States for conversation context."""
    has_recent_expense = State()


@dataclass
class ExpenseContext:
    """Context about the last expense for corrections."""
    expense_id: str
    amount: Decimal
    currency: str
    description: str
    category_name: str
    category_id: str | None


def format_expense_message(
    amount: str,
    currency: str,
    category_name: str,
    category_icon: str,
    description: str,
    expense_date: str,
) -> str:
    """Format the expense confirmation message."""
    icon = f"{category_icon} " if category_icon else ""
    return (
        f"Expense recorded:\n\n"
        f"<b>{currency} {amount}</b> - {icon}{category_name}\n"
        f"{description}\n"
        f"{expense_date}"
    )


def format_update_message(
    amount: str,
    currency: str,
    category_name: str,
    category_icon: str,
    description: str,
    changes: list[str],
) -> str:
    """Format the expense update message."""
    icon = f"{category_icon} " if category_icon else ""
    changes_str = ", ".join(changes)
    return (
        f"Expense updated ({changes_str}):\n\n"
        f"<b>{currency} {amount}</b> - {icon}{category_name}\n"
        f"{description}"
    )


async def handle_item_price_query(
    message: Message,
    session: AsyncSession,
    user: User,
    item_name: str,
    group_chat_id: int | None = None,
) -> bool:
    """Handle item price queries like 'how much was milk?'"""
    item_repo = ExpenseItemRepository(session)
    result = await item_repo.get_latest_price(user.id, item_name, group_chat_id)

    if not result:
        await message.answer(
            f"I couldn't find any purchases of '{item_name}' in your history."
        )
        return True

    item, expense = result
    date_str = expense.expense_date.strftime("%b %d, %Y")

    await message.answer(
        f"<b>{item.name}</b>\n\n"
        f"Last purchased: {date_str}\n"
        f"Price: <b>{expense.currency} {item.total_price:.2f}</b>\n"
        f"Quantity: {item.quantity}"
    )
    return True


async def handle_category_spending_query(
    message: Message,
    session: AsyncSession,
    user: User,
    category_hint: str,
    start_date,
    end_date,
    group_chat_id: int | None = None,
) -> bool:
    """Handle category spending queries like 'how much on petrol last month?'"""
    from datetime import date as date_type
    from datetime import timedelta

    # Default to this month if no dates
    if not start_date:
        today = date_type.today()
        start_date = today.replace(day=1)
    if not end_date:
        end_date = date_type.today()

    expense_repo = ExpenseRepository(session)
    total, expenses = await expense_repo.get_spending_by_category_name(
        user.id, category_hint, start_date, end_date, group_chat_id
    )

    if not expenses:
        await message.answer(
            f"No spending found for '{category_hint}' "
            f"between {start_date.strftime('%b %d')} and {end_date.strftime('%b %d, %Y')}."
        )
        return True

    # Format period
    if start_date == end_date:
        period_str = start_date.strftime("%b %d, %Y")
    else:
        period_str = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"

    # Build response
    currency = expenses[0].currency if expenses else user.default_currency
    lines = [f"<b>Spending on '{category_hint}'</b>"]
    lines.append(f"Period: {period_str}\n")

    # Show individual expenses (max 5)
    for exp in expenses[:5]:
        cat_name = exp.category.name if exp.category else "Uncategorized"
        lines.append(f"• {exp.expense_date.strftime('%b %d')}: {currency} {exp.amount:.2f} - {exp.description or cat_name}")

    if len(expenses) > 5:
        lines.append(f"... and {len(expenses) - 5} more")

    lines.append(f"\n<b>Total: {currency} {total:.2f}</b> ({len(expenses)} transactions)")

    await message.answer("\n".join(lines))
    return True


def extract_expense_id_from_reply(message: Message) -> str | None:
    """Extract expense ID from a replied message's inline keyboard."""
    if not message.reply_to_message:
        return None

    reply = message.reply_to_message
    if not reply.reply_markup or not reply.reply_markup.inline_keyboard:
        return None

    # Look through the keyboard buttons for expense ID
    for row in reply.reply_markup.inline_keyboard:
        for button in row:
            if button.callback_data:
                # Patterns: expense:delete:{id}, expense:category:{id}, delete:confirm:{id}
                parts = button.callback_data.split(":")
                if len(parts) >= 3 and parts[0] in ("expense", "delete"):
                    return parts[2]

    return None


async def handle_date_spending_query(
    message: Message,
    session: AsyncSession,
    user: User,
    start_date,
    end_date,
    group_chat_id: int | None = None,
) -> bool:
    """Handle date spending queries like 'how much yesterday?'"""
    from datetime import date as date_type

    if not start_date:
        start_date = date_type.today()
    if not end_date:
        end_date = start_date

    expense_repo = ExpenseRepository(session)

    # For single day, use specific date query
    if start_date == end_date:
        total, expenses = await expense_repo.get_spending_by_date(
            user.id, start_date, group_chat_id
        )
        period_str = start_date.strftime("%B %d, %Y")
    else:
        # For date range, use date range query
        expenses = list(await expense_repo.get_by_date_range(
            user.id, start_date, end_date, group_chat_id
        ))
        total = sum(exp.amount for exp in expenses)
        period_str = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"

    if not expenses:
        await message.answer(f"No expenses found for {period_str}.")
        return True

    currency = expenses[0].currency if expenses else user.default_currency

    lines = [f"<b>Spending: {period_str}</b>\n"]

    # Group by category
    category_totals: dict[str, Decimal] = {}
    for exp in expenses:
        cat_name = exp.category.name if exp.category else "Uncategorized"
        category_totals[cat_name] = category_totals.get(cat_name, Decimal(0)) + exp.amount

    # Show category breakdown
    for cat_name, cat_total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"• {cat_name}: {currency} {cat_total:.2f}")

    lines.append(f"\n<b>Total: {currency} {total:.2f}</b> ({len(expenses)} transactions)")

    await message.answer("\n".join(lines))
    return True


async def handle_list_expenses_query(
    message: Message,
    session: AsyncSession,
    user: User,
    start_date,
    end_date,
    category_hint: str | None = None,
    group_chat_id: int | None = None,
) -> bool:
    """Handle list expenses queries like 'list today's expenses'."""
    from datetime import date as date_type

    if not start_date:
        start_date = date_type.today()
    if not end_date:
        end_date = start_date

    expense_repo = ExpenseRepository(session)

    # Get expenses for the period
    if category_hint:
        # Filter by category if specified
        total, expenses = await expense_repo.get_spending_by_category_name(
            user.id, category_hint, start_date, end_date, group_chat_id
        )
    else:
        if start_date == end_date:
            total, expenses = await expense_repo.get_spending_by_date(
                user.id, start_date, group_chat_id
            )
        else:
            expenses = list(await expense_repo.get_by_date_range(
                user.id, start_date, end_date, group_chat_id
            ))
            total = sum(exp.amount for exp in expenses)

    # Format period string
    if start_date == end_date:
        period_str = start_date.strftime("%B %d, %Y")
    else:
        period_str = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"

    if not expenses:
        await message.answer(f"No expenses found for {period_str}.")
        return True

    currency = expenses[0].currency if expenses else user.default_currency

    # Build detailed list
    category_filter = f" ({category_hint})" if category_hint else ""
    lines = [f"<b>Expenses: {period_str}{category_filter}</b>\n"]

    for i, exp in enumerate(expenses[:15], 1):  # Limit to 15 to avoid message too long
        cat_icon = exp.category.icon if exp.category else "📦"
        cat_name = exp.category.name if exp.category else "Uncategorized"
        time_str = exp.created_at.strftime("%I:%M %p") if exp.created_at else ""
        date_prefix = ""

        # Show date if range spans multiple days
        if start_date != end_date:
            date_prefix = f"{exp.expense_date.strftime('%b %d')} "

        description = exp.description or cat_name
        lines.append(
            f"{i}. {date_prefix}{time_str}\n"
            f"   <b>{currency} {exp.amount:.2f}</b> - {cat_icon} {cat_name}\n"
            f"   {description}"
        )

    if len(expenses) > 15:
        lines.append(f"\n... and {len(expenses) - 15} more expenses")

    lines.append(f"\n<b>Total: {currency} {total:.2f}</b> ({len(expenses)} expenses)")

    await message.answer("\n".join(lines))
    return True


@router.message(F.text)
async def handle_text_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    state: FSMContext,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle text messages and parse them as expenses."""
    text = message.text.strip()

    if not text:
        return

    # Skip if message looks like a command
    if text.startswith("/"):
        return

    # First, check if this is a query about expenses
    query = await parse_query(text, llm)

    if query.is_valid:
        if query.query_type == QueryType.ITEM_PRICE and query.item_name:
            await handle_item_price_query(
                message, session, user, query.item_name, group_chat_id
            )
            return
        elif query.query_type == QueryType.CATEGORY_SPENDING and query.category_hint:
            await handle_category_spending_query(
                message, session, user,
                query.category_hint, query.start_date, query.end_date,
                group_chat_id
            )
            return
        elif query.query_type == QueryType.DATE_SPENDING:
            await handle_date_spending_query(
                message, session, user,
                query.start_date, query.end_date,
                group_chat_id
            )
            return
        elif query.query_type == QueryType.LIST_EXPENSES:
            await handle_list_expenses_query(
                message, session, user,
                query.start_date, query.end_date,
                query.category_hint,
                group_chat_id
            )
            return

    # Parse expense from text
    parsed = await parse_expense(text, llm)

    if not parsed:
        # Check if this is a reply to an expense message (for corrections)
        reply_expense_id = extract_expense_id_from_reply(message)

        # Get expense context - either from reply or from state
        last_expense = None
        if reply_expense_id:
            # Load expense from database for reply-based correction
            expense_repo = ExpenseRepository(session)
            replied_expense = await expense_repo.get_by_id(UUID(reply_expense_id))
            if replied_expense:
                last_expense = {
                    "expense_id": str(replied_expense.id),
                    "amount": str(replied_expense.amount),
                    "currency": replied_expense.currency,
                    "description": replied_expense.description or "",
                    "category_name": replied_expense.category.name if replied_expense.category else "Uncategorized",
                    "category_id": str(replied_expense.category.id) if replied_expense.category else None,
                }
        else:
            # Fall back to state-based last expense
            state_data = await state.get_data()
            last_expense = state_data.get("last_expense")

        if last_expense:
            # Try to understand if this is a correction
            cat_repo = CategoryRepository(session)
            categories = await cat_repo.get_by_user(user.id)

            correction = await understand_correction(
                message=text,
                last_expense_amount=Decimal(last_expense["amount"]),
                last_expense_currency=last_expense["currency"],
                last_expense_description=last_expense["description"],
                last_expense_category=last_expense["category_name"],
                categories=categories,
                llm=llm,
            )

            if correction.is_correction:
                # Apply the correction
                expense_repo = ExpenseRepository(session)
                expense_id = UUID(last_expense["expense_id"])

                # Build update parameters
                update_kwargs = {}
                changes = []

                if correction.new_category:
                    # Find category by name
                    new_cat = await cat_repo.get_by_name(user.id, correction.new_category)
                    if new_cat:
                        update_kwargs["category_id"] = new_cat.id
                        changes.append("category")
                        last_expense["category_name"] = new_cat.name
                        last_expense["category_id"] = str(new_cat.id)

                if correction.new_description:
                    update_kwargs["description"] = correction.new_description
                    changes.append("description")
                    last_expense["description"] = correction.new_description

                if correction.new_amount is not None:
                    update_kwargs["amount"] = correction.new_amount
                    changes.append("amount")
                    last_expense["amount"] = str(correction.new_amount)

                if update_kwargs:
                    await expense_repo.update(expense_id, **update_kwargs)

                    # Update state with new values
                    await state.update_data(last_expense=last_expense)

                    # Get updated category info for display
                    category_icon = ""
                    category_name = last_expense["category_name"]
                    if last_expense.get("category_id"):
                        cat = await cat_repo.get_by_id(UUID(last_expense["category_id"]))
                        if cat:
                            category_icon = cat.icon

                    response = format_update_message(
                        amount=f"{Decimal(last_expense['amount']):.2f}",
                        currency=last_expense["currency"],
                        category_name=category_name,
                        category_icon=category_icon,
                        description=last_expense["description"],
                        changes=changes,
                    )

                    if is_group:
                        added_by = user.first_name or user.username or "Someone"
                        response = f"<i>Updated by {added_by}</i>\n\n" + response

                    await message.answer(
                        response,
                        reply_markup=expense_confirmation_keyboard(expense_id),
                    )
                    return

        # Not a correction either - show help (only in private chats)
        if not is_group:
            await message.answer(
                "I couldn't identify an expense in your message.\n\n"
                "Try something like:\n"
                "- \"Spent $25 on lunch\"\n"
                "- \"Uber ride 15 dollars\"\n"
                "- \"paid 50 for groceries yesterday\""
            )
        return

    # Get categories and categorize
    cat_repo = CategoryRepository(session)
    categories = await cat_repo.get_by_user(user.id)

    category = None
    category_name = "Uncategorized"
    category_icon = ""

    if parsed.category:
        # Try to find matching category from LLM suggestion
        category = await cat_repo.get_by_name(user.id, parsed.category)

    if not category and parsed.description:
        # Use LLM to categorize based on description
        category, _ = await categorize_expense(parsed.description, categories, llm)

    if category:
        category_name = category.name
        category_icon = category.icon

    # Create expense (with group_chat_id if in a group)
    expense_repo = ExpenseRepository(session)
    expense = await expense_repo.create(
        user_id=user.id,
        amount=parsed.amount,
        currency=parsed.currency or user.default_currency,
        description=parsed.description,
        category_id=category.id if category else None,
        source_type=SourceType.TEXT,
        raw_input=text,
        expense_date=parsed.expense_date,
        group_chat_id=group_chat_id,
    )

    # Store expense context for potential corrections
    expense_context = {
        "expense_id": str(expense.id),
        "amount": str(parsed.amount),
        "currency": parsed.currency or user.default_currency,
        "description": parsed.description,
        "category_name": category_name,
        "category_id": str(category.id) if category else None,
    }
    await state.update_data(last_expense=expense_context)

    # Format date for display
    date_str = parsed.expense_date.strftime("%b %d, %Y")
    if parsed.expense_date == message.date.date():
        date_str = "Today"

    response = format_expense_message(
        amount=f"{parsed.amount:.2f}",
        currency=parsed.currency or user.default_currency,
        category_name=category_name,
        category_icon=category_icon,
        description=parsed.description,
        expense_date=date_str,
    )

    # Add user attribution in group chats
    if is_group:
        added_by = user.first_name or user.username or "Someone"
        response = f"<i>Added by {added_by}</i>\n\n" + response

    await message.answer(
        response,
        reply_markup=expense_confirmation_keyboard(expense.id),
    )

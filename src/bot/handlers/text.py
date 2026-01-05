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
from src.database.repository import CategoryRepository, ExpenseRepository
from src.llm.categorizer import categorize_expense, understand_correction
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

    # Parse expense from text
    parsed = await parse_expense(text, llm)

    if not parsed:
        # Check if this might be a correction to the last expense
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

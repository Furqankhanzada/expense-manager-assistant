"""Text message handler for expense parsing."""

import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import expense_confirmation_keyboard
from src.database.models import SourceType, User
from src.database.repository import CategoryRepository, ExpenseRepository
from src.llm.categorizer import categorize_expense
from src.llm.expense_parser import parse_expense
from src.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

router = Router()


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


@router.message(F.text)
async def handle_text_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
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
        # Only show help in private chats to avoid spam in groups
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

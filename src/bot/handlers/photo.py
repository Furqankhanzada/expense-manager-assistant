"""Photo message handler for receipt processing."""

import logging
import uuid
from dataclasses import dataclass

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import expense_confirmation_keyboard, receipt_confirmation_keyboard
from src.database.models import SourceType, User
from src.database.repository import CategoryRepository, ExpenseItemRepository, ExpenseRepository
from src.llm.categorizer import categorize_expense
from src.llm.expense_parser import ParsedExpense, ParsedLineItem
from src.llm.provider import LLMProvider
from src.media.vision import process_receipt_image

logger = logging.getLogger(__name__)

router = Router()


@dataclass
class PendingReceipt:
    """Pending receipt data with context."""
    expenses: list[ParsedExpense]
    line_items: list[ParsedLineItem] | None = None
    group_chat_id: int | None = None


# Temporary storage for pending receipt confirmations
_pending_receipts: dict[str, PendingReceipt] = {}


@router.message(F.photo)
async def handle_photo_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    state: FSMContext,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle photo messages and parse them as receipts."""
    processing_msg = await message.answer("Analyzing image...")

    try:
        # Get the largest photo (best quality)
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        photo_data = await message.bot.download_file(file.file_path)

        # Process as receipt
        result = await process_receipt_image(
            image_data=photo_data.read(),
            llm=llm,
            mime_type="image/jpeg",
        )

        if not result or not result.expenses:
            await processing_msg.edit_text(
                "I couldn't find any expense information in this image.\n\n"
                "Try sending a clear photo of a receipt, or type your expense instead."
            )
            return

        # Add user attribution prefix for groups
        added_by_prefix = ""
        if is_group:
            added_by = user.first_name or user.username or "Someone"
            added_by_prefix = f"<i>Added by {added_by}</i>\n\n"

        # If single expense, add it directly
        if len(result.expenses) == 1:
            expense_data = result.expenses[0]

            cat_repo = CategoryRepository(session)
            categories = await cat_repo.get_by_user(user.id)

            category = None
            if expense_data.category:
                category = await cat_repo.get_by_name(user.id, expense_data.category)
            if not category and expense_data.description:
                category, _ = await categorize_expense(expense_data.description, categories, llm)

            expense_repo = ExpenseRepository(session)
            expense = await expense_repo.create(
                user_id=user.id,
                amount=expense_data.amount,
                currency=expense_data.currency or user.default_currency,
                description=expense_data.description,
                category_id=category.id if category else None,
                source_type=SourceType.IMAGE,
                raw_input="[Receipt image]",
                expense_date=expense_data.expense_date,
                group_chat_id=group_chat_id,
            )

            # Save line items if available
            items_count = 0
            if result.line_items:
                item_repo = ExpenseItemRepository(session)
                items_data = [
                    {
                        "name": item.name,
                        "quantity": item.quantity,
                        "unit_price": item.unit_price,
                        "total_price": item.total_price,
                    }
                    for item in result.line_items
                ]
                await item_repo.create_bulk(expense.id, items_data)
                items_count = len(result.line_items)

            category_name = category.name if category else "Uncategorized"
            category_icon = category.icon if category else ""
            date_str = expense_data.expense_date.strftime("%b %d, %Y")

            store_info = f" ({result.store_name})" if result.store_name else ""
            icon = f"{category_icon} " if category_icon else ""
            currency = expense_data.currency or user.default_currency
            items_info = f"\n({items_count} items saved)" if items_count > 0 else ""

            # Store expense context for potential corrections
            expense_context = {
                "expense_id": str(expense.id),
                "amount": str(expense_data.amount),
                "currency": currency,
                "description": expense_data.description,
                "category_name": category_name,
                "category_id": str(category.id) if category else None,
            }
            await state.update_data(last_expense=expense_context)

            await processing_msg.edit_text(
                f"{added_by_prefix}Receipt processed{store_info}:\n\n"
                f"<b>{currency} {expense_data.amount:.2f}</b> - {icon}{category_name}\n"
                f"{expense_data.description}\n"
                f"{date_str}{items_info}",
                reply_markup=expense_confirmation_keyboard(expense.id),
            )
            return

        # Multiple expenses found - ask for confirmation
        confirm_id = str(uuid.uuid4())[:8]
        _pending_receipts[confirm_id] = PendingReceipt(
            expenses=result.expenses,
            line_items=result.line_items,
            group_chat_id=group_chat_id,
        )

        lines = [f"{added_by_prefix}Found expenses on receipt:\n"]
        total = sum(e.amount for e in result.expenses)
        currency = result.expenses[0].currency if result.expenses else user.default_currency

        for i, exp in enumerate(result.expenses, 1):
            lines.append(f"{i}. {currency} {exp.amount:.2f} - {exp.description}")

        if result.store_name:
            lines.append(f"\nStore: {result.store_name}")
        lines.append(f"\n<b>Total: {currency} {total:.2f}</b>")

        await processing_msg.edit_text(
            "\n".join(lines),
            reply_markup=receipt_confirmation_keyboard(confirm_id),
        )

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that image. Please try again."
        )


@router.callback_query(F.data.startswith("receipt:confirm:"))
async def handle_receipt_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    state: FSMContext,
) -> None:
    """Confirm and save all receipt expenses."""
    confirm_id = callback.data.split(":")[2]

    pending = _pending_receipts.pop(confirm_id, None)
    if not pending:
        await callback.answer("Receipt data expired. Please send the image again.")
        return

    await callback.answer()
    await callback.message.edit_text("Saving expenses...")

    cat_repo = CategoryRepository(session)
    expense_repo = ExpenseRepository(session)
    item_repo = ExpenseItemRepository(session)
    categories = await cat_repo.get_by_user(user.id)

    saved_count = 0
    first_expense_id = None
    for expense_data in pending.expenses:
        category = None
        if expense_data.category:
            category = await cat_repo.get_by_name(user.id, expense_data.category)
        if not category and expense_data.description:
            category, _ = await categorize_expense(expense_data.description, categories, llm)

        expense = await expense_repo.create(
            user_id=user.id,
            amount=expense_data.amount,
            currency=expense_data.currency or user.default_currency,
            description=expense_data.description,
            category_id=category.id if category else None,
            source_type=SourceType.IMAGE,
            raw_input="[Receipt image]",
            expense_date=expense_data.expense_date,
            group_chat_id=pending.group_chat_id,
        )
        if first_expense_id is None:
            first_expense_id = expense.id
        saved_count += 1

    # Save line items to first expense (the total)
    items_count = 0
    if pending.line_items and first_expense_id:
        items_data = [
            {
                "name": item.name,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total_price": item.total_price,
            }
            for item in pending.line_items
        ]
        await item_repo.create_bulk(first_expense_id, items_data)
        items_count = len(pending.line_items)

    total = sum(e.amount for e in pending.expenses)
    currency = pending.expenses[0].currency if pending.expenses else user.default_currency
    items_info = f"\n({items_count} items saved)" if items_count > 0 else ""

    # Store first expense context for potential corrections
    if pending.expenses and first_expense_id:
        first_exp = pending.expenses[0]
        expense_context = {
            "expense_id": str(first_expense_id),
            "amount": str(total),
            "currency": currency,
            "description": first_exp.description,
            "category_name": first_exp.category or "Uncategorized",
            "category_id": None,
        }
        await state.update_data(last_expense=expense_context)

    await callback.message.edit_text(
        f"Saved {saved_count} expenses from receipt.\n"
        f"Total: <b>{currency} {total:.2f}</b>{items_info}",
        reply_markup=None,
    )


@router.callback_query(F.data.startswith("receipt:cancel:"))
async def handle_receipt_cancel(callback: CallbackQuery) -> None:
    """Cancel receipt processing."""
    confirm_id = callback.data.split(":")[2]
    _pending_receipts.pop(confirm_id, None)

    await callback.answer("Cancelled")
    await callback.message.edit_text(
        "<i>Receipt cancelled.</i>",
        reply_markup=None,
    )

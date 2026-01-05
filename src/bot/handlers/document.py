"""Document message handler for receipt/invoice processing."""

import logging

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import expense_confirmation_keyboard
from src.database.models import SourceType, User
from src.database.repository import CategoryRepository, ExpenseRepository
from src.llm.categorizer import categorize_expense
from src.llm.provider import LLMProvider
from src.media.vision import process_document_image, process_receipt_image

logger = logging.getLogger(__name__)

router = Router()

# Supported document types
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
SUPPORTED_DOC_TYPES = {"application/pdf"}


@router.message(F.document)
async def handle_document_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
) -> None:
    """Handle document messages (PDFs, images sent as files)."""
    document = message.document
    mime_type = document.mime_type or ""

    # Check if it's a supported type
    if mime_type not in SUPPORTED_IMAGE_TYPES and mime_type not in SUPPORTED_DOC_TYPES:
        await message.answer(
            "I can process:\n"
            "- Images (JPEG, PNG, WebP)\n"
            "- PDF documents\n\n"
            "Please send a receipt or invoice in one of these formats."
        )
        return

    processing_msg = await message.answer("Processing document...")

    try:
        file = await message.bot.get_file(document.file_id)
        doc_data = await message.bot.download_file(file.file_path)
        doc_bytes = doc_data.read()

        result = None

        if mime_type in SUPPORTED_IMAGE_TYPES:
            # Process as image
            result = await process_receipt_image(doc_bytes, llm, mime_type)

            if not result or not result.expenses:
                # Try as general document image
                result = await process_document_image(doc_bytes, llm, mime_type)

        elif mime_type == "application/pdf":
            # For PDF, we'll try to extract the first page as an image
            # This requires pdf2image or similar, but for simplicity we'll
            # inform the user about the limitation
            await processing_msg.edit_text(
                "PDF processing is limited. For best results, please:\n"
                "1. Take a screenshot of the receipt/invoice\n"
                "2. Send it as an image\n\n"
                "Or simply type the expense details."
            )
            return

        if not result or not result.expenses:
            await processing_msg.edit_text(
                "I couldn't find any expense information in this document.\n\n"
                "Try sending a clearer image or type the expense details."
            )
            return

        # Process the first expense (or total if available)
        expense_data = result.expenses[0]

        # If there's a total and multiple items, prefer the total
        if result.total and len(result.expenses) > 1:
            expense_data = result.expenses[0]
            expense_data.amount = result.total
            expense_data.description = "Total" + (
                f" at {result.store_name}" if result.store_name else ""
            )

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
            source_type=SourceType.DOCUMENT,
            raw_input=f"[Document: {document.file_name or 'unnamed'}]",
            expense_date=expense_data.expense_date,
        )

        category_name = category.name if category else "Uncategorized"
        category_icon = category.icon if category else ""
        date_str = expense_data.expense_date.strftime("%b %d, %Y")
        store_info = f" at {result.store_name}" if result.store_name else ""
        icon = f"{category_icon} " if category_icon else ""
        currency = expense_data.currency or user.default_currency

        await processing_msg.edit_text(
            f"Document processed{store_info}:\n\n"
            f"<b>{currency} {expense_data.amount:.2f}</b> - {icon}{category_name}\n"
            f"{expense_data.description}\n"
            f"{date_str}",
            reply_markup=expense_confirmation_keyboard(expense.id),
        )

    except Exception as e:
        logger.error(f"Error processing document: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that document. Please try again."
        )

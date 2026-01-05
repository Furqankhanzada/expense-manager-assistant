"""Video message handler for expense parsing."""

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
from src.media.video import transcribe_video, extract_video_frame
from src.media.vision import process_document_image

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.video)
async def handle_video_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle video messages - extract audio and/or frames for expense parsing."""
    processing_msg = await message.answer("Processing video...")

    # Add user attribution prefix for groups
    added_by_prefix = ""
    if is_group:
        added_by = user.first_name or user.username or "Someone"
        added_by_prefix = f"<i>Added by {added_by}</i>\n\n"

    try:
        video = message.video
        file = await message.bot.get_file(video.file_id)
        video_data = await message.bot.download_file(file.file_path)
        video_bytes = video_data.read()

        # Try to transcribe audio first
        transcription = await transcribe_video(video_bytes, ".mp4")

        if transcription:
            await processing_msg.edit_text(f"I heard: \"{transcription}\"\n\nProcessing...")

            parsed = await parse_expense(transcription, llm)

            if parsed:
                cat_repo = CategoryRepository(session)
                categories = await cat_repo.get_by_user(user.id)

                category = None
                if parsed.category:
                    category = await cat_repo.get_by_name(user.id, parsed.category)
                if not category and parsed.description:
                    category, _ = await categorize_expense(parsed.description, categories, llm)

                expense_repo = ExpenseRepository(session)
                expense = await expense_repo.create(
                    user_id=user.id,
                    amount=parsed.amount,
                    currency=parsed.currency or user.default_currency,
                    description=parsed.description,
                    category_id=category.id if category else None,
                    source_type=SourceType.VIDEO,
                    raw_input=transcription,
                    expense_date=parsed.expense_date,
                    group_chat_id=group_chat_id,
                )

                category_name = category.name if category else "Uncategorized"
                category_icon = category.icon if category else ""
                date_str = parsed.expense_date.strftime("%b %d, %Y")
                icon = f"{category_icon} " if category_icon else ""
                currency = parsed.currency or user.default_currency

                await processing_msg.edit_text(
                    f"{added_by_prefix}Expense recorded:\n\n"
                    f"<b>{currency} {parsed.amount:.2f}</b> - {icon}{category_name}\n"
                    f"{parsed.description}\n"
                    f"{date_str}",
                    reply_markup=expense_confirmation_keyboard(expense.id),
                )
                return

        # If no audio or couldn't parse, try extracting a frame
        await processing_msg.edit_text("Analyzing video frame...")

        frame = await extract_video_frame(video_bytes, timestamp=1.0)
        if frame:
            result = await process_document_image(frame, llm)

            if result and result.expenses:
                expense_data = result.expenses[0]

                cat_repo = CategoryRepository(session)
                categories = await cat_repo.get_by_user(user.id)

                category = None
                if expense_data.category:
                    category = await cat_repo.get_by_name(user.id, expense_data.category)
                if not category and expense_data.description:
                    category, _ = await categorize_expense(
                        expense_data.description, categories, llm
                    )

                expense_repo = ExpenseRepository(session)
                expense = await expense_repo.create(
                    user_id=user.id,
                    amount=expense_data.amount,
                    currency=expense_data.currency or user.default_currency,
                    description=expense_data.description,
                    category_id=category.id if category else None,
                    source_type=SourceType.VIDEO,
                    raw_input="[Video frame]",
                    expense_date=expense_data.expense_date,
                    group_chat_id=group_chat_id,
                )

                category_name = category.name if category else "Uncategorized"
                category_icon = category.icon if category else ""
                date_str = expense_data.expense_date.strftime("%b %d, %Y")
                icon = f"{category_icon} " if category_icon else ""
                currency = expense_data.currency or user.default_currency

                await processing_msg.edit_text(
                    f"{added_by_prefix}Expense recorded from video:\n\n"
                    f"<b>{currency} {expense_data.amount:.2f}</b> - {icon}{category_name}\n"
                    f"{expense_data.description}\n"
                    f"{date_str}",
                    reply_markup=expense_confirmation_keyboard(expense.id),
                )
                return

        await processing_msg.edit_text(
            "I couldn't find any expense information in this video.\n\n"
            "Try recording yourself saying the expense, or send a text message instead."
        )

    except Exception as e:
        logger.error(f"Error processing video: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that video. Please try again."
        )


@router.message(F.video_note)
async def handle_video_note(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle video notes (circular videos) for expense parsing."""
    processing_msg = await message.answer("Processing video note...")

    try:
        video_note = message.video_note
        file = await message.bot.get_file(video_note.file_id)
        video_data = await message.bot.download_file(file.file_path)
        video_bytes = video_data.read()

        # Transcribe audio from video note
        transcription = await transcribe_video(video_bytes, ".mp4")

        if not transcription:
            await processing_msg.edit_text(
                "I couldn't understand the audio in your video note.\n"
                "Please try again or send a text/voice message."
            )
            return

        await processing_msg.edit_text(f"I heard: \"{transcription}\"\n\nProcessing...")

        parsed = await parse_expense(transcription, llm)

        if not parsed:
            await processing_msg.edit_text(
                f"I heard: \"{transcription}\"\n\n"
                "But I couldn't identify an expense. Try saying something like:\n"
                "\"Spent twenty dollars on lunch\""
            )
            return

        cat_repo = CategoryRepository(session)
        categories = await cat_repo.get_by_user(user.id)

        category = None
        if parsed.category:
            category = await cat_repo.get_by_name(user.id, parsed.category)
        if not category and parsed.description:
            category, _ = await categorize_expense(parsed.description, categories, llm)

        expense_repo = ExpenseRepository(session)
        expense = await expense_repo.create(
            user_id=user.id,
            amount=parsed.amount,
            currency=parsed.currency or user.default_currency,
            description=parsed.description,
            category_id=category.id if category else None,
            source_type=SourceType.VIDEO,
            raw_input=transcription,
            expense_date=parsed.expense_date,
            group_chat_id=group_chat_id,
        )

        category_name = category.name if category else "Uncategorized"
        category_icon = category.icon if category else ""
        date_str = parsed.expense_date.strftime("%b %d, %Y")
        icon = f"{category_icon} " if category_icon else ""
        currency = parsed.currency or user.default_currency

        # Add user attribution in group chats
        added_by_prefix = ""
        if is_group:
            added_by = user.first_name or user.username or "Someone"
            added_by_prefix = f"<i>Added by {added_by}</i>\n\n"

        await processing_msg.edit_text(
            f"{added_by_prefix}Expense recorded:\n\n"
            f"<b>{currency} {parsed.amount:.2f}</b> - {icon}{category_name}\n"
            f"{parsed.description}\n"
            f"{date_str}",
            reply_markup=expense_confirmation_keyboard(expense.id),
        )

    except Exception as e:
        logger.error(f"Error processing video note: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that video note."
        )

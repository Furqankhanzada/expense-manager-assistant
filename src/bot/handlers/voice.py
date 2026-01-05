"""Voice message handler for expense parsing."""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.keyboards import expense_confirmation_keyboard
from src.database.models import SourceType, User
from src.database.repository import CategoryRepository, ExpenseRepository
from src.llm.categorizer import categorize_expense
from src.llm.expense_parser import parse_expense
from src.llm.provider import LLMProvider
from src.media.transcriber import transcribe_voice_message, transcribe_audio_file

logger = logging.getLogger(__name__)

router = Router()


@router.message(F.voice)
async def handle_voice_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    state: FSMContext,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle voice messages and parse them as expenses."""
    # Send processing indicator
    processing_msg = await message.answer("Listening...")

    try:
        # Download voice message
        voice = message.voice
        file = await message.bot.get_file(voice.file_id)
        voice_data = await message.bot.download_file(file.file_path)

        # Transcribe
        transcription = await transcribe_voice_message(voice_data.read())

        if not transcription:
            await processing_msg.edit_text(
                "I couldn't understand the audio. Please try again or type your expense."
            )
            return

        await processing_msg.edit_text(f"I heard: \"{transcription}\"\n\nProcessing...")

        # Parse expense from transcription
        parsed = await parse_expense(transcription, llm)

        if not parsed:
            await processing_msg.edit_text(
                f"I heard: \"{transcription}\"\n\n"
                "But I couldn't identify an expense. Try saying something like:\n"
                "\"Spent twenty dollars on lunch\""
            )
            return

        # Categorize
        cat_repo = CategoryRepository(session)
        categories = await cat_repo.get_by_user(user.id)

        category = None
        category_name = "Uncategorized"
        category_icon = ""

        if parsed.category:
            category = await cat_repo.get_by_name(user.id, parsed.category)

        if not category and parsed.description:
            category, _ = await categorize_expense(parsed.description, categories, llm)

        if category:
            category_name = category.name
            category_icon = category.icon

        # Create expense
        expense_repo = ExpenseRepository(session)
        expense = await expense_repo.create(
            user_id=user.id,
            amount=parsed.amount,
            currency=parsed.currency or user.default_currency,
            description=parsed.description,
            category_id=category.id if category else None,
            source_type=SourceType.VOICE,
            raw_input=transcription,
            expense_date=parsed.expense_date,
            group_chat_id=group_chat_id,
        )

        date_str = parsed.expense_date.strftime("%b %d, %Y")

        icon = f"{category_icon} " if category_icon else ""
        currency = parsed.currency or user.default_currency

        # Store expense context for potential corrections
        expense_context = {
            "expense_id": str(expense.id),
            "amount": str(parsed.amount),
            "currency": currency,
            "description": parsed.description,
            "category_name": category_name,
            "category_id": str(category.id) if category else None,
        }
        await state.update_data(last_expense=expense_context)

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
        logger.error(f"Error processing voice message: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that voice message. Please try again."
        )


@router.message(F.audio)
async def handle_audio_message(
    message: Message,
    session: AsyncSession,
    user: User,
    llm: LLMProvider,
    state: FSMContext,
    is_group: bool = False,
    group_chat_id: int | None = None,
) -> None:
    """Handle audio file messages."""
    processing_msg = await message.answer("Processing audio...")

    try:
        audio = message.audio
        file = await message.bot.get_file(audio.file_id)
        audio_data = await message.bot.download_file(file.file_path)

        mime_type = audio.mime_type or "audio/mpeg"
        transcription = await transcribe_audio_file(audio_data.read(), mime_type)

        if not transcription:
            await processing_msg.edit_text(
                "I couldn't understand the audio. Please try again."
            )
            return

        await processing_msg.edit_text(f"I heard: \"{transcription}\"\n\nProcessing...")

        parsed = await parse_expense(transcription, llm)

        if not parsed:
            await processing_msg.edit_text(
                f"I heard: \"{transcription}\"\n\n"
                "But I couldn't identify an expense."
            )
            return

        cat_repo = CategoryRepository(session)
        categories = await cat_repo.get_by_user(user.id)

        category = None
        category_name = "Uncategorized"
        category_icon = ""

        if parsed.category:
            category = await cat_repo.get_by_name(user.id, parsed.category)

        if not category and parsed.description:
            category, _ = await categorize_expense(parsed.description, categories, llm)

        if category:
            category_name = category.name
            category_icon = category.icon

        expense_repo = ExpenseRepository(session)
        expense = await expense_repo.create(
            user_id=user.id,
            amount=parsed.amount,
            currency=parsed.currency or user.default_currency,
            description=parsed.description,
            category_id=category.id if category else None,
            source_type=SourceType.VOICE,
            raw_input=transcription,
            expense_date=parsed.expense_date,
            group_chat_id=group_chat_id,
        )

        date_str = parsed.expense_date.strftime("%b %d, %Y")
        icon = f"{category_icon} " if category_icon else ""
        currency = parsed.currency or user.default_currency

        # Store expense context for potential corrections
        expense_context = {
            "expense_id": str(expense.id),
            "amount": str(parsed.amount),
            "currency": currency,
            "description": parsed.description,
            "category_name": category_name,
            "category_id": str(category.id) if category else None,
        }
        await state.update_data(last_expense=expense_context)

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
        logger.error(f"Error processing audio: {e}")
        await processing_msg.edit_text(
            "Sorry, I had trouble processing that audio file."
        )

"""Bot middleware for database and user management."""

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.database.connection import get_session
from src.database.repository import UserRepository, LLMConfigRepository
from src.llm.provider import LLMProvider, get_provider_for_user

logger = logging.getLogger(__name__)


class DatabaseMiddleware(BaseMiddleware):
    """Middleware that provides database session to handlers."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Inject database session into handler data."""
        async with get_session() as session:
            data["session"] = session
            return await handler(event, data)


class UserMiddleware(BaseMiddleware):
    """Middleware that ensures user exists and provides user object."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        """Ensure user exists and inject user and LLM provider into handler data."""
        session = data.get("session")
        if not session:
            logger.error("Database session not found in middleware data")
            return await handler(event, data)

        # Get user from event
        user_info = None
        if isinstance(event, Message):
            user_info = event.from_user
        elif isinstance(event, CallbackQuery):
            user_info = event.from_user

        if not user_info:
            return await handler(event, data)

        # Get or create user
        user_repo = UserRepository(session)
        user, created = await user_repo.get_or_create(
            telegram_id=user_info.id,
            username=user_info.username,
            first_name=user_info.first_name,
            last_name=user_info.last_name,
        )

        if created:
            logger.info(f"Created new user: {user_info.id} (@{user_info.username})")

        data["user"] = user

        # Get user's LLM configuration
        llm_repo = LLMConfigRepository(session)
        llm_config = await llm_repo.get_active_config(user.id)

        if llm_config:
            data["llm"] = get_provider_for_user(
                provider=llm_config.provider,
                model=llm_config.model,
                encrypted_api_key=llm_config.api_key_encrypted,
            )
        else:
            # Use default LLM provider
            data["llm"] = get_provider_for_user()

        return await handler(event, data)

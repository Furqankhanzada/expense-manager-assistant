"""Main entry point for the Expense Manager Telegram Bot."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.bot.handlers import (
    commands_router,
    document_router,
    photo_router,
    text_router,
    video_router,
    voice_router,
)
from src.bot.middlewares import ChatContextMiddleware, DatabaseMiddleware, UserMiddleware
from src.config import get_settings
from src.database.connection import create_db_pool, close_db_pool


async def health_check() -> bool:
    """Health check for Docker."""
    return True


async def on_startup(bot: Bot) -> None:
    """Actions to perform on bot startup."""
    logging.info("Bot is starting up...")
    await create_db_pool()

    bot_info = await bot.get_me()
    logging.info(f"Bot started: @{bot_info.username}")


async def on_shutdown(bot: Bot) -> None:
    """Actions to perform on bot shutdown."""
    logging.info("Bot is shutting down...")
    await close_db_pool()


def setup_logging() -> None:
    """Configure application logging."""
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Reduce noise from external libraries
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def create_bot() -> Bot:
    """Create and configure the Telegram bot instance."""
    settings = get_settings()

    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
        ),
    )


def create_dispatcher() -> Dispatcher:
    """Create and configure the dispatcher with routers and middleware."""
    dp = Dispatcher()

    # Register middleware (order matters - ChatContext first to set group context)
    dp.message.middleware(ChatContextMiddleware())
    dp.message.middleware(DatabaseMiddleware())
    dp.message.middleware(UserMiddleware())
    dp.callback_query.middleware(ChatContextMiddleware())
    dp.callback_query.middleware(DatabaseMiddleware())
    dp.callback_query.middleware(UserMiddleware())

    # Register routers (order matters - commands first, then specific handlers, text last)
    dp.include_router(commands_router)
    dp.include_router(voice_router)
    dp.include_router(photo_router)
    dp.include_router(video_router)
    dp.include_router(document_router)
    dp.include_router(text_router)  # Text handler last as catch-all for expenses

    return dp


async def main_async() -> None:
    """Async main function to run the bot."""
    setup_logging()

    bot = create_bot()
    dp = create_dispatcher()

    # Register startup/shutdown hooks
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    logging.info("Starting bot polling...")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")


if __name__ == "__main__":
    main()

"""Bot message handlers."""

from src.bot.handlers.commands import router as commands_router
from src.bot.handlers.document import router as document_router
from src.bot.handlers.photo import router as photo_router
from src.bot.handlers.text import router as text_router
from src.bot.handlers.video import router as video_router
from src.bot.handlers.voice import router as voice_router

__all__ = [
    "commands_router",
    "text_router",
    "voice_router",
    "photo_router",
    "video_router",
    "document_router",
]

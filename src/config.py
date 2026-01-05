"""Application configuration management."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Telegram
    telegram_bot_token: str = Field(..., description="Telegram Bot API token")

    # Database
    database_url: str = Field(
        ...,
        description="PostgreSQL connection URL (asyncpg format)",
    )

    # Default LLM settings
    default_llm_provider: Literal["openai", "gemini", "grok", "ollama"] = Field(
        default="openai",
        description="Default LLM provider",
    )
    default_llm_model: str = Field(
        default="gpt-4o-mini",
        description="Default LLM model",
    )

    # LLM API Keys
    openai_api_key: str | None = Field(default=None, description="OpenAI API key")
    google_api_key: str | None = Field(default=None, description="Google AI API key")
    xai_api_key: str | None = Field(default=None, description="xAI (Grok) API key")

    # Ollama
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server URL",
    )

    # Security
    encryption_key: str = Field(..., description="Fernet encryption key for API keys")

    # Whisper
    whisper_model: str = Field(
        default="base",
        description="Whisper model size (tiny, base, small, medium, large-v3)",
    )

    # Application
    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Debug mode")

    def get_llm_api_key(self, provider: str) -> str | None:
        """Get the API key for a specific LLM provider."""
        key_map = {
            "openai": self.openai_api_key,
            "gemini": self.google_api_key,
            "grok": self.xai_api_key,
            "ollama": None,  # Ollama doesn't need an API key
        }
        return key_map.get(provider)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()

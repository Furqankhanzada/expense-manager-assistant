"""LLM provider abstraction using LiteLLM."""

import base64
import logging
from typing import Any

import litellm
from litellm import acompletion

from src.config import get_settings
from src.utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)

# Map providers to their model prefixes for LiteLLM
PROVIDER_PREFIXES = {
    "openai": "",
    "gemini": "gemini/",
    "grok": "xai/",
    "ollama": "ollama/",
}

# Default models for each provider
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-1.5-flash",
    "grok": "grok-beta",
    "ollama": "llama3.2",
}

# Vision-capable models
VISION_MODELS = {
    "openai": "gpt-4o",
    "gemini": "gemini-1.5-flash",
    "grok": "grok-vision-beta",
    "ollama": "llava",
}


class LLMProvider:
    """Unified LLM provider using LiteLLM."""

    def __init__(
        self,
        provider: str = "openai",
        model: str | None = None,
        api_key: str | None = None,
        encrypted_api_key: str | None = None,
    ):
        self.provider = provider
        self.model = model or DEFAULT_MODELS.get(provider, "gpt-4o-mini")
        self._api_key = api_key
        self._encrypted_api_key = encrypted_api_key
        self._setup_provider()

    def _setup_provider(self) -> None:
        """Configure the LLM provider."""
        settings = get_settings()

        # Determine API key
        if self._encrypted_api_key:
            api_key = decrypt_api_key(self._encrypted_api_key)
        elif self._api_key:
            api_key = self._api_key
        else:
            api_key = settings.get_llm_api_key(self.provider)

        # Set up environment for LiteLLM based on provider
        if self.provider == "openai" and api_key:
            litellm.api_key = api_key
        elif self.provider == "gemini" and api_key:
            litellm.api_key = api_key
        elif self.provider == "grok" and api_key:
            litellm.api_key = api_key
        elif self.provider == "ollama":
            litellm.api_base = settings.ollama_base_url

        # Disable LiteLLM logging noise
        litellm.set_verbose = False

    def _get_model_name(self, use_vision: bool = False) -> str:
        """Get the full model name with provider prefix."""
        prefix = PROVIDER_PREFIXES.get(self.provider, "")

        if use_vision:
            model = VISION_MODELS.get(self.provider, self.model)
        else:
            model = self.model

        return f"{prefix}{model}"

    async def complete(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 1000,
        use_vision: bool = False,
    ) -> str:
        """Send a completion request to the LLM."""
        model = self._get_model_name(use_vision)

        try:
            response = await acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"LLM completion error: {e}")
            raise

    async def complete_with_image(
        self,
        prompt: str,
        image_data: bytes,
        image_type: str = "image/jpeg",
        temperature: float = 0.3,
        max_tokens: int = 1000,
    ) -> str:
        """Send a completion request with an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_type};base64,{base64_image}"
                        },
                    },
                ],
            }
        ]

        return await self.complete(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            use_vision=True,
        )


def get_default_provider() -> LLMProvider:
    """Get the default LLM provider from settings."""
    settings = get_settings()
    return LLMProvider(
        provider=settings.default_llm_provider,
        model=settings.default_llm_model,
    )


def get_provider_for_user(
    provider: str | None = None,
    model: str | None = None,
    encrypted_api_key: str | None = None,
) -> LLMProvider:
    """Get an LLM provider configured for a specific user."""
    settings = get_settings()

    return LLMProvider(
        provider=provider or settings.default_llm_provider,
        model=model or settings.default_llm_model,
        encrypted_api_key=encrypted_api_key,
    )

"""Audio and video transcription using Whisper."""

import logging
import tempfile
from pathlib import Path

import aiofiles
from faster_whisper import WhisperModel

from src.config import get_settings

logger = logging.getLogger(__name__)

# Global model instance (loaded lazily)
_whisper_model: WhisperModel | None = None


def get_whisper_model() -> WhisperModel:
    """Get or initialize the Whisper model."""
    global _whisper_model

    if _whisper_model is None:
        settings = get_settings()
        logger.info(f"Loading Whisper model: {settings.whisper_model}")

        _whisper_model = WhisperModel(
            settings.whisper_model,
            device="auto",  # Use GPU if available, else CPU
            compute_type="auto",
        )
        logger.info("Whisper model loaded successfully")

    return _whisper_model


async def transcribe_audio(audio_data: bytes, file_extension: str = ".ogg") -> str:
    """Transcribe audio data to text.

    Args:
        audio_data: Raw audio bytes
        file_extension: File extension (e.g., .ogg, .mp3, .wav)

    Returns:
        Transcribed text
    """
    # Write audio to temporary file (Whisper needs a file path)
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        async with aiofiles.open(tmp_path, "wb") as f:
            await f.write(audio_data)

    try:
        model = get_whisper_model()

        # Transcribe
        segments, info = model.transcribe(
            str(tmp_path),
            beam_size=5,
            language=None,  # Auto-detect language
            vad_filter=True,  # Filter out non-speech
        )

        # Combine all segments
        text_parts = [segment.text for segment in segments]
        transcription = " ".join(text_parts).strip()

        logger.info(
            f"Transcribed audio: {len(audio_data)} bytes -> {len(transcription)} chars "
            f"(language: {info.language}, probability: {info.language_probability:.2f})"
        )

        return transcription

    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        raise

    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


async def transcribe_voice_message(voice_data: bytes) -> str:
    """Transcribe a Telegram voice message (OGG format)."""
    return await transcribe_audio(voice_data, ".ogg")


async def transcribe_audio_file(audio_data: bytes, mime_type: str) -> str:
    """Transcribe an audio file based on its MIME type."""
    extension_map = {
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mp4": ".m4a",
        "audio/x-m4a": ".m4a",
        "audio/flac": ".flac",
    }

    extension = extension_map.get(mime_type, ".ogg")
    return await transcribe_audio(audio_data, extension)

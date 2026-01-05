"""Video processing for expense extraction."""

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

import aiofiles

from src.media.transcriber import transcribe_audio

logger = logging.getLogger(__name__)


async def extract_audio_from_video(video_data: bytes, file_extension: str = ".mp4") -> bytes | None:
    """Extract audio track from video file.

    Args:
        video_data: Raw video bytes
        file_extension: Video file extension

    Returns:
        Audio data as bytes, or None if extraction failed
    """
    # Create temp files
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as video_tmp:
        video_path = Path(video_tmp.name)

    audio_path = video_path.with_suffix(".wav")

    try:
        # Write video to temp file
        async with aiofiles.open(video_path, "wb") as f:
            await f.write(video_data)

        # Extract audio using ffmpeg
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",  # No video
            "-acodec", "pcm_s16le",  # WAV format
            "-ar", "16000",  # 16kHz sample rate (good for speech)
            "-ac", "1",  # Mono
            "-y",  # Overwrite output
            str(audio_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"ffmpeg error: {stderr.decode()}")
            return None

        # Read extracted audio
        async with aiofiles.open(audio_path, "rb") as f:
            audio_data = await f.read()

        logger.info(f"Extracted {len(audio_data)} bytes of audio from video")
        return audio_data

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install ffmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error extracting audio from video: {e}")
        return None
    finally:
        # Clean up temp files
        video_path.unlink(missing_ok=True)
        audio_path.unlink(missing_ok=True)


async def transcribe_video(video_data: bytes, file_extension: str = ".mp4") -> str | None:
    """Transcribe speech from a video file.

    Args:
        video_data: Raw video bytes
        file_extension: Video file extension (e.g., .mp4, .mov)

    Returns:
        Transcribed text, or None if transcription failed
    """
    # Extract audio from video
    audio_data = await extract_audio_from_video(video_data, file_extension)

    if not audio_data:
        logger.warning("Could not extract audio from video")
        return None

    # Transcribe the audio
    try:
        transcription = await transcribe_audio(audio_data, ".wav")
        return transcription
    except Exception as e:
        logger.error(f"Error transcribing video audio: {e}")
        return None


async def extract_video_frame(
    video_data: bytes,
    timestamp: float = 0.5,
    file_extension: str = ".mp4",
) -> bytes | None:
    """Extract a single frame from a video.

    Args:
        video_data: Raw video bytes
        timestamp: Time in seconds to extract frame from
        file_extension: Video file extension

    Returns:
        JPEG image data, or None if extraction failed
    """
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as video_tmp:
        video_path = Path(video_tmp.name)

    frame_path = video_path.with_suffix(".jpg")

    try:
        # Write video to temp file
        async with aiofiles.open(video_path, "wb") as f:
            await f.write(video_data)

        # Extract frame using ffmpeg
        cmd = [
            "ffmpeg",
            "-ss", str(timestamp),
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "2",  # High quality JPEG
            "-y",
            str(frame_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            logger.error(f"ffmpeg frame extraction error: {stderr.decode()}")
            return None

        # Read extracted frame
        async with aiofiles.open(frame_path, "rb") as f:
            frame_data = await f.read()

        logger.info(f"Extracted frame at {timestamp}s: {len(frame_data)} bytes")
        return frame_data

    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install ffmpeg.")
        return None
    except Exception as e:
        logger.error(f"Error extracting video frame: {e}")
        return None
    finally:
        # Clean up temp files
        video_path.unlink(missing_ok=True)
        frame_path.unlink(missing_ok=True)


async def get_video_duration(video_data: bytes, file_extension: str = ".mp4") -> float | None:
    """Get the duration of a video in seconds."""
    with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as video_tmp:
        video_path = Path(video_tmp.name)

    try:
        async with aiofiles.open(video_path, "wb") as f:
            await f.write(video_data)

        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = await process.communicate()

        if process.returncode == 0:
            return float(stdout.decode().strip())
        return None

    except Exception as e:
        logger.error(f"Error getting video duration: {e}")
        return None
    finally:
        video_path.unlink(missing_ok=True)

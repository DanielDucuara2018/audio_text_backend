"""Audio transcription using faster-whisper.

This module contains the core transcription logic that runs inside a
Cloud Run Job (or the local-worker equivalent).  It has no dependency on
Celery, Redis, or any HTTP framework.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from audio_text_backend.action.audio import storage
from audio_text_backend.config import Config
from audio_text_backend.errors import FileProcessingError, StorageError, TranscriptionError

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()
TMP_FOLDER = BASE_DIR / "tmp"
TMP_FOLDER.mkdir(parents=True, exist_ok=True)

# In-process model cache: one entry per model name for the lifetime of the
# container.  Cloud Run Jobs start fresh per invocation, so the cache covers
# only a single job execution — still avoids reloading if run_transcription is
# called multiple times within one container (e.g., tests).
_whisper_models: dict[str, "WhisperModel"] = {}


def get_whisper_model(model_name: str) -> "WhisperModel":
    """Return a loaded faster-whisper model, loading it on first access."""
    from faster_whisper import WhisperModel  # noqa: PLC0415 — lazy ML import

    if model_name not in _whisper_models:
        logger.info(f"Loading faster-whisper model: {model_name}")
        try:
            _whisper_models[model_name] = WhisperModel(
                model_name,
                device=Config.whisper.device,
                compute_type=Config.whisper.compute_type,
                cpu_threads=Config.whisper.cpu_threads if Config.whisper.cpu_threads > 0 else None,
                num_workers=1,
            )
        except Exception as e:
            raise TranscriptionError(
                message=f"Failed to load Whisper model: {model_name}", error=str(e)
            )

    return _whisper_models[model_name]


def _run_whisper(model: "WhisperModel", file_path: Path) -> tuple[list[Any], Any]:
    """Run faster-whisper inference and return (segments, info)."""
    vad_params = None
    if Config.whisper.vad_filter:
        vad_params = {"min_silence_duration_ms": Config.whisper.vad_min_silence_duration_ms}

    segments, info = model.transcribe(
        str(file_path),
        beam_size=Config.whisper.beam_size,
        word_timestamps=Config.whisper.word_timestamps,
        vad_filter=Config.whisper.vad_filter,
        vad_parameters=vad_params,
        temperature=0.0,
        condition_on_previous_text=True,
    )
    return list(segments), info


def _build_result(segments: list, info: Any) -> dict:
    return {
        "text": " ".join(s.text.strip() for s in segments),
        "language": info.language,
        "language_probability": info.language_probability,
    }


async def run_transcription(filename: str, model_name: str) -> dict:
    """Download the audio file from S3, run Whisper, and return the result.

    Returns a dict with keys:
        text, language, language_probability, processing_time (seconds).
    """
    start = datetime.now()
    file_path = TMP_FOLDER / filename

    try:
        logger.info(f"Downloading {filename} from S3")
        try:
            storage.download_file(filename, file_path)
        except StorageError as e:
            raise FileProcessingError(
                message="Failed to download audio file", filename=filename, error=str(e)
            )

        logger.info(f"Transcribing {filename} with model {model_name}")
        model = get_whisper_model(model_name)
        segments, info = _run_whisper(model, file_path)
        result = _build_result(segments, info)

        processing_time = (datetime.now() - start).total_seconds()
        result["processing_time"] = processing_time

        logger.info(
            f"Transcription done: {len(segments)} segments, "
            f"language={info.language} ({info.language_probability:.2%}), "
            f"time={processing_time:.2f}s"
        )
        return result

    finally:
        if file_path.exists():
            try:
                file_path.unlink()
            except OSError:
                pass
        # Best-effort S3 cleanup — do not propagate cleanup errors.
        try:
            storage.delete_file(filename)
        except StorageError as exc:
            logger.warning(f"Failed to clean up S3 file {filename}: {exc}")

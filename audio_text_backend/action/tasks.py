import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import redis
from celery import current_task

from audio_text_backend.action.audio import storage
from audio_text_backend.celery.app import celery_app as app
from audio_text_backend.config import Config
from audio_text_backend.errors import FileProcessingError, StorageError, TranscriptionError

# Lazy import for type hints only (not at runtime)
if TYPE_CHECKING:
    from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# Add Redis client for publishing
redis_client = redis.Redis.from_url(f"redis://{Config.redis.host}:{Config.redis.port}/0")

BASE_DIR = Path(__file__).parent.resolve()
TMP_FOLDER = BASE_DIR.joinpath("tmp")

# Create input folder if it doesn't exist
if not TMP_FOLDER.exists():
    TMP_FOLDER.mkdir(parents=True, exist_ok=True)

# Load Whisper model once when worker starts (faster-whisper)
# Lazy import to avoid ImportError in API container
whisper_models = {}


def get_whisper_model(model_name: str) -> "WhisperModel":
    """Get or load faster-whisper model with optimized settings."""
    # Lazy import - only imported when worker actually calls this function
    from faster_whisper import WhisperModel

    if model_name not in whisper_models:
        logger.info(f"Loading Faster-Whisper model: {model_name}")
        try:
            whisper_models[model_name] = WhisperModel(
                model_name,
                device=Config.whisper.device,
                compute_type=Config.whisper.compute_type,
                cpu_threads=Config.whisper.cpu_threads if Config.whisper.cpu_threads > 0 else None,
                num_workers=1,  # Let Celery handle parallelism
            )
            logger.info(
                f"Model loaded successfully: {model_name} "
                f"(device={Config.whisper.device}, compute_type={Config.whisper.compute_type})"
            )
        except Exception as e:
            raise TranscriptionError(
                message=f"Failed to load Whisper model: {model_name}", error=str(e)
            )
    return whisper_models[model_name]


def send_redis_update(message: dict) -> None:
    """Send WebSocket update via Redis pub/sub."""
    try:
        redis_client.publish(Config.redis.pub_sub_channel, json.dumps(message))
    except Exception as e:
        logger.warning(f"Failed to send Redis update for job {message['job_id']}: {e}")


@app.task(trail=True)
def process_audio(job_id: str, filename: str, mode: str):
    """Process audio file and extract text using Whisper."""
    logger.info(f"Processing job {job_id} with mode {mode}")
    start_time = datetime.now()
    file_path = None

    try:
        _initialize_job_processing(job_id)
        file_path = _download_audio_file(job_id, filename)
        transcription_result = _transcribe_audio_file(job_id, filename, mode, file_path)
        processing_time = _finalize_job_success(job_id, transcription_result, start_time)
        _cleanup_resources(filename)

        logger.info(f"Successfully processed job {job_id} in {processing_time:.2f}s")
        return {"text": transcription_result["text"], "processing_time": processing_time}
    except (FileProcessingError, TranscriptionError, StorageError) as e:
        _handle_known_error(job_id, e)
        raise
    except Exception as e:
        _handle_unexpected_error(job_id, e)
        raise
    finally:
        _cleanup_temp_file(file_path)


def _initialize_job_processing(job_id: str) -> None:
    """Initialize job processing and send initial progress update."""
    send_redis_update({
        "job_id": job_id,
        "status": "processing",
        "progress": 10,
        "message": "Starting transcription",
        "type": "job_update",
    })


def _download_audio_file(job_id: str, filename: str) -> Path:
    """Download audio file from S3 storage."""
    current_task.update_state(state="PROGRESS", meta={"progress": 20})
    send_redis_update({
        "job_id": job_id,
        "status": "processing",
        "progress": 20,
        "message": "Downloading file",
        "type": "job_update",
    })

    file_path = TMP_FOLDER.joinpath(filename)

    try:
        storage.download_file(filename, file_path)
    except StorageError as e:
        raise FileProcessingError(message="Failed to download file", job_id=job_id, error=str(e))

    return file_path


def _run_transcription(model: "WhisperModel", file_path: Path) -> tuple[list[Any], Any]:
    """Run the actual transcription with configured parameters."""
    vad_params = None
    if Config.whisper.vad_filter:
        vad_params = {"min_silence_duration_ms": Config.whisper.vad_min_silence_duration_ms}

    segments, info = model.transcribe(
        str(file_path),
        beam_size=Config.whisper.beam_size,
        word_timestamps=Config.whisper.word_timestamps,
        vad_filter=Config.whisper.vad_filter,
        vad_parameters=vad_params,
        temperature=0.0,  # Deterministic for consistency
        condition_on_previous_text=True,  # Better context
    )
    return list(segments), info


def _build_transcription_result(segments_list: list, info) -> dict:
    """Build complete transcription result with metadata."""
    # Build complete transcript
    full_text = " ".join([segment.text.strip() for segment in segments_list])

    # Build result with enhanced metadata
    return {
        "text": full_text,
        "language": info.language,
        "language_probability": info.language_probability,
    }


def _transcribe_audio_file(job_id: str, filename: str, mode: str, file_path: Path) -> dict:
    """Transcribe audio file using faster-whisper model."""
    current_task.update_state(state="PROGRESS", meta={"progress": 30})
    send_redis_update({
        "job_id": job_id,
        "status": "processing",
        "progress": 30,
        "message": "File downloaded, starting transcription",
        "type": "job_update",
    })

    logger.info(f"Processing audio file: {filename} with model: {mode}")

    # Load model and run transcription
    model = get_whisper_model(mode)
    segments_list, info = _run_transcription(model, file_path)

    # Build structured result
    result = _build_transcription_result(segments_list, info)

    logger.info(
        f"Transcription complete: {len(segments_list)} segments, "
        f"language={info.language} ({info.language_probability:.2%})"
    )

    return result


def _finalize_job_success(job_id: str, result: dict, start_time: datetime) -> float:
    """Finalize successful job processing and send completion updates."""
    current_task.update_state(state="PROGRESS", meta={"progress": 90})
    send_redis_update({
        "job_id": job_id,
        "status": "processing",
        "progress": 90,
        "message": "Transcription complete, saving results",
        "type": "job_update",
    })

    # Calculate processing time
    processing_time = (datetime.now() - start_time).total_seconds()

    current_task.update_state(state="COMPLETED", meta={"progress": 100})

    # Send completion update with enhanced data
    send_redis_update({
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "result": result["text"],
        "language": result["language"],
        "language_probability": result["language_probability"],
        "processing_time": processing_time,
        "message": "Transcription completed successfully",
        "type": "job_update",
    })

    return processing_time


def _cleanup_resources(filename: str):
    """Clean up S3 file and other resources."""
    try:
        storage.delete_file(filename)
        logger.info(f"Cleaned up S3 file: {filename}")
    except StorageError as e:
        logger.warning(f"Failed to clean up S3 file {filename}: {e}")


def _handle_known_error(job_id: str, error: Exception):
    """Handle known processing errors and update job status."""
    logger.error(f"Processing error for job {job_id}: {str(error)}")

    try:
        send_redis_update({
            "job_id": job_id,
            "status": "failed",
            "error": str(error),
            "message": "Transcription failed",
            "type": "job_update",
        })
    except Exception as update_error:
        logger.error(f"Failed to update job status: {update_error}")

    current_task.update_state(state="FAILURE", meta={"error": str(error)})


def _handle_unexpected_error(job_id: str, error: Exception):
    """Handle unexpected errors during processing."""
    logger.error(f"Unexpected error processing job {job_id}: {str(error)}")
    error_message = f"Unexpected error: {str(error)}"

    try:
        send_redis_update({
            "job_id": job_id,
            "status": "failed",
            "error": error_message,
            "message": "Transcription failed due to unexpected error",
            "type": "job_update",
        })
    except Exception as update_error:
        logger.error(f"Failed to update job status: {update_error}")

    current_task.update_state(state="FAILURE", meta={"error": str(error)})
    raise FileProcessingError(
        message="Unexpected error during processing", job_id=job_id, error=str(error)
    )


def _cleanup_temp_file(file_path: Path):
    """Clean up temporary file if it exists."""
    if file_path and file_path.exists():
        try:
            file_path.unlink()
            logger.info(f"Cleaned up temporary file: {file_path}")
        except Exception as e:
            logger.warning(f"Failed to clean up temporary file {file_path}: {e}")

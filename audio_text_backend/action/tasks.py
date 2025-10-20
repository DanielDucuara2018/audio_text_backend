import json
import logging
from datetime import datetime
from pathlib import Path

import redis
import whisper
from celery import current_task

from audio_text_backend.action.audio import storage
from audio_text_backend.celery.app import celery_app as app
from audio_text_backend.config import Config
from audio_text_backend.errors import FileProcessingError, StorageError, TranscriptionError

logger = logging.getLogger(__name__)

# Add Redis client for publishing
redis_client = redis.Redis.from_url(f"redis://{Config.redis.host}:{Config.redis.port}/0")

BASE_DIR = Path(__file__).parent
TMP_FOLDER = BASE_DIR.joinpath("tmp")

# Create input folder if it doesn't exist
if not TMP_FOLDER.exists():
    TMP_FOLDER.mkdir(parents=True, exist_ok=True)

# Load Whisper model once when worker starts
whisper_models = {}


def get_whisper_model(model_name: str) -> whisper.Whisper:
    """Get or load whisper model."""
    if model_name not in whisper_models:
        logger.info(f"Loading Whisper model: {model_name}")
        try:
            whisper_models[model_name] = whisper.load_model(model_name)
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
        _cleanup_resources(filename, file_path)

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


def _transcribe_audio_file(job_id: str, filename: str, mode: str, file_path: Path) -> dict:
    """Transcribe audio file using Whisper model."""
    current_task.update_state(state="PROGRESS", meta={"progress": 30})
    send_redis_update({
        "job_id": job_id,
        "status": "processing",
        "progress": 30,
        "message": "File downloaded, starting transcription",
        "type": "job_update",
    })

    logger.info(f"Processing audio file: {filename} with model: {mode}")

    try:
        model = get_whisper_model(mode)
        result = model.transcribe(str(file_path))
    except Exception as e:
        raise TranscriptionError(message="Failed to transcribe audio", job_id=job_id, error=str(e))

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
    # Send completion update
    send_redis_update({
        "job_id": job_id,
        "status": "completed",
        "progress": 100,
        "result": result["text"],
        "processing_time": processing_time,
        "message": "Transcription completed successfully",
        "type": "job_update",
    })

    return processing_time


def _cleanup_resources(filename: str, file_path: Path):
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

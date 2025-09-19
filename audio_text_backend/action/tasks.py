import logging
from datetime import datetime
from pathlib import Path

import whisper
from celery import current_task

from audio_text_backend.action.audio import storage
from audio_text_backend.action.job import manager
from audio_text_backend.celery.app import celery_app as app
from audio_text_backend.errors import FileProcessingError, StorageError, TranscriptionError
from audio_text_backend.model import JobStatus, TranscriptionJob

logger = logging.getLogger(__name__)

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


def send_websocket_update(job_id: str, message: dict) -> None:
    """Send WebSocket update safely."""
    try:
        manager.send_job_update_sync(job_id, message)
    except Exception as e:
        logger.warning(f"Failed to send WebSocket update for job {job_id}: {e}")


@app.task(bind=True)
def process_audio(self, job_id: str, mode: str):
    """Process audio file and extract text using Whisper."""
    start_time = datetime.now()
    file_path = None

    try:
        # Get job from database
        job = TranscriptionJob.get(id=job_id)
        job.update(status=JobStatus.PROCESSING)

        # Send WebSocket update
        send_websocket_update(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": 10,
                "message": "Starting transcription",
            },
        )

        file_path = TMP_FOLDER.joinpath(job.filename)

        # Download file from S3
        current_task.update_state(state="PROGRESS", meta={"progress": 20})
        send_websocket_update(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": 20,
                "message": "Downloading file",
            },
        )

        try:
            storage.download_file(job.filename, file_path)
        except StorageError as e:
            raise FileProcessingError(
                message="Failed to download file", job_id=job_id, error=str(e)
            )

        # Send progress update
        current_task.update_state(state="PROGRESS", meta={"progress": 30})
        send_websocket_update(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": 30,
                "message": "File downloaded, starting transcription",
            },
        )

        # Process with Whisper
        logger.info(f"Processing audio file: {job.filename} with model: {mode}")
        try:
            model = get_whisper_model(mode)
            result = model.transcribe(str(file_path))
        except Exception as e:
            raise TranscriptionError(
                message="Failed to transcribe audio", job_id=job_id, error=str(e)
            )

        # Send progress update
        current_task.update_state(state="PROGRESS", meta={"progress": 90})
        send_websocket_update(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": 90,
                "message": "Transcription complete, saving results",
            },
        )

        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()

        # Update job with results
        job.update(
            status=JobStatus.COMPLETED,
            result_text=result["text"],
            processing_time_seconds=int(processing_time),
        )

        # Send completion update
        send_websocket_update(
            job_id,
            {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "result": result["text"],
                "processing_time": processing_time,
                "message": "Transcription completed successfully",
            },
        )

        # Clean up S3 file (optional - configurable)
        try:
            storage.delete_file(job.filename)
            logger.info(f"Cleaned up S3 file: {job.filename}")
        except StorageError as e:
            logger.warning(f"Failed to clean up S3 file {job.filename}: {e}")

        logger.info(f"Successfully processed job {job_id} in {processing_time:.2f}s")
        return {"text": result["text"], "processing_time": processing_time}

    except (FileProcessingError, TranscriptionError, StorageError) as e:
        logger.error(f"Processing error for job {job_id}: {str(e)}")

        try:
            job = TranscriptionJob.get(id=job_id)
            job.update(status=JobStatus.FAILED, error_message=str(e))

            # Send error update via WebSocket
            send_websocket_update(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(e),
                    "message": "Transcription failed",
                },
            )
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")

        current_task.update_state(state="FAILURE", meta={"error": str(e)})
        raise

    except Exception as e:
        logger.error(f"Unexpected error processing job {job_id}: {str(e)}")

        try:
            job = TranscriptionJob.get(id=job_id)
            job.update(status=JobStatus.FAILED, error_message=f"Unexpected error: {str(e)}")

            send_websocket_update(
                job_id,
                {
                    "job_id": job_id,
                    "status": "failed",
                    "error": f"Unexpected error: {str(e)}",
                    "message": "Transcription failed due to unexpected error",
                },
            )
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")

        current_task.update_state(state="FAILURE", meta={"error": str(e)})
        raise FileProcessingError(
            message="Unexpected error during processing", job_id=job_id, error=str(e)
        )

    finally:
        # Clean up temp file if it exists
        if file_path and file_path.exists():
            try:
                file_path.unlink()
                logger.info(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file {file_path}: {e}")

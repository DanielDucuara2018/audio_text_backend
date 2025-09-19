# import requests
import logging
from datetime import datetime
from pathlib import Path

import whisper

from audio_text_backend.action.audio import storage
from audio_text_backend.action.job import manager
from audio_text_backend.celery.app import celery_app as app
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
        whisper_models[model_name] = whisper.load_model(model_name)
    return whisper_models[model_name]


@app.task(bind=True)
async def process_audio(job_id: str, mode: str):
    """Process audio file and extract text using Whisper."""
    start_time = datetime.now()
    file_path = None

    try:
        # Get job from database
        job = TranscriptionJob.get(id=job_id)
        job.update(status=JobStatus.PROCESSING)

        # Send WebSocket update
        await manager.send_job_update(
            job_id, {"job_id": job_id, "status": JobStatus.PROCESSING, "progress": 10}
        )

        file_path = TMP_FOLDER.joinpath(job.filename)

        # Download file from S3
        storage.download_file(job.filename, file_path)

        # Send progress update
        await manager.send_job_update(
            job_id, {"job_id": job_id, "status": JobStatus.PROCESSING, "progress": 30}
        )

        # Process with Whisper
        logger.info(f"Processing audio file: {job.filename} with model: {mode}")
        model = get_whisper_model(mode)
        result = model.transcribe(str(file_path))

        # Send progress update
        await manager.send_job_update(
            job_id, {"job_id": job_id, "status": JobStatus.PROCESSING, "progress": 90}
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
        await manager.send_job_update(
            job_id,
            {
                "job_id": job_id,
                "status": "completed",
                "progress": 100,
                "result": result["text"],
                "processing_time": processing_time,
            },
        )

        logger.info(f"Successfully processed job {job_id} in {processing_time:.2f}s")
        return {"text": result["text"], "processing_time": processing_time}

    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")

        try:
            job = TranscriptionJob.get(id=job_id)
            job.update(status=JobStatus.FAILED, error_message=str(e))

            # Send error update via WebSocket
            await manager.send_job_update(
                job_id, {"job_id": job_id, "status": "failed", "error": str(e)}
            )
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")

        raise

    finally:
        # Clean up temp file if it exists
        if file_path and file_path.exists():
            file_path.unlink(missing_ok=True)
            logger.info(f"Cleaned up temporary file: {file_path}")

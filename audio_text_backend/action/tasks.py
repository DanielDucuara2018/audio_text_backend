# import requests
import logging
from datetime import datetime
from pathlib import Path

import whisper
from celery import current_task

from audio_text_backend.action.audio import storage
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
def process_audio(job_id: str, mode: str):
    """Process audio file and extract text using Whisper."""
    start_time = datetime.now()
    # Get job from database
    job = TranscriptionJob.get(id=job_id)
    job.update(status=JobStatus.PROCESSING)
    file_path = TMP_FOLDER.joinpath(job.filename)
    try:
        # Update task progress
        current_task.update_state(state="PROGRESS", meta={"progress": 10})
        storage.download_file(job.filename, TMP_FOLDER.joinpath(job.filename))

        # Process with Whisper
        current_task.update_state(state="PROGRESS", meta={"progress": 20})
        logger.info(f"Processing audio file: {job.filename} with model: {mode}")
        model = get_whisper_model(mode)
        result = model.transcribe(file_path)

        current_task.update_state(state="PROGRESS", meta={"progress": 90})

        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()

        # Update job with results
        job.status = JobStatus.COMPLETED
        job.update(
            status=JobStatus.COMPLETED,
            result_text=result["text"],
            processing_time_seconds=int(processing_time),
        )

        current_task.update_state(
            state="SUCCESS",
            meta={
                "progress": 100,
                "result": result["text"],
                "processing_time": processing_time,
            },
        )

        logger.info(f"Successfully processed job {job_id} in {processing_time:.2f}s")
        return {"text": result["text"], "processing_time": processing_time}
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {str(e)}")
        job.update(status=JobStatus.FAILED, error_message=str(e))
        current_task.update_state(state="FAILURE", meta={"error": str(e)})
        raise Exception("Error processing audio file") from e
    finally:
        # Clean up temp file if it exists
        logger.info(f"Cleaned up temporary file: {file_path}")
        file_path.unlink(missing_ok=True)

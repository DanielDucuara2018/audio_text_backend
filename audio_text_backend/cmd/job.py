"""Shared job processing logic used by both the Cloud Run Job worker and the local development worker."""

import logging
from dataclasses import dataclass

from audio_text_backend import pubsub as pubsub_module
from audio_text_backend.action.transcription import run_transcription
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob

logger = logging.getLogger(__name__)


@dataclass
class JobPayload:
    """Typed representation of a Pub/Sub transcription job message."""

    job_id: str
    filename: str
    model: str
    url: str


async def process_job(payload: JobPayload) -> None:
    """Run a transcription job end-to-end.

    Marks the job as PROCESSING, runs transcription, then updates the DB record
    and publishes a status event.  Re-raises on failure so callers can
    ack/nack the Pub/Sub message appropriately.
    """
    job_id = payload.job_id
    filename = payload.filename
    model_name = payload.model

    logger.info("[worker] job_id=%s  model=%s  filename=%s", job_id, model_name, filename)

    job = await TranscriptionJob.get(id=job_id)
    await job.update(status=JobStatus.PROCESSING)
    await pubsub_module.publish_status(
        job_id, JobStatus.PROCESSING, message="Transcription started", progress=5
    )

    try:
        result = await run_transcription(filename, model_name)
    except Exception as exc:
        logger.error("[worker] job_id=%s FAILED: %s", job_id, exc, exc_info=True)
        await job.update(status=JobStatus.FAILED, error_message=str(exc))
        await pubsub_module.publish_status(job_id, JobStatus.FAILED, error=str(exc))
        raise

    await job.update(
        status=JobStatus.COMPLETED,
        result_text=result["text"],
        processing_time_seconds=int(result["processing_time"]),
        language=result["language"],
        language_probability=result["language_probability"],
    )
    await pubsub_module.publish_status(
        job_id,
        JobStatus.COMPLETED,
        result=result["text"],
        language=result["language"],
        language_probability=result["language_probability"],
        processing_time=result["processing_time"],
    )
    logger.info("[worker] job_id=%s completed in %.2fs", job_id, result["processing_time"])

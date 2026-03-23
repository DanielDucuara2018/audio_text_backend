import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from audio_text_backend.action.email import get_email_service
from audio_text_backend.action.job import create as add_job
from audio_text_backend.action.job import establish_connection
from audio_text_backend.action.job import read as read_jobs
from audio_text_backend.db import get_session
from audio_text_backend.model.transcription_job import JobStatus
from audio_text_backend.schema.job import (
    EmailTranscriptionRequest,
    EmailTranscriptionResponse,
    TranscribeRequest,
    TranscribeResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/job",
    tags=["job"],
    responses={404: {"description": "Not found"}},
)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    request: TranscribeRequest,
):
    """Start audio transcription job."""
    # create() manages its own session so the DB commit happens before the
    # Pub/Sub publish — no Depends(get_session) needed here.
    return await add_job(request.filename, request.url, request.mode)


@router.get("/status/{job_id}", response_model=TranscribeResponse)
async def get_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> TranscribeResponse:
    """Get transcription job status and results."""
    return await read_jobs(job_id, session=session)


@router.get("/read", response_model=list[TranscribeResponse])
async def read(
    session: AsyncSession = Depends(get_session),
) -> list[TranscribeResponse]:
    """List all transcription jobs."""
    return await read_jobs(session=session)


@router.post("/{job_id}/email", response_model=EmailTranscriptionResponse)
async def email_transcription(
    job_id: str,
    request: EmailTranscriptionRequest,
    session: AsyncSession = Depends(get_session),
):
    """Send transcription results via email."""
    if not request.email:
        raise HTTPException(status_code=400, detail="Email address is required")

    job = await read_jobs(job_id, session=session)

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot email transcription. Job status is '{job.status}', expected 'completed'",
        )

    if not job.result_text:
        raise HTTPException(
            status_code=400, detail="Cannot email transcription. Job has no results"
        )

    email_service = get_email_service()
    success = email_service.send_transcription(job, request.email)

    if success:
        return EmailTranscriptionResponse(
            success=True, message=f"Transcription sent successfully to {request.email}"
        )
    raise HTTPException(status_code=500, detail="Failed to send email. Please try again later")


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates."""
    logger.info(f"WebSocket connection attempt for job: {job_id}")
    try:
        await establish_connection(job_id, websocket)
    except Exception as e:
        logger.error(f"Fatal error in WebSocket endpoint for job {job_id}: {e}")

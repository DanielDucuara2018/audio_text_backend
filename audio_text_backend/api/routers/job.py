import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from audio_text_backend.action.job import manager
from audio_text_backend.action.tasks import process_audio
from audio_text_backend.errors import DBError, NoDataFound
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob
from audio_text_backend.typing import CustomDateTime

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/job",
    tags=["job"],
    responses={404: {"description": "Not found"}},
)


class TranscribeRequest(BaseModel):
    filename: str
    mode: str
    url: str


class TranscribeResponse(BaseModel):
    job_id: str
    filename: str
    status: str
    message: str
    creation_date: CustomDateTime
    update_date: CustomDateTime | None = None
    result: str | None = None
    processing_time: float | None = None
    error: str | None = None


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest) -> TranscribeResponse:
    """Start audio transcription job."""
    try:
        # Create job record in database
        job = TranscriptionJob(
            filename=request.filename, url=request.url, status=JobStatus.PENDING
        ).create()

        # Start background processing with Celery
        process_audio.delay(job.id, request.mode)

        return job
    except DBError as e:
        logger.error(f"Database error creating transcription job: {e}")
        raise HTTPException(
            status_code=500, detail=f"Database error: {e.data.get('error', str(e))}"
        )
    except Exception as e:
        logger.error(f"Unexpected error creating transcription job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start transcription: {str(e)}")


@router.get("/status/{job_id}", response_model=TranscribeResponse)
async def get_status(job_id: str) -> TranscribeResponse:
    """Get transcription job status and results."""
    try:
        return TranscriptionJob.get(id=job_id)
    except NoDataFound:
        logger.warning(f"Job not found: {job_id}")
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    except DBError as e:
        logger.error(f"Database error getting job status: {e}")
        raise HTTPException(
            status_code=500, detail=f"Database error: {e.data.get('error', str(e))}"
        )
    except Exception as e:
        logger.error(f"Unexpected error getting job status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.get("/read", response_model=list[TranscribeResponse])
async def read() -> list[TranscribeResponse]:
    """List all transcription jobs."""
    try:
        return TranscriptionJob.find()
    except DBError as e:
        logger.error(f"Database error retrieving jobs: {e}")
        raise HTTPException(
            status_code=500, detail=f"Database error: {e.data.get('error', str(e))}"
        )
    except Exception as e:
        logger.error(f"Unexpected error retrieving jobs: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving jobs: {str(e)}")


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates."""
    await manager.connect(websocket, job_id)
    try:
        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "job_id": job_id,
            "message": "Connected to job updates",
        })

        while True:
            # Keep connection alive and handle any client messages
            data = await websocket.receive_text()
            # Echo back for connection testing
            await websocket.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job: {job_id}")
        manager.disconnect(websocket, job_id)
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
        manager.disconnect(websocket, job_id)

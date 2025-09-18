import logging

from dev.audio_text_backend.audio_text_backend.action.tasks import process_audio
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from audio_text_backend.action.job import manager
from audio_text_backend.model.transcription_job import JobStatus, TranscriptionJob

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


@router.post("/transcribe")
async def transcribe(request: TranscribeRequest):
    """Start audio transcription job."""
    try:
        # Generate unique job ID and S3 key
        # Create job record in database
        job = TranscriptionJob(
            filename=request.filename, url=request.url, status=JobStatus.PENDING
        ).create()

        # Start background processing with Celery
        process_audio.delay(job.id, request.mode)

        return {
            "job_id": job.id,
            "filename": request.filename,
            "status": JobStatus.PENDING.value,
            "message": "Transcription job started successfully.",
        }

    except Exception as e:
        logger.error(f"Error creating transcription job: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to start transcription: {str(e)}")


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    """Get transcription job status and results."""
    try:
        job = TranscriptionJob.get(job_id)
        response = {
            "job_id": job.id,
            "filename": job.filename,
            "status": job.status.value,
            "creation_date": job.creation_date,
            "update_date": job.update_date,
        }
        if job.status == JobStatus.COMPLETED:
            response["result"] = job.result_text
            response["processing_time"] = job.processing_time_seconds
        elif job.status == JobStatus.FAILED:
            response["error"] = job.error_message
        return response
    except Exception as e:
        logger.error(f"Error getting job status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get job status: {str(e)}")


@router.get("/jobs")
async def read():
    """List all transcription jobs."""
    try:
        return TranscriptionJob.find()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error retrieving events: {str(e)}")


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    """WebSocket endpoint for real-time job updates."""
    await manager.connect(websocket, job_id)
    try:
        while True:
            # Keep connection alive and handle any client messages
            data = await websocket.receive_text()
            # Echo back for connection testing
            await websocket.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)

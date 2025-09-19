import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from audio_text_backend.action.job import create as add_job
from audio_text_backend.action.job import manager
from audio_text_backend.errors import DBError, NoDataFound
from audio_text_backend.model.transcription_job import TranscriptionJob
from audio_text_backend.schema.job import TranscribeRequest, TranscribeResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/job",
    tags=["job"],
    responses={404: {"description": "Not found"}},
)


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(request: TranscribeRequest):
    """Start audio transcription job."""
    try:
        return add_job(request.filename, request.url, request.mode)
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
    logger.info(f"WebSocket connection attempt for job: {job_id}")

    try:
        await manager.connect(websocket, job_id)

        # Send initial connection confirmation
        await websocket.send_json({
            "type": "connected",
            "job_id": job_id,
            "message": "Connected to job updates",
            "timestamp": datetime.now().isoformat(),
        })

        # Keep connection alive and handle any client messages
        while True:
            try:
                # Wait for client messages with timeout
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)

                # Echo back for connection testing
                await websocket.send_json({
                    "type": "echo",
                    "data": data,
                    "timestamp": datetime.now().isoformat(),
                })

            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_json({"type": "ping", "timestamp": datetime.now().isoformat()})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for job: {job_id}")
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
    finally:
        manager.disconnect(websocket, job_id)

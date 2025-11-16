import logging

from fastapi import APIRouter, HTTPException, WebSocket

from audio_text_backend.action.job import create as add_job
from audio_text_backend.action.job import establish_connection
from audio_text_backend.action.job import read as read_jobs
from audio_text_backend.errors import DBError, NoDataFound
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
        return await add_job(request.filename, request.url, request.mode)
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
        return read_jobs(job_id)
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
        return read_jobs()
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
        await establish_connection(job_id, websocket)
    except Exception as e:
        logger.error(f"Fatal error in WebSocket endpoint for job {job_id}: {e}")

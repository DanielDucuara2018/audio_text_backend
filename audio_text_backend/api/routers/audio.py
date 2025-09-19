import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from audio_text_backend.action.audio import storage, validate_audio_file
from audio_text_backend.schema.audio import FileGeneratePresignedUrlResponse

logger = logging.getLogger(__name__)

UPLOAD_DIR_PATH = Path("/tmp/uploads")
TRANSCRIPTION_DIR_PATH = Path("/tmp/transcriptions")

router = APIRouter(
    prefix="/audio",
    tags=["audio"],
    responses={404: {"description": "Not found"}},
)


@router.get("/get_presigned_url", response_model=FileGeneratePresignedUrlResponse)
async def get_presigned_url(
    filename: str, content_type: str, file_size: int
) -> FileGeneratePresignedUrlResponse:
    try:
        validate_audio_file(filename, content_type, file_size)
        url = storage.get_presigned_url(filename, content_type)
        return FileGeneratePresignedUrlResponse(url=url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error generating presigned URL: {str(e)}")

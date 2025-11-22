from pydantic import BaseModel, ConfigDict, EmailStr, Field

from audio_text_backend.model.transcription_job import JobStatus
from audio_text_backend.typing import CustomDateTime


class TranscribeRequest(BaseModel):
    filename: str
    mode: str
    url: str


class TranscribeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    status: JobStatus
    creation_date: CustomDateTime
    update_date: CustomDateTime | None = None
    result_text: str | None = None
    processing_time_seconds: float | None = None
    error_message: str | None = None
    language: str | None = None
    language_probability: float | None = None
    whisper_model: str | None = None


class EmailTranscriptionRequest(BaseModel):
    """Request to email transcription results."""

    email: EmailStr = Field(..., description="Email address to send transcription to")


class EmailTranscriptionResponse(BaseModel):
    """Response for email send operation."""

    success: bool
    message: str

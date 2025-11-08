from pydantic import BaseModel, ConfigDict

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
    # TODO New fields from faster-whisper
    # language: str | None = None
    # language_probability: float | None = None
    # duration: float | None = None

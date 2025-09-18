from enum import Enum

from sqlalchemy import Enum as SQLAEnum
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from audio_text_backend.model.base import Base
from audio_text_backend.model.resource import Resource
from audio_text_backend.utils import idun


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TranscriptionJob(Base, Resource):
    __tablename__ = "transcription_job"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: idun("transcription_job")
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[JobStatus] = mapped_column(SQLAEnum(JobStatus), default=JobStatus.PENDING)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_time_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

import logging
import os
import signal
from multiprocessing import Process
from pathlib import Path

import magic
import whisper
from fastapi import APIRouter, UploadFile
from fastapi.responses import StreamingResponse

from audio_text_backend.schema import fileRequest, terminateRequest
from audio_text_backend.utils import generate_random_name

logger = logging.getLogger(__name__)

UPLOAD_DIR_PATH = Path("/tmp/uploads")
TRANSCRIPTION_DIR_PATH = Path("/tmp/transcriptions")

router = APIRouter(
    prefix="/audio",
    tags=["audio"],
    responses={404: {"description": "Not found"}},
)


def run_trascription(file_path: Path, mode: str, transcription_filename: str) -> None:
    model = whisper.load_model(mode)
    result = model.transcribe(str(file_path))
    text = result["text"]
    final_file_path = TRANSCRIPTION_DIR_PATH.joinpath(transcription_filename)
    final_file_path.parent.mkdir(parents=True, exist_ok=True)
    final_file_path.write_text(text)


@router.post("/upload")
async def upload(file: UploadFile):
    filename = file.filename
    name, extension = filename.split(".")
    new_filename = f"{generate_random_name(name)}.{extension}"
    file_path = UPLOAD_DIR_PATH.joinpath(new_filename)
    logger.info("file %s is uploading into %s", filename, file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_data = await file.read()
    file_path.write_bytes(file_data)
    return {"filename": new_filename}


@router.post("/transcribe")
async def transcribe(data: fileRequest):
    filename = data.filename
    file_path = UPLOAD_DIR_PATH.joinpath(filename)
    logger.info("Getting text from audio file %s located in %s", filename, file_path)
    name, _ = filename.split(".")
    transcription_filename = f"{name}.txt"
    process = Process(
        target=run_trascription, args=(file_path, data.mode, transcription_filename)
    )
    process.start()
    return {
        "transcription_filename": transcription_filename,
        "pid_process": process.pid,
    }


@router.post("/terminate")
async def terminate_transcription(data: terminateRequest) -> None:
    os.kill(data.pid, signal.SIGKILL)


@router.get("/transcription")
async def get_transcription(filename: str):
    file_path = TRANSCRIPTION_DIR_PATH.joinpath(filename)
    text = None
    if file_path.exists():
        text = file_path.read_text(encoding="utf-8")
    return {"transcription": text}


@router.get("/data")
async def get_audio_data(filename: str) -> StreamingResponse:
    file_path = UPLOAD_DIR_PATH.joinpath(filename)
    content_type = magic.Magic(mime=True).from_file(file_path)
    logger.info("Sending data of file %s wiht content type %s", file_path, content_type)

    def iterfile():
        with open(file_path, "rb") as f:
            yield from f

    return StreamingResponse(iterfile(), media_type=content_type)

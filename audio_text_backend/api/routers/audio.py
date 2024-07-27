from pathlib import Path

import logging
import whisper
from fastapi import APIRouter,UploadFile
from audio_text_backend.schema import fileRequest
from audio_text_backend.utils import generate_random_name
from multiprocessing import Process
from asyncio import sleep

logger = logging.getLogger(__name__)

UPLOAD_DIR_PATH = Path("/tmp/uploads")
TRANSCRIPTION_DIR_PATH = Path("/tmp/transcriptions")

router = APIRouter(
    prefix="/audio",
    tags=["audio"],
    responses={404: {"description": "Not found"}},
)

def run_trascription(file_path: Path, mode: str, transcription_filename: str):
    model = whisper.load_model(mode)
    result = model.transcribe(str(file_path))
    text = result["text"]
    final_file_path = TRANSCRIPTION_DIR_PATH.joinpath(transcription_filename)
    final_file_path.parent.mkdir(parents=True, exist_ok=True)
    final_file_path.write_text(text)

@router.post("/upload/")
async def upload(file: UploadFile):
    filename = file.filename
    name, extension = filename.split(".")
    new_filename = f"{generate_random_name(name)}.{extension}"
    file_path = UPLOAD_DIR_PATH.joinpath(new_filename)
    logger.info("file %s is uploading into %s", filename, file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(await file.read())
    await sleep(1) # TODO check if the file exists on frontend side
    return {"filename": new_filename}


@router.post("/transcribe/")
async def transcribe(data: fileRequest):
    filename = data.filename
    file_path = UPLOAD_DIR_PATH.joinpath(filename)
    logger.info("Getting text from audio file %s located in %s", filename, file_path)
    name, _ = filename.split(".")
    transcription_filename = f"{name}.txt"
    process = Process(target=run_trascription, args=(file_path, data.mode, transcription_filename))
    process.start()
    return {"transcription_filename": transcription_filename}


@router.get("/transcription/")
async def get_transcription(filename: str):
    file_path = TRANSCRIPTION_DIR_PATH.joinpath(filename)
    text = None
    if file_path.exists():
        text = file_path.read_text(encoding="utf-8")
    await sleep(1) # TODO check if the file exists on frontend side
    return {"transcription": text}




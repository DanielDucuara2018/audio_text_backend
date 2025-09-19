import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audio_text_backend.api.routers.audio import router as audio_router
from audio_text_backend.api.routers.job import router as job_router
from audio_text_backend.db import initialize

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

initialize(True)

app = FastAPI(title="Audio Text Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router, prefix=API_PREFIX)
app.include_router(job_router, prefix=API_PREFIX)

@app.get(API_PREFIX)
async def root():
    return {"message": "Welcome to audio_text app"}

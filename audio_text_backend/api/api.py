import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audio_text_backend.api.routers.audio import router as audio_router

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router)


@app.get("/")
async def root():
    return {"message": "Welcome to audio_text app"}

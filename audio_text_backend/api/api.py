import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audio_text_backend.api.routers.audio import router as audio_router
from audio_text_backend.api.routers.job import router as job_router
from audio_text_backend.config import Config
from audio_text_backend.db import initialize

# from audio_text_backend.middleware import RateLimitMiddleware

# from audio_text_backend.action.job import manager

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

initialize(True)

app = FastAPI(title="Audio Text Backend", version="0.1.0")

# app.add_middleware(
#     RateLimitMiddleware,
#     requests_per_minute="60",
#     requests_per_hour="1000",
# )

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.middleware.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# @app.on_event("shutdown")
# async def shutdown_event():
#     """Cleanup services on shutdown."""
#     logger.info("Shutting down Audio Text Backend")
#     try:
#         await manager.stop_listening()
#     except Exception as e:
#         logger.error(f"Error during Redis cleanup: {e}")

app.include_router(audio_router, prefix=API_PREFIX)
app.include_router(job_router, prefix=API_PREFIX)


@app.get(API_PREFIX)
async def root():
    return {"message": "Welcome to audio_text app"}


@app.get("/")
async def healthcheck():
    return {"message": "audio_text app alive"}

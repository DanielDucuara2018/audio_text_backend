import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from audio_text_backend import db
from audio_text_backend.api.routers.audio import router as audio_router
from audio_text_backend.api.routers.job import router as job_router
from audio_text_backend.api.routers.pubsub import router as pubsub_router
from audio_text_backend.config import Config
from audio_text_backend.errors import (
    DBError,
    Error,
    FileProcessingError,
    FileValidationError,
    NoDataFound,
    StorageError,
    TranscriptionError,
)

# from audio_text_backend.middleware import RateLimitMiddleware

# from audio_text_backend.action.job import manager

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Migrations are run once by start-api.sh before workers start.
    await db.run_migrations_async(Config.database.skip_alembic_migration)
    await db.init()
    yield


app = FastAPI(title="Audio Text Backend", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(NoDataFound)
async def no_data_found_handler(request: Request, exc: NoDataFound) -> JSONResponse:
    logger.info("Resource not found on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=404,
        content={"detail": "Resource not found"},
    )


@app.exception_handler(FileValidationError)
async def file_validation_error_handler(request: Request, exc: FileValidationError) -> JSONResponse:
    logger.warning("File validation failed on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=422,
        content={"detail": exc.data.get("message", "File validation failed")},
    )


@app.exception_handler(TranscriptionError)
@app.exception_handler(FileProcessingError)
async def processing_error_handler(request: Request, exc: Error) -> JSONResponse:
    logger.error("Processing error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "An error occurred while processing the file"},
    )


@app.exception_handler(StorageError)
@app.exception_handler(DBError)
async def service_unavailable_handler(request: Request, exc: Error) -> JSONResponse:
    logger.error("Service error on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Service temporarily unavailable, please try again"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception on %s: %s", request.url.path, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# app.add_middleware(
#     RateLimitMiddleware,
#     requests_per_minute="60",
#     requests_per_hour="1000",
# )

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.middleware.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(audio_router, prefix=API_PREFIX)
app.include_router(job_router, prefix=API_PREFIX)
app.include_router(pubsub_router, prefix=API_PREFIX)


@app.get(API_PREFIX)
async def root():
    return {"message": "Welcome to audio_text app"}


@app.get("/")
async def healthcheck():
    return {"message": "audio_text app alive"}

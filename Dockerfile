# Multi-stage Dockerfile for Audio Text Backend
# Supports: development, production API, and production Celery worker

# ============================================================================
# BASE STAGE - Common dependencies for all variants
# ============================================================================
FROM python:3.12-slim-bookworm AS base

WORKDIR /app

# Install common system dependencies (only libmagic, not ffmpeg)
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    libmagic1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files for better layer caching
COPY pyproject.toml README.md ./

# ============================================================================
# DEPENDENCIES STAGE - Install Python dependencies
# ============================================================================
FROM base AS dependencies

# Upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip

# Install base Python dependencies (API core - without ML/Whisper)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --editable .

# ============================================================================
# DEV STAGE - Development environment with hot reload
# ============================================================================
FROM dependencies AS dev

# Install ffmpeg for audio processing in development
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install worker dependencies for local testing
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --editable ".[worker]"

# Copy source code
COPY . .

EXPOSE 3203

# Default command for API dev server with hot reload and debug logging
CMD ["uvicorn", "audio_text_backend.api.api:app", "--host", "0.0.0.0", "--port", "3203", "--log-level", "debug", "--reload"]

# ============================================================================
# API PRODUCTION STAGE - Lightweight API without ML libraries
# ============================================================================
FROM dependencies AS api

# Copy only necessary files for API
COPY audio_text_backend/ ./audio_text_backend/
COPY alembic/ ./alembic/
COPY config.ini ./

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 3203

# Production API server (no reload)
CMD ["uvicorn", "audio_text_backend.api.api:app", "--host", "0.0.0.0", "--port", "3203", "--workers", "4"]

# ============================================================================
# WORKER PRODUCTION STAGE - Celery worker with ML/Whisper
# ============================================================================
FROM base AS worker

# Install ffmpeg for audio processing
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --upgrade pip

# Install core dependencies + ML/worker dependencies
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir --editable ".[worker]"

# Copy application code
COPY audio_text_backend/ ./audio_text_backend/
COPY config.ini ./

# Pre-download Whisper models during build (cache them in the image)
# This prevents downloads during container startup
RUN python -c "import whisper; \
    whisper.load_model('tiny'); \
    whisper.load_model('base'); \
    whisper.load_model('small')"

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Celery worker command
CMD ["celery", "-A", "audio_text_backend.celery.app", "worker", \
    "--loglevel=info", \
    "--concurrency=1", \
    "--max-tasks-per-child=5", \
    "-Q", "audio_processing"]

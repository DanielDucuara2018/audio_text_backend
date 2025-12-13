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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy dependency files for better layer caching
COPY pyproject.toml uv.lock README.md ./

# ============================================================================
# DEPENDENCIES STAGE - Install Python dependencies
# ============================================================================
FROM base AS dependencies

# Use --frozen to ensure exact versions from lock file
RUN uv sync --frozen

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

# Install worker dependencies (faster-whisper) for local testing
RUN uv sync --frozen --extra worker

# Copy source code
COPY . .

EXPOSE 3203

# Default command for API dev server with hot reload and debug logging
CMD ["uv", "run", "uvicorn", "audio_text_backend.api.api:app", "--host", "0.0.0.0", "--port", "3203", "--log-level", "debug", "--reload"]

# ============================================================================
# API PRODUCTION STAGE - Lightweight API without ML libraries
# ============================================================================
FROM dependencies AS api

# Copy only necessary files for API
COPY audio_text_backend/ ./audio_text_backend/
COPY alembic/ ./alembic/
COPY config.ini ./
COPY scripts/start-api.sh ./scripts/

# Make startup script executable
RUN chmod +x ./scripts/start-api.sh

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 3203

# Production API server with automatic migrations
CMD ["./scripts/start-api.sh"]

# ============================================================================
# WORKER PRODUCTION STAGE - Celery worker with faster-whisper
# ============================================================================
FROM base AS worker

# Install ffmpeg for audio processing
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends \
    ffmpeg && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install core dependencies + ML/worker dependencies (faster-whisper)
# Note: pyproject.toml and uv.lock already copied from base stage
RUN uv sync --frozen --extra worker

# Copy application code
COPY audio_text_backend/ ./audio_text_backend/
COPY config.ini ./
COPY scripts/start_worker.sh ./scripts/

# Make the start script executable
RUN chmod +x scripts/start_worker.sh

# Pre-download faster-whisper CTranslate2 models with int8 quantization
# This prevents downloads during container startup and reduces image size
RUN uv run python -c "from faster_whisper import WhisperModel; \
    print('Downloading tiny model...'); \
    WhisperModel('tiny', device='cpu', compute_type='int8'); \
    print('Downloading base model...'); \
    WhisperModel('base', device='cpu', compute_type='int8'); \
    print('Downloading small model...'); \
    WhisperModel('small', device='cpu', compute_type='int8'); \
    print('All models downloaded successfully!')"

# Create non-root user for security
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

# Celery worker with health check HTTP server
CMD ["./scripts/start_worker.sh"]

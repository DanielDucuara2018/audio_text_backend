#!/bin/bash
# Startup script for the API server.
# Migrations run once here (synchronously, before workers start) to avoid
# race conditions when multiple uvicorn workers enter lifespan concurrently.

set -e

cd /app

# echo "Running database migrations..."
# uv run python -c "import asyncio; from audio_text_backend.db import run_migrations_async; asyncio.run(run_migrations_async())"
# echo "Migrations complete."

# Start uvicorn with workers using UV
exec uv run uvicorn audio_text_backend.api.api:app \
    --host 0.0.0.0 \
    --port "${PORT:-3203}" \
    --workers "${WORKERS:-1}"

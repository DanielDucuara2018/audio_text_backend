#!/bin/bash
# Startup script for API with automatic migrations

set -e

echo "Running database migrations..."
cd /app

# Run migrations using UV-managed Python environment
uv run python -c "from audio_text_backend.db import initialize; initialize(update_schema=True)"

echo "Migrations complete. Starting API server..."

# Start uvicorn with workers using UV
exec uv run uvicorn audio_text_backend.api.api:app \
    --host 0.0.0.0 \
    --port "${PORT:-3203}" \
    --workers "${WORKERS:-4}"

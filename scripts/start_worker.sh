#!/bin/bash
# Start script for Celery worker with HTTP health check endpoint
# Required for Cloud Run which expects containers to listen on a port
# Supports multiple queue configurations via environment variables

set -e

# Queue and concurrency configuration via environment variables
# Defaults to fallback queue (audio_processing) with concurrency=2
QUEUE_NAME=${CELERY_QUEUE:-audio_processing}
CONCURRENCY=${CELERY_CONCURRENCY:-2}

echo "Starting Celery worker with queue: $QUEUE_NAME, concurrency: $CONCURRENCY"

# Start a simple HTTP server for health checks in the background on port 8080
uv run python -m http.server ${PORT:-8080} &
HTTP_PID=$!

# Start Celery worker with configurable queue and concurrency using UV
uv run celery -A audio_text_backend.celery.app worker \
    --loglevel=info \
    --concurrency=$CONCURRENCY \
    --max-tasks-per-child=10 \
    -Q $QUEUE_NAME &
CELERY_PID=$!

# Function to handle shutdown gracefully
shutdown() {
    echo "Shutting down..."
    kill $CELERY_PID 2>/dev/null || true
    kill $HTTP_PID 2>/dev/null || true
    exit 0
}

# Trap termination signals
trap shutdown SIGTERM SIGINT

# Wait for either process to exit
wait -n $CELERY_PID $HTTP_PID

# If we get here, one process died - shut down the other
shutdown

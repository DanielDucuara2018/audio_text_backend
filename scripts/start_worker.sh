#!/bin/bash
# Start script for Celery worker with HTTP health check endpoint
# Required for Cloud Run which expects containers to listen on a port

set -e

# Start a simple HTTP server for health checks in the background on port 8080
python -m http.server ${PORT:-8080} &
HTTP_PID=$!

# Start Celery worker
celery -A audio_text_backend.celery.app worker \
    --loglevel=info \
    --concurrency=1 \
    --max-tasks-per-child=5 \
    -Q audio_processing &
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

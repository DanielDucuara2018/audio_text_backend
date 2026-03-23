#!/bin/bash
# Cloud Run Job entrypoint for the audio transcription worker.
#
# Cloud Run Jobs inject JOB_PAYLOAD (the decoded Pub/Sub message data JSON)
# as an environment variable before starting the container.
#
# Exit codes:
#   0  — success; Pub/Sub acknowledges the message.
#   ≠0 — failure; Pub/Sub retries with exponential back-off.

set -e

echo "Starting transcription worker..."
exec uv run python -m audio_text_backend.cmd.worker

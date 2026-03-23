#!/bin/bash
# Start the full local development environment using docker-compose.
#
# Services started:
#   app           — FastAPI API server (hot-reload, port 3203)
#   postgres      — PostgreSQL 17 (port 5432)
#   pubsub-emulator — Google Cloud Pub/Sub emulator (port 8085)
#   local-worker  — Pull-based worker simulating Cloud Run Jobs

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Ensure .env exists
"$SCRIPT_DIR/populate-env-variables.sh"

if [ $? -eq 0 ] && [ ! -s "$SCRIPT_DIR/../.env" ]; then
    exit 0
fi

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

echo "Starting audio-text backend development environment..."
docker-compose up -d --build

echo ""
echo "Services ready:"
echo "  API:            http://localhost:3203"
echo "  Database:       localhost:5432"
echo "  Pub/Sub emulator: localhost:8085"
echo ""
echo "Commands:"
echo "  Logs:  docker-compose logs -f"
echo "  Stop:  docker-compose down"

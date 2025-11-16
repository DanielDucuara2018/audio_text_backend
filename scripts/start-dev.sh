#!/bin/bash

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Run populate-env-variables.sh to ensure .env exists
"$SCRIPT_DIR/populate-env-variables.sh"

# If populate script exited (waiting for user to edit .env), stop here
if [ $? -eq 0 ] && [ ! -s "$SCRIPT_DIR/../.env" ]; then
    exit 0
fi

# Enable Docker BuildKit for faster builds
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1

# Check for multi-queue flag
MULTI_QUEUE=false
if [[ "$1" == "--multi-queue" || "$1" == "-m" ]]; then
    MULTI_QUEUE=true
fi

echo "🚀 Starting audio-text backend development..."
echo "   ✅ Docker BuildKit enabled"
echo ""

# Build and start services
if [ "$MULTI_QUEUE" = true ]; then
    echo "🐳 Building with multi-queue workers (small/medium/large)..."
    docker-compose --profile multi-queue up -d --build
    WORKER_MODE="multi-queue (small/medium/large queues)"
else
    echo "🐳 Building with default single worker (listens to all queues)..."
    docker-compose --profile default up -d --build
    WORKER_MODE="single worker (listens to all queues)"
fi

echo ""
echo "✅ Development environment ready!"
echo ""
echo "🌐 Services:"
echo "   API:      http://localhost:3203"
echo "   Database: localhost:5432"
echo "   Redis:    localhost:6379"
echo "   Workers:  $WORKER_MODE"
echo ""
echo "📝 Commands:"
echo "   Logs: docker-compose logs -f"
echo "   Stop: docker-compose down"
echo "   Multi-queue: $0 --multi-queue"

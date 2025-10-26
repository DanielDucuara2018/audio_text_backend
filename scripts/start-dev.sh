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

echo "🚀 Starting optimized audio-text backend development with BuildKit..."
echo "   ✅ DOCKER_BUILDKIT=1 (parallel builds, advanced caching)"
echo "   ✅ Layer caching optimization"
echo "   ✅ Selective volume mounting"
echo ""

# Build and start services
echo "🐳 Building and starting services..."
docker-compose up -d --build

echo ""
echo "✅ Development environment ready!"
echo ""
echo "🌐 Services:"
echo "   API:      http://localhost:3203"
echo "   Database: localhost:5432"
echo "   Redis:    localhost:6379"
echo ""
echo "📝 Useful commands:"
echo "   Logs: docker-compose logs -f"
echo "   Stop: docker-compose down"
echo "   Rebuild: docker-compose up -d --build"

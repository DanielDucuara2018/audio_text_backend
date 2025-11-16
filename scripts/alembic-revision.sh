#!/bin/bash

# Helper script to run Alembic commands with environment variables loaded
# Usage:
#   ./scripts/alembic-revision.sh "Migration message"           # Create new migration
#   ./scripts/alembic-revision.sh upgrade                       # Upgrade to head
#   ./scripts/alembic-revision.sh upgrade +1                    # Upgrade one revision
#   ./scripts/alembic-revision.sh downgrade -1                  # Downgrade one revision
#   ./scripts/alembic-revision.sh downgrade base                # Downgrade to base

set -e

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$SCRIPT_DIR/.."

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "Error: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Determine the command
COMMAND="${1:-revision}"

# Run alembic with env variables from .env file
# The 'env' command ensures variables are passed to the subprocess
# PYTHONPATH=/app ensures local code is used instead of installed package
cd "$PROJECT_ROOT/alembic"

case "$COMMAND" in
    upgrade)
        TARGET="${2:-head}"
        echo "Running Alembic upgrade to: $TARGET"
        echo "Environment variables loaded from .env"
        env $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs) PYTHONPATH=/app alembic upgrade "$TARGET"
        echo "Upgrade completed successfully!"
        ;;

    downgrade)
        TARGET="${2:--1}"
        echo "Running Alembic downgrade to: $TARGET"
        echo "Environment variables loaded from .env"
        env $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs) PYTHONPATH=/app alembic downgrade "$TARGET"
        echo "Downgrade completed successfully!"
        ;;

    *)
        # Default: create new migration
        MESSAGE="$1"
        echo "Creating Alembic migration: $MESSAGE"
        echo "Environment variables loaded from .env"
        env $(cat "$PROJECT_ROOT/.env" | grep -v '^#' | xargs) PYTHONPATH=/app alembic revision --autogenerate -m "$MESSAGE"
        echo "Migration created successfully!"
        ;;
esac

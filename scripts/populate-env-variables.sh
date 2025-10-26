#!/bin/bash

# Script to create .env from template and populate environment variables

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_TEMPLATE="$PROJECT_ROOT/.env.template"
ENV_FILE="$PROJECT_ROOT/.env"

# Check if .env exists
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating .env file from template..."

    if [ ! -f "$ENV_TEMPLATE" ]; then
        echo "Error: .env.template not found at $ENV_TEMPLATE"
        exit 1
    fi

    cp "$ENV_TEMPLATE" "$ENV_FILE"

    echo ""
    echo "✅ .env file created at $ENV_FILE"
    echo ""
    echo "⚠️  Please edit the .env file and fill in your values, then run this script again."
    echo ""
    exit 0
fi

# .env exists, populate variables
echo "Loading environment variables from .env..."

while IFS= read -r line; do
    # Skip empty lines and comments
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue

    # Export for current session
    export "$line"

    # Add to .bashrc if not already there
    var_name=$(echo "$line" | cut -d'=' -f1)
    grep -q "^export $var_name=" ~/.bashrc || echo "export $line" >> ~/.bashrc
done < "$ENV_FILE"

echo "✅ Environment variables populated"
echo "✅ Variables saved to ~/.bashrc"
echo ""
echo "Run 'source ~/.bashrc' in other terminals to load them"

#!/bin/bash
# Start the development environment with VS Code Server
#
# Usage:
#   ./scripts/dev-start.sh

set -e

echo "Starting GnuCash Plaintext development environment..."
echo ""

# Install git hooks if not already installed
if [ ! -f .git/hooks/pre-commit ]; then
    echo "Installing git hooks..."
    ./scripts/install-hooks.sh
    echo ""
fi

# Check if base image exists
if ! docker image inspect gnucash-dev:latest &> /dev/null; then
    echo "Base image gnucash-dev:latest not found. Building..."
    ./scripts/build.sh
    echo ""
fi

# Check if dev image exists, if not, docker compose will build it
if ! docker image inspect gnucash-dev-vscode:latest &> /dev/null; then
    echo "Dev image not found. Docker compose will build it (this may take a few minutes)..."
    echo ""
fi

echo "Starting docker compose..."
docker compose up --build

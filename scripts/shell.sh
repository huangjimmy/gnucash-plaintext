#!/bin/bash
# Start interactive shell in GnuCash development container
#
# Usage:
#   ./scripts/shell.sh         # Use latest image
#   ./scripts/shell.sh debian12 # Use specific tag

set -e

TAG="${1:-latest}"
IMAGE_NAME="gnucash-dev:$TAG"

# Detect if running inside a container (Docker-in-Docker scenario)
if [ -n "$HOST_PROJECT_PATH" ]; then
    PROJECT_PATH="$HOST_PROJECT_PATH"
else
    PROJECT_PATH="$(pwd)"
fi

# Check if image exists
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    echo "Image $IMAGE_NAME not found. Building..."
    case "$TAG" in
        latest)
            ./scripts/build.sh debian:13
            ;;
        debian12)
            ./scripts/build.sh debian:12
            ;;
        debian11)
            ./scripts/build.sh debian:11
            ;;
        ubuntu20)
            ./scripts/build.sh ubuntu:20.04
            ;;
        *)
            echo "Unknown tag: $TAG"
            exit 1
            ;;
    esac
fi

echo "Starting interactive shell in $IMAGE_NAME..."
docker run -it --rm -v "$PROJECT_PATH:/workspace" "$IMAGE_NAME" bash

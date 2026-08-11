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
#
# `build.sh` takes the tag as well as the base image, so the table mapping one
# to the other lives there alone. Copied here it knew seven of the ten builds,
# and `./scripts/shell.sh opensuse` on a machine without that image answered
# `Unknown tag: opensuse` rather than building it.
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    echo "Image $IMAGE_NAME not found. Building..."
    "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/build.sh" "$TAG"
fi

echo "Starting interactive shell in $IMAGE_NAME..."
docker run -it --rm -v "$PROJECT_PATH:/workspace" "$IMAGE_NAME" bash

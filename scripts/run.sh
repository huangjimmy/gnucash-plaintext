#!/bin/bash
# Run arbitrary command in GnuCash development container
#
# Usage:
#   ./scripts/run.sh python3 --version
#   ./scripts/run.sh debian12 python3 script.py
#   ./scripts/run.sh latest gnucash-plaintext --help

set -e

# Detect if running inside a container (Docker-in-Docker scenario)
if [ -n "$HOST_PROJECT_PATH" ]; then
    PROJECT_PATH="$HOST_PROJECT_PATH"
else
    PROJECT_PATH="$(pwd)"
fi

# Check if first arg looks like a tag (no slashes or spaces)
if [[ "$1" =~ ^[a-z0-9]+$ ]]; then
    TAG="$1"
    shift
else
    TAG="latest"
fi

IMAGE_NAME="gnucash-dev:$TAG"

# Check if image exists
#
# By tag, which `build.sh` accepts alongside the base image — see
# `scripts/shell.sh` for what the copy of that table here cost. This one is
# reached by `test-deployment.sh`, so a tag it did not know meant a deployment
# check that could not run on three of the ten builds.
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    echo "Image $IMAGE_NAME not found. Building..."
    "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/build.sh" "$TAG"
fi

docker run --rm -v "$PROJECT_PATH:/workspace" "$IMAGE_NAME" "$@"

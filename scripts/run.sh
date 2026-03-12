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

docker run --rm -v "$PROJECT_PATH:/workspace" "$IMAGE_NAME" "$@"

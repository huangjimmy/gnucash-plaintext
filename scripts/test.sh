#!/bin/bash
# Run tests in GnuCash development container
#
# Usage:
#   ./scripts/test.sh              # Run all tests with latest image
#   ./scripts/test.sh debian12     # Run with specific tag
#   ./scripts/test.sh latest tests/unit  # Run specific tests

set -e

TAG="${1:-latest}"
IMAGE_NAME="gnucash-dev:$TAG"

# Detect if running inside a container (Docker-in-Docker scenario)
# If HOST_PROJECT_PATH is set, use it; otherwise use current directory
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
        ubuntu22)
            ./scripts/build.sh ubuntu:22.04
            ;;
        ubuntu24)
            ./scripts/build.sh ubuntu:24.04
            ;;
        *)
            echo "Unknown tag: $TAG"
            exit 1
            ;;
    esac
fi

# Shift to get remaining arguments (test paths)
shift || true
TEST_PATH="${@:-tests/}"

echo "Running tests in $IMAGE_NAME..."
docker run --rm -v "$PROJECT_PATH:/workspace" "$IMAGE_NAME" /workspace/scripts/test-in-docker.sh $TEST_PATH

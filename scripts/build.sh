#!/bin/bash
# Build Docker image for GnuCash development
#
# Usage:
#   ./scripts/build.sh              # Build default (debian:13)
#   ./scripts/build.sh debian:12    # Build specific distribution
#   ./scripts/build.sh ubuntu:20.04 # Build Ubuntu 20.04

set -e

BASE_IMAGE="${1:-debian:13}"
IMAGE_NAME="gnucash-dev"

# Map base image to tag name
case "$BASE_IMAGE" in
    debian:13)
        TAG="latest"
        GNUCASH_VERSION="5.10"
        ;;
    debian:12)
        TAG="debian12"
        GNUCASH_VERSION="4.13"
        ;;
    debian:11)
        TAG="debian11"
        GNUCASH_VERSION="4.4"
        ;;
    ubuntu:20.04)
        TAG="ubuntu20"
        GNUCASH_VERSION="3.8"
        ;;
    *)
        echo "Unknown distribution: $BASE_IMAGE"
        echo "Supported: debian:13, debian:12, debian:11, ubuntu:20.04"
        exit 1
        ;;
esac

echo "Building $IMAGE_NAME:$TAG (GnuCash $GNUCASH_VERSION)..."
docker build --build-arg BASE_IMAGE="$BASE_IMAGE" -t "$IMAGE_NAME:$TAG" .

echo ""
echo "✅ Build complete: $IMAGE_NAME:$TAG"
echo ""
echo "Run interactive shell:"
echo "  ./scripts/shell.sh $TAG"

#!/bin/bash
# Build Docker image for GnuCash development
#
# Usage:
#   ./scripts/build.sh              # Build default (debian:13)
#   ./scripts/build.sh debian:12    # Build specific distribution
#   ./scripts/build.sh ubuntu:24.04 # Build Ubuntu 24.04
#   ./scripts/build.sh fedora:41    # Build Fedora 41
#   ./scripts/build.sh arch         # Build Arch Linux (rolling)
#   ./scripts/build.sh opensuse     # Build openSUSE Tumbleweed

set -e

BASE_IMAGE="${1:-debian:13}"
IMAGE_NAME="gnucash-dev"
DOCKERFILE="Dockerfile"
BUILD_ARGS=("--build-arg" "BASE_IMAGE=$BASE_IMAGE")

# Map base image to tag name and Dockerfile
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
    ubuntu:22.04)
        TAG="ubuntu22"
        GNUCASH_VERSION="4.8"
        ;;
    ubuntu:24.04)
        TAG="ubuntu24"
        GNUCASH_VERSION="4.9"
        ;;
    fedora:41)
        TAG="fedora41"
        GNUCASH_VERSION="5.13"
        DOCKERFILE="Dockerfile.fedora"
        BUILD_ARGS=()
        ;;
    arch)
        TAG="arch"
        GNUCASH_VERSION="5.14+"
        DOCKERFILE="Dockerfile.arch"
        BUILD_ARGS=()
        ;;
    opensuse)
        TAG="opensuse"
        GNUCASH_VERSION="5.13"
        DOCKERFILE="Dockerfile.opensuse"
        BUILD_ARGS=()
        ;;
    *)
        echo "Unknown distribution: $BASE_IMAGE"
        echo "Supported: debian:13, debian:12, debian:11, ubuntu:20.04, ubuntu:22.04, ubuntu:24.04,"
        echo "           fedora:41, arch, opensuse"
        exit 1
        ;;
esac

echo "Building $IMAGE_NAME:$TAG (GnuCash $GNUCASH_VERSION) from $DOCKERFILE..."
docker build "${BUILD_ARGS[@]}" -f "$DOCKERFILE" -t "$IMAGE_NAME:$TAG" .

echo ""
echo "✅ Build complete: $IMAGE_NAME:$TAG"
echo ""
echo "Run interactive shell:"
echo "  ./scripts/shell.sh $TAG"

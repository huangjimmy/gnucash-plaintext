#!/bin/bash
# Build Docker image for GnuCash development
#
# Usage:
#   ./scripts/build.sh              # Build default (debian:13)
#   ./scripts/build.sh debian:12    # Build specific distribution
#   ./scripts/build.sh ubuntu:26.04 # Build Ubuntu 26.04
#   ./scripts/build.sh ubuntu:24.04 # Build Ubuntu 24.04
#   ./scripts/build.sh fedora:41    # Build Fedora 41
#   ./scripts/build.sh arch         # Build Arch Linux (rolling)
#   ./scripts/build.sh opensuse     # Build openSUSE Tumbleweed
#
# A tag names the same build as its base image — `./scripts/build.sh ubuntu24`
# is `./scripts/build.sh ubuntu:24.04` — so the scripts that hold a tag and
# find its image missing can ask for it by the name they already have.

set -e

# The Dockerfile and the build context are the project root, whatever the
# caller's working directory is: `test.sh` calls this by path when an image is
# missing, and that path may be reached from anywhere.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

WANTED="${1:-debian:13}"
IMAGE_NAME="gnucash-dev"
DOCKERFILE="Dockerfile"

# Map what was asked for — a base image or a tag — to the build.
#
# Both spellings, because the alternative is what was here: `test.sh`,
# `shell.sh` and `run.sh` each carried a copy of this table to turn the tag
# they hold into a base image, and the copies went out of step. Two of them
# still did not know fedora, arch or openSUSE at all, so `./scripts/run.sh
# opensuse` on a machine without that image said `Unknown tag: opensuse`
# instead of building it.
#

# The versions are what each image's own package database reports, read on
# 2026-08-11 — `dpkg-query -W gnucash`, `rpm -q gnucash`, `pacman -Q gnucash`.
# They are printed on every build and are the label a reader goes by, and three
# of them were a release or more out: ubuntu24 said 4.9 and carries 5.5, arch
# said 5.14+ and carries 5.15, opensuse said 5.13 and carries 5.16. CLAUDE.md
# records what the first one cost — it put the only 4.x/5.x behavioural
# boundary this suite has measured on the wrong side of two builds. Re-probe
# rather than guess when a base image moves.
case "$WANTED" in
    debian:13|latest)
        BASE_IMAGE="debian:13"
        TAG="latest"
        GNUCASH_VERSION="5.10"
        ;;
    debian:12|debian12)
        BASE_IMAGE="debian:12"
        TAG="debian12"
        GNUCASH_VERSION="4.13"
        ;;
    debian:10|debian10)
        BASE_IMAGE="debian:10"
        TAG="debian10"
        GNUCASH_VERSION="3.4"
        ;;
    debian:11|debian11)
        BASE_IMAGE="debian:11"
        TAG="debian11"
        GNUCASH_VERSION="4.4"
        ;;
    ubuntu:20.04|ubuntu20)
        BASE_IMAGE="ubuntu:20.04"
        TAG="ubuntu20"
        GNUCASH_VERSION="3.8"
        ;;
    ubuntu:22.04|ubuntu22)
        BASE_IMAGE="ubuntu:22.04"
        TAG="ubuntu22"
        GNUCASH_VERSION="4.8"
        ;;
    ubuntu:24.04|ubuntu24)
        BASE_IMAGE="ubuntu:24.04"
        TAG="ubuntu24"
        GNUCASH_VERSION="5.5"
        ;;
    ubuntu:26.04|ubuntu26)
        BASE_IMAGE="ubuntu:26.04"
        TAG="ubuntu26"
        GNUCASH_VERSION="5.14"
        ;;
    fedora:41|fedora41)
        BASE_IMAGE="fedora:41"
        TAG="fedora41"
        GNUCASH_VERSION="5.13"
        DOCKERFILE="Dockerfile.fedora"
        ;;
    arch)
        BASE_IMAGE="arch"
        TAG="arch"
        GNUCASH_VERSION="5.15"
        DOCKERFILE="Dockerfile.arch"
        ;;
    opensuse)
        BASE_IMAGE="opensuse"
        TAG="opensuse"
        GNUCASH_VERSION="5.16"
        DOCKERFILE="Dockerfile.opensuse"
        ;;
    *)
        echo "Unknown distribution or tag: $WANTED"
        echo "Supported: debian:13, debian:12, debian:11, debian:10, ubuntu:20.04, ubuntu:22.04,"
        echo "           ubuntu:24.04, ubuntu:26.04, fedora:41, arch, opensuse"
        echo "           (or their tags: latest, debian12, debian11, debian10, ubuntu20,"
        echo "            ubuntu22, ubuntu24, ubuntu26, fedora41, arch, opensuse)"
        exit 1
        ;;
esac

# The three that build from their own Dockerfile take no base-image argument;
# the seven that share `Dockerfile` are told which one to start from.
BUILD_ARGS=()
if [ "$DOCKERFILE" = "Dockerfile" ]; then
    BUILD_ARGS=("--build-arg" "BASE_IMAGE=$BASE_IMAGE")
fi

echo "Building $IMAGE_NAME:$TAG (GnuCash $GNUCASH_VERSION) from $DOCKERFILE..."
docker build "${BUILD_ARGS[@]}" -f "$DOCKERFILE" -t "$IMAGE_NAME:$TAG" .

echo ""
echo "✅ Build complete: $IMAGE_NAME:$TAG"
echo ""
echo "Run interactive shell:"
echo "  ./scripts/shell.sh $TAG"

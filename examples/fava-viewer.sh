#!/bin/bash
# Export a GnuCash file to beancount format and launch the Fava web UI.
#
# Fava (https://beancount.github.io/fava/) is a modern web interface for
# beancount files. This script exports your GnuCash data using the project's
# Docker image, then starts Fava in a lightweight Python container.
#
# Usage:
#   ./examples/fava-viewer.sh <gnucash-file> [options]
#
# Options:
#   --port PORT              Fava listen port (default: 5000)
#   --date-from YYYY-MM-DD   Export transactions from this date
#   --date-to   YYYY-MM-DD   Export transactions up to this date
#   --account   ACCOUNT      Filter by account path (e.g. "Assets:Bank")
#   --tag TAG                Docker image tag to use (default: latest)
#
# Examples:
#   ./examples/fava-viewer.sh ~/finances/my.gnucash
#   ./examples/fava-viewer.sh ~/finances/my.gnucash --port 5001
#   ./examples/fava-viewer.sh ~/finances/my.gnucash --date-from 2024-01-01 --date-to 2024-12-31
#   ./examples/fava-viewer.sh ~/finances/my.gnucash --account "Assets"

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Defaults ---
PORT=5000
DOCKER_TAG="latest"
EXPORT_ARGS=()

usage() {
    grep '^#' "$0" | grep -v '#!/' | sed 's/^# \?//'
    exit 1
}

if [ $# -eq 0 ]; then
    usage
fi

GNUCASH_FILE="$1"
shift

while [[ $# -gt 0 ]]; do
    case "$1" in
        --port)
            PORT="$2"
            if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
                echo "Error: --port must be a number"; exit 1
            fi
            shift 2 ;;
        --tag)
            DOCKER_TAG="$2"; shift 2 ;;
        --date-from|--date-to|--account)
            EXPORT_ARGS+=("$1" "$2"); shift 2 ;;
        -h|--help)
            usage ;;
        *)
            echo "Unknown option: $1"
            usage ;;
    esac
done

# --- Resolve paths ---
GNUCASH_FILE="$(realpath "$GNUCASH_FILE")"
if [ ! -f "$GNUCASH_FILE" ]; then
    echo "Error: GnuCash file not found: $GNUCASH_FILE"
    exit 1
fi

GNUCASH_DIR="$(dirname "$GNUCASH_FILE")"
GNUCASH_BASENAME="$(basename "$GNUCASH_FILE" .gnucash)"
BEANCOUNT_FILE="$GNUCASH_DIR/${GNUCASH_BASENAME}.beancount"

IMAGE_NAME="gnucash-dev:$DOCKER_TAG"

echo "=== GnuCash → Fava Viewer ==="
echo "  Input:  $GNUCASH_FILE"
echo "  Output: $BEANCOUNT_FILE"
echo "  Port:   http://localhost:$PORT"
echo ""

# --- Step 1: Build image if missing ---
if ! docker image inspect "$IMAGE_NAME" &>/dev/null; then
    if [ "$DOCKER_TAG" != "latest" ]; then
        echo "Error: image $IMAGE_NAME not found. Build it first with scripts/build.sh --tag $DOCKER_TAG"
        exit 1
    fi
    echo "Docker image $IMAGE_NAME not found. Building..."
    "$PROJECT_DIR/scripts/build.sh"
    echo ""
fi

# --- Step 2: Export GnuCash → beancount ---
echo "Step 1/2: Exporting to beancount..."
docker run --rm \
    -v "$GNUCASH_DIR:/gnucash-data" \
    "$IMAGE_NAME" \
    gnucash-plaintext export-beancount \
        "/gnucash-data/$(basename "$GNUCASH_FILE")" \
        "/gnucash-data/${GNUCASH_BASENAME}.beancount" \
        "${EXPORT_ARGS[@]}"

echo ""
echo "Step 2/2: Launching Fava..."
echo "  Open your browser at: http://localhost:$PORT"
echo "  Press Ctrl+C to stop."
echo ""

# --- Step 3: Run fava in a Python container ---
# Uses python:3.12-slim so we don't need to modify the GnuCash image.
# The beancount file is mounted read-only; Fava only needs to read it.
docker rm -f gnucash-fava 2>/dev/null || true
docker run --rm \
    -v "$GNUCASH_DIR:/data:ro" \
    -p "${PORT}:5000" \
    --name gnucash-fava \
    -e BEANCOUNT_FILE="${GNUCASH_BASENAME}.beancount" \
    python:3.12-slim \
    sh -c 'pip install fava --quiet --disable-pip-version-check && fava --host 0.0.0.0 "/data/$BEANCOUNT_FILE"'

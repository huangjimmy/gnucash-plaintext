#!/bin/bash
#
# Auto-fix linting errors
#
# Usage:
#   ./scripts/fix-lint.sh          # Safe fixes only
#   ./scripts/fix-lint.sh --unsafe # Include unsafe fixes (recommended)
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

UNSAFE_FLAG=""
if [ "$1" = "--unsafe" ]; then
    UNSAFE_FLAG="--unsafe-fixes"
    echo "Running linting auto-fix (including unsafe fixes)..."
else
    echo "Running linting auto-fix (safe fixes only)..."
    echo "Tip: Use --unsafe flag to fix all issues"
fi

# Run as the invoking host user (not root) so the *.egg-info written into the
# mounted workspace stays owned by you. The uid has no /etc/passwd entry, so
# point HOME at a writable /tmp dir and install ruff per-user.
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    -v "$(pwd):/workspace" \
    gnucash-dev:latest sh -c \
    "mkdir -p /tmp/home/.local && cd /workspace && python3 -m pip install -e '.[dev]' -q --break-system-packages --user && PATH=/tmp/home/.local/bin:\$PATH ruff check --fix $UNSAFE_FLAG ."

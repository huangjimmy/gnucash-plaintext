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

docker run --rm -v "$(pwd):/workspace" gnucash-dev:latest sh -c \
    "cd /workspace && python3 -m pip install -e '.[dev]' -q --break-system-packages && ruff check --fix $UNSAFE_FLAG ."

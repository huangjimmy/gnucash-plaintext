#!/bin/bash
#
# Run linting checks
#
# Usage:
#   ./scripts/lint.sh              # Check all files
#   ./scripts/lint.sh file1.py file2.py  # Check specific files
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Use provided files or default to all files (.)
FILES="${*:-.}"

echo "Running linting checks..."
docker run --rm -v "$(pwd):/workspace" gnucash-dev:latest sh -c \
    "cd /workspace && python3 -m pip install -e '.[dev]' -q --break-system-packages && ruff check ${FILES}"

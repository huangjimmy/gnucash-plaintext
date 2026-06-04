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
# Run as the invoking host user (not root) so the *.egg-info written into the
# mounted workspace stays owned by you. The uid has no /etc/passwd entry, so
# point HOME at a writable /tmp dir and install ruff per-user.
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    -v "$(pwd):/workspace" \
    gnucash-dev:latest sh -c \
    "mkdir -p /tmp/home/.local && cd /workspace && python3 -m pip install -e '.[dev]' -q --break-system-packages --user && PATH=/tmp/home/.local/bin:\$PATH ruff check ${FILES}"

#!/bin/bash
# Run tests in Docker with GnuCash Python bindings
#
# Usage:
#   ./scripts/test-in-docker.sh                    # Run all tests
#   ./scripts/test-in-docker.sh tests/unit/        # Run specific directory
#   ./scripts/test-in-docker.sh tests/unit/services/test_transaction_matcher.py  # Run specific file

set -e

# Default to running all tests
TEST_PATH="${1:-tests/}"

# This script may run as a non-root user (scripts/test.sh passes --user so the
# files written into the mounted workspace stay owned by the host user). A
# non-root uid cannot write to the system site-packages, so install per-user
# under a writable HOME and put its bin dir on PATH for pytest.
export HOME="${HOME:-/tmp/home}"
mkdir -p "$HOME/.local"

echo "Installing package..."
python3 -m pip install -e . weasyprint pytest-xdist --break-system-packages --user -q

echo ""
echo "Running tests: $TEST_PATH"
echo "================================"
PATH="$HOME/.local/bin:$PATH" python3 -m pytest "$TEST_PATH" -n auto -v --tb=short

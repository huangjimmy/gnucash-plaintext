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

echo "Installing package..."
python3 -m pip install -e . --break-system-packages -q

echo ""
echo "Running tests: $TEST_PATH"
echo "================================"
python3 -m pytest "$TEST_PATH" -v --tb=short

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
python3 -m pip install -e . weasyprint --break-system-packages --user -q

# Coverage is measured only when asked for, because the figure that means
# anything is the union of every supported distribution's run (scripts/
# coverage.sh) and a single run's number would read as a shortfall. Nothing is
# reported or gated here: the data file is written for the sweep to add up.
COV_ARGS=()
if [ -n "$GNC_COVERAGE" ]; then
    COV_ARGS=(--cov --cov-report= --cov-fail-under=0)
fi

echo ""
echo "Running tests: $TEST_PATH"
echo "================================"
PATH="$HOME/.local/bin:$PATH" python3 -m pytest "$TEST_PATH" -v --tb=short "${COV_ARGS[@]}"

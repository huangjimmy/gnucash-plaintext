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

# And said out loud when it is root, because what root costs here is silence.
# A process running as root writes whatever the mode says, so the tests that
# need a directory they cannot write to cannot be run — they check for the
# state and skip when it is not there, which is the honest answer but also a
# green suite with a behaviour untested and its lines out of the union
# scripts/coverage.sh gates. Dropping `--user` from a container is how that
# happens, and it happened: CI ran as root on every version while the gate ran
# as the invoking user, and the difference showed up as a CI failure rather
# than as anything the suite said. Not an error — `scripts/shell.sh` runs
# without `--user` on purpose, and `pytest tests/` in there is a documented
# way to work — so this says so and carries on.
if [ "$(id -u)" = 0 ]; then
    echo "⚠  running as root: tests needing an unwritable directory will skip"
    echo "   (root ignores the mode). scripts/test.sh passes --user; a bare"
    echo "   'docker run' does not."
fi

# `pypdf` is test-only: a printed document is a PDF, and the only honest way to
# check that its text can be selected and copied is to read the text back out
# of it. Installed here beside weasyprint rather than added to ten Dockerfiles.
echo "Installing package..."
python3 -m pip install -e . weasyprint pypdf --break-system-packages --user -q

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

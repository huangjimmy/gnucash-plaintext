#!/bin/bash
# Run tests in GnuCash development container
#
# Usage:
#   ./scripts/test.sh              # Run all tests with latest image
#   ./scripts/test.sh debian12     # Run with specific tag
#   ./scripts/test.sh latest tests/unit  # Run specific tests

set -e

TAG="${1:-latest}"
IMAGE_NAME="gnucash-dev:$TAG"

# Where this script lives, so the build fallback below finds its sibling
# whatever the caller's working directory is. Called as `./scripts/build.sh` it
# needed the caller to be standing in the project root — true of a person
# typing it and of the parallel sweep, which `cd`s there, but only by habit.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect if running inside a container (Docker-in-Docker scenario)
# If HOST_PROJECT_PATH is set, use it; otherwise use current directory
if [ -n "$HOST_PROJECT_PATH" ]; then
    PROJECT_PATH="$HOST_PROJECT_PATH"
else
    PROJECT_PATH="$(pwd)"
fi

# Check if image exists
#
# By tag: `build.sh` takes either spelling, so the table turning one into the
# other is in one place rather than copied into each of the three scripts that
# build on demand.
if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    echo "Image $IMAGE_NAME not found. Building..."
    "$SCRIPT_DIR/build.sh" "$TAG"
fi

# Shift to get remaining arguments (test paths)
shift || true
TEST_PATH="${@:-tests/}"

echo "Running tests in $IMAGE_NAME..."
# Run as the invoking host user (not root) so the __pycache__, .pytest_cache,
# *.egg-info and editable-install artifacts written into the mounted workspace
# stay owned by you and are removable without a privileged container. The uid
# has no /etc/passwd entry, so point HOME at a writable /tmp dir for the
# per-user pip install (see scripts/test-in-docker.sh).
# GNC_WRITE_EXPORTS is forwarded so the research harnesses can refresh the
# committed snapshots in exports/ on request. Without it they write to a
# scratch directory, leaving the worktree clean — every run stamps a fresh date
# and fresh GUIDs, so writing on each one would keep those files permanently
# modified.
# GNC_COVERAGE, and the directory the data lands in, are forwarded for
# scripts/coverage.sh, which adds up one run per supported distribution.
#
# GNC_UNPRIVILEGED_RUN says this run cannot write past the mode, so a test
# needing a directory it cannot write to may insist on it rather than skip.
# Root writes whatever the mode says, so such a test can only check for the
# state and skip when it is not there — which is honest and also silent, and
# dropping `--user` is exactly the regression this flag exists to keep loud: it
# happened, CI ran as root on every version, and it showed up as a CI failure
# rather than as anything the suite said. `scripts/shell.sh` runs root on
# purpose and sets nothing, so working in there still skips.
#
# Not "`--user` was passed", which is the thing that is easy to write here and
# is not the same claim: `--user` carries whatever uid is invoking, and under
# `sudo ./scripts/test.sh` — the ordinary way to reach Docker without being in
# the `docker` group — that is `0:0`. The container is then root, the flag
# would say otherwise, and every version of the sweep would fail on a
# regression nobody caused, telling its reader to go and look for a `--user`
# that was never dropped.
COV_MOUNT=()
if [ -n "$GNC_COVERAGE" ]; then
    mkdir -p "${GNC_COVERAGE_DIR:=$PROJECT_PATH/.coverage-data}"
    COV_MOUNT=(-v "$GNC_COVERAGE_DIR:/cov" -e "COVERAGE_FILE=/cov/.coverage.$TAG")
fi

UNPRIVILEGED=()
if [ "$(id -u)" != 0 ]; then
    UNPRIVILEGED=(-e GNC_UNPRIVILEGED_RUN=1)
fi

docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    "${UNPRIVILEGED[@]}" \
    -e GNC_WRITE_EXPORTS="${GNC_WRITE_EXPORTS:-}" \
    -e GNC_COVERAGE="${GNC_COVERAGE:-}" \
    "${COV_MOUNT[@]}" \
    -v "$PROJECT_PATH:/workspace" \
    "$IMAGE_NAME" /workspace/scripts/test-in-docker.sh $TEST_PATH

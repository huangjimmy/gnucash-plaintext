#!/bin/bash
#
# Test against all supported OS/Python versions IN PARALLEL
#
# Strategy: Copy workspace to temp directories, mount each to separate container
# This avoids mount conflicts and enables parallel execution
#
# Usage:
#   ./scripts/test-all-versions-parallel.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Supported versions
VERSIONS=("latest" "debian12" "debian11" "ubuntu26" "ubuntu24" "ubuntu22" "ubuntu20" "fedora41" "arch" "opensuse")

echo "Testing against all supported versions IN PARALLEL..."
echo "This is ~4x faster than sequential testing"
echo ""

# Create temp directory for workspace copies
TEMP_BASE=$(mktemp -d -t gnucash-test-XXXXXX)
echo "Temp workspace: $TEMP_BASE"

# With GNC_COVERAGE set, every container writes its coverage data into one
# shared directory, under a name of its own, so ten of them can write side by
# side and `coverage combine` adds them up afterwards. The union is the only
# figure worth gating on: version-specific paths run on the distributions that
# have those versions and nowhere else.
if [ -n "$GNC_COVERAGE" ]; then
    : "${GNC_COVERAGE_DIR:=$TEMP_BASE/cov}"
    mkdir -p "$GNC_COVERAGE_DIR"
    echo "Coverage data: $GNC_COVERAGE_DIR"
fi
echo ""

# Cleanup function
# Docker containers run as root, so some files in TEMP_BASE may be root-owned.
# Use a privileged container to remove them, falling back to plain rm.
cleanup() {
    echo ""
    echo "Cleaning up temp directories..."
    # docker run --rm -v "$TEMP_BASE:/cleanup" alpine sh -c "rm -rf /cleanup/*" 2>/dev/null || true
    # rm -rf "$TEMP_BASE" 2>/dev/null || true
}
trap cleanup EXIT

# Copy workspace for each version
echo "Preparing workspaces..."
for version in "${VERSIONS[@]}"; do
    WORKSPACE="$TEMP_BASE/$version"
    echo "  Copying to $WORKSPACE..."

    # Copy entire workspace, excluding large/unnecessary files
    rsync -a --exclude='.git' \
             --exclude='__pycache__' \
             --exclude='*.pyc' \
             --exclude='.pytest_cache' \
             --exclude='.ruff_cache' \
             --exclude='htmlcov' \
             --exclude='.coverage' \
             --exclude='*.egg-info' \
             --exclude='test_outputs' \
             --exclude='.claude' \
             "$PROJECT_ROOT/" "$WORKSPACE/"
done
echo ""

# Build images if needed (sequential - Docker build has internal locking)
#
# By tag, which `build.sh` takes. A local table turning the tag into a base
# image lived here too, with no arm for an unknown one — so a typo in VERSIONS
# above produced an empty argument, `build.sh` read that as "no argument
# given", and the sweep quietly rebuilt debian:13 over `gnucash-dev:latest`
# before failing later on the tag that does not exist.
echo "Building Docker images..."
for version in "${VERSIONS[@]}"; do
    if ! docker image inspect gnucash-dev:$version > /dev/null 2>&1; then
        echo "  Building gnucash-dev:$version..."
        "$PROJECT_ROOT/scripts/build.sh" "$version"
    fi
done
echo ""

# Function to run tests for one version
run_test() {
    local version=$1
    local workspace="$TEMP_BASE/$version"
    local log_file="$TEMP_BASE/$version.log"

    echo "[$version] Starting tests..." > "$log_file"

    # Through `scripts/test.sh`, which is the one place that decides how the
    # suite is run — the user, the mount, HOME, the coverage file. Spelled out
    # here it was a third copy of that recipe beside `test-in-docker.sh` and
    # CI's own, agreeing only by hand: CI's copy had no `--user` and so ran as
    # root, where a test that takes write permission off a directory cannot
    # fail, and the gate reported green on every version while CI reported red
    # on every version.
    #
    # `HOST_PROJECT_PATH` is what `test.sh` mounts, which is how the per-version
    # copy of the workspace this function makes reaches the container.
    if HOST_PROJECT_PATH="$workspace" GNC_COVERAGE="$GNC_COVERAGE" \
        GNC_COVERAGE_DIR="$GNC_COVERAGE_DIR" \
        "$PROJECT_ROOT/scripts/test.sh" "$version" \
        >> "$log_file" 2>&1; then
        echo "[$version] ✓ PASSED" >> "$log_file"
        return 0
    else
        echo "[$version] ✗ FAILED" >> "$log_file"
        return 1
    fi
}

# Export function for parallel execution
export -f run_test
export TEMP_BASE GNC_COVERAGE GNC_COVERAGE_DIR PROJECT_ROOT

# Run tests in parallel using background jobs
echo "Running tests in parallel..."
FAILED_VERSIONS=()
PASSED_VERSIONS=()
PIDS=()
for version in "${VERSIONS[@]}"; do
    echo "  Starting $version..."
    run_test "$version" &
    PIDS+=($!)
done
echo ""
echo "All test jobs started. Waiting for completion..."
echo ""

# Wait for all background jobs and collect exit codes
for i in "${!VERSIONS[@]}"; do
    version="${VERSIONS[$i]}"
    pid="${PIDS[$i]}"

    if wait "$pid"; then
        PASSED_VERSIONS+=("$version")
        echo "✓ $version completed successfully"
    else
        FAILED_VERSIONS+=("$version")
        echo "✗ $version failed"
    fi
done

echo ""
echo "========================================="
echo "Summary"
echo "========================================="
echo "Passed (${#PASSED_VERSIONS[@]}): ${PASSED_VERSIONS[*]}"
echo "Failed (${#FAILED_VERSIONS[@]}): ${FAILED_VERSIONS[*]}"
echo ""

# Show logs for failed versions
if [ ${#FAILED_VERSIONS[@]} -gt 0 ]; then
    echo "Failed version logs (last 50 lines):"
    echo "========================================="
    for version in "${FAILED_VERSIONS[@]}"; do
        LOG_PATH="$TEMP_BASE/$version.log"
        echo ""
        echo "--- $version ---"
        echo "Full log: $LOG_PATH"
        echo ""
        tail -50 "$LOG_PATH"
        echo ""
    done
    echo "========================================="
    echo "❌ Some tests failed"
    echo ""
    echo "To view full logs:"
    for version in "${FAILED_VERSIONS[@]}"; do
        echo "  cat $TEMP_BASE/$version.log"
    done
    echo ""
    echo "Note: Logs will be deleted when you exit this terminal or run cleanup"
    exit 1
else
    echo "✅ All versions passed!"
    exit 0
fi

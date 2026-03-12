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
VERSIONS=("latest" "debian12" "debian11" "ubuntu20")

echo "Testing against all supported versions IN PARALLEL..."
echo "This is ~4x faster than sequential testing"
echo ""

# Create temp directory for workspace copies
TEMP_BASE=$(mktemp -d -t gnucash-test-XXXXXX)
echo "Temp workspace: $TEMP_BASE"
echo ""

# Cleanup function
cleanup() {
    echo ""
    echo "Cleaning up temp directories..."
    rm -rf "$TEMP_BASE"
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
             --exclude='htmlcov' \
             --exclude='.coverage' \
             --exclude='*.egg-info' \
             --exclude='test_outputs' \
             --exclude='.claude' \
             "$PROJECT_ROOT/" "$WORKSPACE/"
done
echo ""

# Build images if needed (sequential - Docker build has internal locking)
echo "Building Docker images..."
for version in "${VERSIONS[@]}"; do
    if [ "$version" = "latest" ]; then
        if ! docker image inspect gnucash-dev:latest > /dev/null 2>&1; then
            echo "  Building gnucash-dev:latest..."
            docker build -t gnucash-dev:latest .
        fi
    else
        if ! docker image inspect gnucash-dev:$version > /dev/null 2>&1; then
            echo "  Building gnucash-dev:$version..."
            BASE_IMAGE=$(case "$version" in
                debian12) echo "debian:12" ;;
                debian11) echo "debian:11" ;;
                ubuntu20) echo "ubuntu:20.04" ;;
            esac)
            docker build --build-arg BASE_IMAGE=$BASE_IMAGE -t gnucash-dev:$version .
        fi
    fi
done
echo ""

# Function to run tests for one version
run_test() {
    local version=$1
    local workspace="$TEMP_BASE/$version"
    local log_file="$TEMP_BASE/$version.log"

    echo "[$version] Starting tests..." > "$log_file"

    if docker run --rm \
        -v "$workspace:/workspace" \
        gnucash-dev:$version \
        sh -c "cd /workspace && python3 -m pip install -e '.[dev]' -q --break-system-packages && pytest tests/ -v --tb=short" \
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
export TEMP_BASE

# Run tests in parallel using background jobs
echo "Running tests in parallel..."
PIDS=()
for version in "${VERSIONS[@]}"; do
    echo "  Starting $version..."
    run_test "$version" &
    PIDS+=($!)
done
echo ""
echo "All test jobs started. Waiting for completion..."
echo "(This may take 2-3 minutes depending on your machine)"
echo ""

# Wait for all background jobs and collect exit codes
FAILED_VERSIONS=()
PASSED_VERSIONS=()

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

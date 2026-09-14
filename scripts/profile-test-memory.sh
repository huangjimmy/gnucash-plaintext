#!/bin/bash
# Profile the test suite's memory, test by test, in a GnuCash container.
#
# Usage:
#   ./scripts/profile-test-memory.sh                  # all tests, latest image
#   ./scripts/profile-test-memory.sh debian10         # all tests on Debian 10
#   ./scripts/profile-test-memory.sh latest tests/integration/test_payment_roundtrip.py
#
# Runs the tests the way scripts/test.sh does, with
# tests/research/memory_per_test_plugin.py loaded, and prints:
#   - the pytest result line;
#   - resident memory at the start of the run, at the end, and at most;
#   - how many GnuCash sessions were created, ended and destroyed;
#   - the test files that added the most memory.
#
# The rows are kept in $GNC_PROFILE_DIR (default .memory-profile/), as
# <tag>.tsv — one row per test: test id, KiB before, KiB after, difference —
# beside <tag>.log, the pytest output.
#
# Why it exists: one pytest process runs the whole suite, so memory a test
# keeps is kept for the rest of the run. Sessions that were ended and never
# destroyed kept every book in memory, and the suite grew to 1.7 GB on every
# build before GnuCashRepository.close destroyed its session. See
# docs/issues/Q-041-a-price-cannot-be-recorded-for-a-past-date-or-kept-through-export-and-import.md.

set -e

TAG="${1:-latest}"
shift || true
TEST_PATH="${1:-tests/}"
IMAGE_NAME="gnucash-dev:$TAG"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The same host path scripts/test.sh mounts, for Docker-in-Docker.
PROJECT_PATH="${HOST_PROJECT_PATH:-$(pwd)}"

OUT_DIR="${GNC_PROFILE_DIR:-$PROJECT_PATH/.memory-profile}"
mkdir -p "$OUT_DIR"
TSV="$OUT_DIR/$TAG.tsv"
LOG="$OUT_DIR/$TAG.log"
rm -f "$TSV" "$LOG"

if ! docker image inspect "$IMAGE_NAME" &> /dev/null; then
    echo "Image $IMAGE_NAME not found. Building..."
    "$SCRIPT_DIR/build.sh" "$TAG"
fi

UNPRIVILEGED=()
if [ "$(id -u)" != 0 ]; then
    UNPRIVILEGED=(-e GNC_UNPRIVILEGED_RUN=1)
fi

echo "Profiling $TEST_PATH in $IMAGE_NAME..."
set +e
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    "${UNPRIVILEGED[@]}" \
    -e PYTEST_ADDOPTS="-p tests.research.memory_per_test_plugin" \
    -e MEMORY_PER_TEST_OUT="/profile/$TAG.tsv" \
    -v "$PROJECT_PATH:/workspace" \
    -v "$OUT_DIR:/profile" \
    "$IMAGE_NAME" /workspace/scripts/test-in-docker.sh "$TEST_PATH" > "$LOG" 2>&1
status=$?
set -e

grep -E "=+ .*(passed|failed|error).* in " "$LOG" || tail -5 "$LOG"
if [ -s "$TSV" ]; then
    awk -F'\t' '!/^#/ {
            if (first == "") first = $2
            last = $3
            if ($3 > peak) peak = $3
        }
        END {
            printf "Resident memory: %.0f MiB at the start, %.0f MiB at the end, %.0f MiB at most\n",
                first / 1024, last / 1024, peak / 1024
        }' "$TSV"
    grep "^# sessions" "$TSV" | sed 's/^# sessions/GnuCash sessions:/'
    echo "Test files that added the most memory:"
    awk -F'\t' '!/^#/ {
            split($1, part, "::")
            added[part[1]] += $4
            tests[part[1]]++
        }
        END {
            for (file in added)
                printf "%8.1f MiB  %4d tests  %s\n", added[file] / 1024, tests[file], file
        }' "$TSV" | sort -rn | head -n "${GNC_PROFILE_TOP:-15}"
fi
echo "Rows: $TSV"
echo "pytest output: $LOG"
exit $status

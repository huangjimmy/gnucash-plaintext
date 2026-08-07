#!/bin/bash
#
# Line and branch coverage, added up across every supported distribution.
#
# Usage:
#   ./scripts/coverage.sh                  # sweep every version, combine, gate
#   ./scripts/coverage.sh --threshold 100  # gate at the destination figure
#   ./scripts/coverage.sh --report-only    # combine and report what is on disk
#
# One distribution's number is not this project's number. The tree carries
# paths that only a particular GnuCash runs — a slot read on 3.8 and 4.4 and
# derived from 4.13, a SWIG call that works on Debian and needs ctypes on
# Ubuntu — so a line can be untestable on the machine in front of you and
# ordinary on the next. What is gated is the union: every supported version
# runs the suite, and a line no version reached is a line nothing tests.
#
# The destination is 100%: every line and branch reached by some supported
# version, with anything unreachable deleted rather than excused. The default
# below is the floor instead — what the union measures today — so the bare
# command is one that passes and refuses to let the figure slip. Raise it as
# the work in docs/issues/T-009 lands. A default of 100 today would fail on
# every run, and a gate that always fails is a gate somebody turns off.
#
# The data lands in .coverage-data/ (git-ignored) so a failing run can be read
# afterwards; `--report-only` re-reads it without running anything.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# The union as measured on 2026-08-05, across GnuCash 5.10, 4.13, 4.4, 3.8 and
# 5.15 — `latest`, `debian12`, `debian11`, `ubuntu20` and `arch`. The tag names
# and the versions are not interchangeable: `debian11` is 4.4, not 4.13.
THRESHOLD=89
REPORT_ONLY=""
HTML=""
while [ $# -gt 0 ]; do
    case "$1" in
        --threshold)
            # Checked here, or a missing value shifts past the end and reaches
            # coverage as `--fail-under=`, which fails with its own error about
            # a number rather than saying what is wrong with the command line.
            case "$2" in
                ''|*[!0-9]*)
                    echo "--threshold needs a whole number, got '${2}'" >&2
                    exit 1 ;;
            esac
            THRESHOLD="$2"; shift 2 ;;
        --report-only) REPORT_ONLY=1; shift ;;
        --html) HTML=1; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
done

export GNC_COVERAGE_DIR="$PROJECT_ROOT/.coverage-data"

if [ -z "$REPORT_ONLY" ]; then
    rm -rf "$GNC_COVERAGE_DIR"
    mkdir -p "$GNC_COVERAGE_DIR"
    echo "Running the suite on every supported version with coverage on..."
    echo ""
    # `|| SWEEP=$?` rather than a bare call: under `set -e` a version that fails
    # takes this script down on this line, so nothing says where the data went
    # or that a figure measured from a partial sweep is not the union it claims
    # to be. The versions that did finish have written theirs, and saying so is
    # more use than exiting silently.
    SWEEP=0
    GNC_COVERAGE=1 ./scripts/test-all-versions-parallel.sh || SWEEP=$?
    echo ""
    if [ $SWEEP -ne 0 ]; then
        # Recorded next to the data, because the data outlives this run and
        # `--report-only` has no other way to know what it is reading. Cleared
        # by the `rm -rf` above, so it can only survive a sweep that failed.
        echo "$SWEEP" > "$GNC_COVERAGE_DIR/.partial-sweep"
        echo "❌ The suite failed on at least one version (exit $SWEEP)."
        echo ""
        echo "Coverage is not reported from a partial sweep: a line no failing"
        echo "version reached would read as untested when it may be covered"
        echo "there. Fix the failure and re-run; what the finished versions"
        echo "measured is kept in $GNC_COVERAGE_DIR meanwhile, and reading it"
        echo "with --report-only says so rather than calling it the union."
        exit $SWEEP
    fi
fi

if ! ls "$GNC_COVERAGE_DIR"/.coverage* > /dev/null 2>&1; then
    echo "❌ No coverage data in $GNC_COVERAGE_DIR"
    echo "   Run ./scripts/coverage.sh (without --report-only) to measure it."
    exit 1
fi

# Data measured against source that has since changed reports a figure for a
# tree that no longer exists, and reads exactly like a current one — a stale
# run reported 81% where the same tree measured 89%, which cost an hour.
PARTIAL=""
if [ -n "$REPORT_ONLY" ]; then
    NEWEST_DATA=$(ls -t "$GNC_COVERAGE_DIR"/.coverage.* 2>/dev/null | head -1)
    NEWEST_DATA=${NEWEST_DATA:-$GNC_COVERAGE_DIR/.coverage}
    if [ -n "$(find cli services infrastructure use_cases repositories tests \
                    -name '*.py' -newer "$NEWEST_DATA" -print -quit 2>/dev/null)" ]; then
        echo "⚠  Source files are newer than this coverage data — it describes a"
        echo "   tree that has since changed. Re-measure with ./scripts/coverage.sh"
        echo ""
    fi
    # The sweep that wrote this data did not finish, so it is a floor and not
    # the union: the versions that failed reached lines nothing here records.
    # Without this the report reads exactly like a whole one, verdict included,
    # which is the reading the sweep had just refused to do.
    if [ -f "$GNC_COVERAGE_DIR/.partial-sweep" ]; then
        PARTIAL=1
        echo "⚠  This data is from a sweep that failed on at least one version"
        echo "   (exit $(cat "$GNC_COVERAGE_DIR/.partial-sweep")). It is a floor,"
        echo "   not the union — lines the missing versions cover read as missed."
        echo "   Fix the failure and re-run ./scripts/coverage.sh for the figure."
        echo ""
    fi
fi

echo "========================================="
echo "Combined coverage (line + branch)"
echo "========================================="

# Combined and reported inside the image, so the host needs no Python of its
# own and the version doing the reading is the version that did the measuring.
#
# Combining happens on a copy in the container's own /tmp, because it consumes
# what it reads — `--keep` does not spare explicitly-named files — and eating
# the per-version data would leave `--report-only` with nothing to re-read and
# a failing run with nothing to look at. The combined result is written back as
# `.coverage`, which is also what gets re-read when the per-version files are
# already gone.
# `|| STATUS=$?` rather than a bare call: under `set -e` a failing gate would
# take the script down before it could say which lines were missed.
STATUS=0
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    -e COVERAGE_FILE=/tmp/comb/.coverage \
    -v "$GNC_COVERAGE_DIR:/cov" \
    -v "$PROJECT_ROOT:/workspace" \
    gnucash-dev:latest \
    sh -c "mkdir -p /tmp/home/.local /tmp/comb && cd /workspace && \
           python3 -m pip install -e '.[dev]' -q --break-system-packages --user && \
           export PATH=/tmp/home/.local/bin:\$PATH && \
           if ls /cov/.coverage.* > /dev/null 2>&1; then \
               cp /cov/.coverage.* /tmp/comb/ && \
               coverage combine /tmp/comb/.coverage.* && \
               cp /tmp/comb/.coverage /cov/.coverage; \
           else \
               cp /cov/.coverage /tmp/comb/.coverage; \
           fi && \
           ${HTML:+coverage html -d /workspace/htmlcov && } \
           coverage report --fail-under=$THRESHOLD" || STATUS=$?

echo ""
if [ -n "$PARTIAL" ] && [ $STATUS -ne 2 ] && [ $STATUS -ne 0 ]; then
    # Partial data *and* the reporting itself failed, so there is no figure
    # above to call a floor. The tooling message is the one that helps: a
    # missing image is the usual cause and is reachable exactly here, since
    # --report-only skips the sweep that builds them.
    echo "❌ Coverage could not be measured (exit $STATUS), and this data is"
    echo "   from a partial sweep besides."
    echo ""
    echo "That is the tooling, not the figure: the container above says what"
    echo "went wrong. ./scripts/build.sh debian:13 builds the image this reads"
    echo "with; then re-run ./scripts/coverage.sh for the union."
    exit $STATUS
elif [ -n "$PARTIAL" ]; then
    # No ✅/❌: neither verdict is one this data can support. Above the
    # threshold it may still be short on a version that never ran, and below it
    # the missing lines may be covered there.
    echo "⚠  Reported from a partial sweep — no verdict against $THRESHOLD%."
    echo ""
    echo "The figure above is the floor the finished versions reached. Fix the"
    echo "failing version and re-run ./scripts/coverage.sh for the union."
    # Non-zero because the gate could not be answered, which is not the same as
    # passing it. A caller reading this as a gate gets the same "no" it gets
    # from missing data, rather than a pass off half the evidence.
    exit 1
elif [ $STATUS -eq 0 ]; then
    echo "✅ Coverage is at or above $THRESHOLD%"
elif [ $STATUS -ne 2 ]; then
    # Exit 2 is coverage's own "below --fail-under". Anything else came from
    # the machinery around it — a missing image (reachable through
    # --report-only, which skips the sweep that builds them), a pip failure, a
    # combine that found nothing — and reporting those as a coverage shortfall
    # sends the reader to write tests for a tool that never ran.
    echo "❌ Coverage could not be measured (exit $STATUS)"
    echo ""
    echo "That is the tooling, not the figure: the container above says what"
    echo "went wrong. A missing image is the usual one — ./scripts/build.sh"
    echo "debian:13 builds the one this reads with."
else
    echo "❌ Coverage is below $THRESHOLD%"
    echo ""
    echo "Every line and branch above is one nothing in the suite reaches on any"
    echo "supported version. Cover it with a test, or delete it if it cannot be"
    echo "reached — unreachable code is the defect, not the missing test."
    echo ""
    echo "$THRESHOLD% is the floor, not the goal: the goal is 100%, and the"
    echo "remaining work is listed in docs/issues/T-009."
    echo ""
    echo "Data kept in $GNC_COVERAGE_DIR — re-read it with:"
    echo "  ./scripts/coverage.sh --report-only"
    echo "  ./scripts/coverage.sh --report-only --html   # then open htmlcov/index.html"
fi
exit $STATUS

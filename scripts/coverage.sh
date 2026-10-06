#!/bin/bash
#
# Line and branch coverage, added up across every supported distribution.
#
# Usage:
#   ./scripts/coverage.sh                  # sweep every version, combine, gate
#   ./scripts/coverage.sh --report-only    # combine and report what is on disk
#   ./scripts/coverage.sh --threshold 99   # report a tree mid-change against a
#                                          # lower bar, without moving the gate
#
# One distribution's number is not this project's number. The tree carries
# paths that only a particular GnuCash runs — a slot read on 3.8 and 4.4 and
# derived from 4.13, a SWIG call that works on Debian and needs ctypes on
# Ubuntu — so a line can be untestable on the machine in front of you and
# ordinary on the next. What is gated is the union: every supported version
# runs the suite, and a line no version reached is a line nothing tests.
#
# The gate is 100%: every line and branch reached by some supported version,
# with anything unreachable deleted rather than excused. That is what the union
# measures, so the bare command passes on the tree as it stands and fails on the
# first line a change adds that no supported version runs. There is no floor to
# raise any more — a figure below 100 is a line nothing tests, and `--threshold`
# is for reading a tree mid-change, not for lowering the bar.
#
# Beside the union it gates what `tests/scenario/` alone reaches: the cases a
# person reported from a real book. Every line is recorded as reached by a
# scenario test or by the rest of the suite (the `scenario` and `suite`
# contexts, switched in tests/conftest.py), and the second report counts only
# lines the `scenario` context reached. It says how much of
# the tool real books exercise, which the union cannot, and it may not drop
# below SCENARIO_THRESHOLD, the figure the scenarios reached when it was set.
# The pre-commit hook and CI both reach this gate through `--report-only`.
#
# The data lands in .coverage-data/ (git-ignored) so a failing run can be read
# afterwards; `--report-only` re-reads it without running anything.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# The union as measured on 2026-09-16, across every supported build: 14,603
# statements and 5,294 branches, none of them missed.
#
# Only the union reaches it. One build on its own measures 99.04% (arch,
# ubuntu26) to 99.44% (latest, ubuntu24, fedora41, opensuse) of the same tree,
# because the paths a particular GnuCash takes run on the builds carrying that
# version and nowhere else. The tag names and the versions are not
# interchangeable either: `debian11` is 4.4, not 4.13, and `ubuntu24` is 5.5 —
# CLAUDE.md lists what each one carries.
THRESHOLD=100

# What `tests/scenario/` alone reaches, line and branch, on the union of every
# supported build: 45.22% measured on 2026-10-06, gated at 45.22%. A floor: a
# change may raise it, and a change that leaves the scenarios reaching less is
# refused. Two decimal places, because the report is read at that precision.
#
# It is gated at the figure measured, with no slack below it, because the
# figure CI gates cannot be lower than the one measured here. This script's
# sweep combines the eleven builds, and CI combines the same eleven and the
# arm64 run of `ubuntu24`. The figure is a union of lines and branch exits
# reached, against the same tree: a twelfth data file can add to what is
# reached and can take nothing away.
#
# It was 41.03% until Q-055's scenario tests of custom keys and of the keys
# gnucash-plaintext keeps for itself raised the measured figure from 41.05% to
# 42.35%, with the union at 100% before and after. Q-056's scenario tests of a
# Hong Kong company's book and a US company's book raised it to 42.46%, and
# the scenario tests of a customer's credit spent on an invoice posted at
# another rate raised it to 43.96%. Q-057 added the code that keeps a balance
# in each selected currency on every account, which no scenario test then
# reached, and the measured figure fell to 43.23%. The author's two cases for
# it, ACME LLC and ACMU LLC with a transaction deleted from each, and eighteen
# transactions among three accounts, raised it to 45.22%.
#
# **Before that it was 41.10%, from 41.12% measured the same day, and it came down because
# the tree gained code no book can reach.** A scenario is an accounting case —
# a book, a file, a command, and the figures that come back — and the library
# this tool loads GnuCash from is not one: no ledger a person writes can state a
# processor. The commit that found the engine by the processor the host reports
# added 26 statements and 8 branch exits of that kind, all of them covered by
# the suite (the union stayed at 100%) and none of them reachable by any
# scenario on any processor, which moved 41.12% to 41.05% with no scenario test
# weaker than it was.
#
# So the floor gives way to that dilution and to nothing else. It may be raised
# freely. It may be lowered only by a change that adds code no book can reach,
# by no more than the dilution that code causes, and the commit that lowers it
# states both figures. A test deleted, weakened, or moved out of
# `tests/scenario/` is not a reason, and a scenario test written to reach a line
# rather than to state a case is the thing this gate exists to refuse — calling
# an implementation function from `tests/scenario/` would clear the floor and
# measure nothing.
SCENARIO_THRESHOLD=45.22
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
           coverage report --fail-under=$THRESHOLD; \
           union=\$?; \
           echo ''; \
           echo '========================================='; \
           echo 'Scenario coverage: tests/scenario/ alone (gated at $SCENARIO_THRESHOLD%)'; \
           echo '========================================='; \
           coverage report --contexts='^scenario$' --precision=2 \
               --fail-under=$SCENARIO_THRESHOLD; \
           scenario=\$?; \
           if [ \$union -ne 0 ]; then exit \$union; fi; \
           if [ \$scenario -eq 2 ]; then exit 3; fi; \
           exit \$scenario" || STATUS=$?

echo ""
if [ -n "$PARTIAL" ] && [ $STATUS -ne 2 ] && [ $STATUS -ne 3 ] && [ $STATUS -ne 0 ]; then
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
    echo "✅ Coverage is at or above $THRESHOLD%, and the scenarios reach at least $SCENARIO_THRESHOLD%"
elif [ $STATUS -eq 3 ]; then
    # The union is whole; what fell is what `tests/scenario/` alone reaches.
    echo "❌ The scenarios reach less than $SCENARIO_THRESHOLD%"
    echo ""
    echo "The union is at $THRESHOLD%, so every line is still tested. What fell"
    echo "is how much of the tool the scenario tests reach on their own: a"
    echo "scenario was removed or narrowed, or code they ran was moved where"
    echo "none of them runs it. Put the scenario back, or add one that reaches"
    echo "the code. The floor may be raised; it is not lowered."
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
    echo "The union has been whole since 2026-09-16, so a line missing here"
    echo "arrived with a change rather than being left over from before."
    echo ""
    echo "Data kept in $GNC_COVERAGE_DIR — re-read it with:"
    echo "  ./scripts/coverage.sh --report-only"
    echo "  ./scripts/coverage.sh --report-only --html   # then open htmlcov/index.html"
fi
exit $STATUS

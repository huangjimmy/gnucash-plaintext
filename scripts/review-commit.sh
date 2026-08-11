#!/bin/bash
#
# Independent AI review of a change.
#
# Reviews the staged index (what the pre-commit hook runs) or a change that is
# already committed, so a review that times out during a commit can be run
# again afterwards against the commit it missed.
#
# Usage:
#   ./scripts/review-commit.sh                      # staged changes
#   ./scripts/review-commit.sh -m "commit message"  # staged changes, proposed message
#   ./scripts/review-commit.sh --working            # everything uncommitted, vs main
#   ./scripts/review-commit.sh HEAD                 # the commit just made
#   ./scripts/review-commit.sh 7f60d32              # any commit, by sha or tag
#   ./scripts/review-commit.sh main..HEAD           # a whole branch, as one diff
#   ./scripts/review-commit.sh --dry-run HEAD       # what would be reviewed, no AI call
#
# `--working` is for work still in progress: it diffs the working tree against
# `main` (override with REVIEW_BASE) and counts untracked files, so a review
# can be had before there is anything to commit. It stages nothing.
#
# The commit's own message is given to the reviewer; -m is for the staged case,
# where no message exists yet, and doubles as the place to tell the reviewer
# what the change is trying to do — what to look at, what was already decided,
# what not to re-litigate.
#
# Environment:
#   AI_REVIEW_TIMEOUT   seconds to allow (default 1800). Ten minutes was the
#                       default and was not enough: this repo's
#                       foreign-currency commit is ~8k added lines, and a
#                       4.5k-line working tree timed out at 600s having done
#                       the work — the run is thrown away, not resumed, so a
#                       short default costs the whole review rather than
#                       truncating it.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

TIMEOUT_SECONDS="${AI_REVIEW_TIMEOUT:-1800}"
COMMIT_MSG=""
REVISION=""
DRY_RUN=0
WORKING=""

while [ $# -gt 0 ]; do
    case "$1" in
        --working)
            WORKING=1
            shift
            ;;
        -m|--message)
            if [ $# -lt 2 ]; then
                echo "❌ -m needs a message" >&2
                exit 2
            fi
            COMMIT_MSG="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            # The header block only: every line up to the first that is not a
            # comment, so the body of the script never leaks into the help.
            sed -n '2,${/^#/!q;p;}' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            if [ -n "$REVISION" ]; then
                echo "❌ Only one revision may be reviewed at a time (got '$REVISION' and '$1')" >&2
                exit 2
            fi
            REVISION="$1"
            shift
            ;;
    esac
done

# Collect the diff and the message that goes with it.
if [ -n "$REVISION" ]; then
    if [[ "$REVISION" == *..* ]]; then
        # A range: review every commit in it as one diff.
        if ! git rev-list --quiet "$REVISION" >/dev/null 2>&1; then
            echo "❌ Not a valid revision range: $REVISION" >&2
            exit 2
        fi
        DIFF=$(git diff --no-color "$REVISION")
        [ -n "$COMMIT_MSG" ] || COMMIT_MSG=$(git log --format='%B' "$REVISION")
        SUBJECT="$REVISION ($(git rev-list --count "$REVISION") commits)"
    else
        if ! git rev-parse --verify --quiet "${REVISION}^{commit}" >/dev/null; then
            echo "❌ Not a commit: $REVISION" >&2
            exit 2
        fi
        SHA=$(git rev-parse --short "$REVISION")
        # `--format=` drops the header so only the patch reaches the reviewer;
        # the message is passed separately, under its own heading.
        DIFF=$(git show --no-color --format= "$REVISION")
        [ -n "$COMMIT_MSG" ] || COMMIT_MSG=$(git log -1 --format='%B' "$REVISION")
        SUBJECT="$SHA $(git log -1 --format='%s' "$REVISION")"
    fi
    SOURCE="commit"
elif [ -n "$WORKING" ]; then
    # Everything not yet committed, staged or not, against the base branch —
    # which is what "review what I have written so far" means while the work
    # is still in progress. Untracked files are included by registering them
    # with `--intent-to-add`: without it a whole new module reads as absent,
    # and a review of new work would see only the edits to old files.
    #
    # `-N` stages no content, but it does register the path in the index, and
    # that registration outlives this script: after one review, `git add -u`
    # and `git commit -a` would pick those files up. CLAUDE.md forbids
    # `git add -A` for exactly that reason — untracked probes, secrets and the
    # external reference files (`convert_qfx.py`, `ledger.py`,
    # `reference_file*.txt`) must never be swept in — so a review that leaves
    # them registered hands the next commit the mistake the rule prevents.
    #
    # Named explicitly rather than `--all`, and undone on the way out however
    # this exits: the paths are remembered first, and a trap resets exactly
    # those and nothing else.
    #
    # On INT and TERM as well as EXIT. A review runs up to half an hour, so
    # being interrupted part-way through one is the ordinary case, not the
    # exotic one — and an EXIT trap alone does not run when the shell is
    # killed by a signal, which is exactly the run that would leave the paths
    # registered.
    #
    # Each signal handler exits. Bash *resumes* the script after a trap
    # returns, so a single `trap ... EXIT INT TERM` unregistered the paths
    # mid-run and then carried on reviewing a diff those files had just been
    # removed from — measured: `[cleanup ran]`, the work after the signal,
    # `[cleanup ran]` again, exit 0. A review that reports success on half the
    # diff is worse than one that stops.
    #
    # And a note on disk, because no trap runs for `kill -9` or a lost
    # terminal. The next run resets whatever the last one left registered
    # before it registers anything of its own, so the mistake CLAUDE.md's
    # `git add -A` rule exists to prevent cannot outlive one review.
    REVIEW_LEFTOVERS="$(git rev-parse --git-dir)/review-commit-registered"
    if [ -s "$REVIEW_LEFTOVERS" ]; then
        # Only paths still registered and still empty. `--intent-to-add` puts
        # the path in the index with nothing in it, which `git status
        # --porcelain` reports as `" A"` — a space in the staged column. A
        # file the user has since staged for real reads `"A "`, and unstaging
        # that would throw away work this script never did. A killed run
        # leaves this note behind, so the list can be a day old and mean
        # nothing by the time it is read.
        while IFS= read -r leftover; do
            [ -n "$leftover" ] || continue
            state=$(git status --porcelain -- "$leftover" 2>/dev/null | head -1)
            case "$state" in
                ' A'*) git reset -q -- "$leftover" >/dev/null 2>&1 || true ;;
            esac
        done < "$REVIEW_LEFTOVERS"
        rm -f "$REVIEW_LEFTOVERS"
    fi
    REVIEW_ADDED=$(git ls-files --others --exclude-standard)
    if [ -n "$REVIEW_ADDED" ]; then
        printf '%s\n' "$REVIEW_ADDED" > "$REVIEW_LEFTOVERS"
        printf '%s\n' "$REVIEW_ADDED" | tr '\n' '\0' \
            | xargs -0 -r git add --intent-to-add -- >/dev/null 2>&1 || true
        _review_unregister() {
            printf '%s\n' "$REVIEW_ADDED" | tr '\n' '\0' \
                | xargs -0 -r git reset -q -- >/dev/null 2>&1 || true
            rm -f "$REVIEW_LEFTOVERS"
        }
        trap '_review_unregister' EXIT
        trap '_review_unregister; exit 130' INT
        trap '_review_unregister; exit 143' TERM
    fi
    BASE=${REVIEW_BASE:-main}
    if git rev-parse --verify --quiet "${BASE}^{commit}" >/dev/null; then
        # Against where the branch left the base, not the base's tip. This is
        # an open-source repo where other work lands while a branch is open,
        # and diffing the tip presents every commit merged since the branch
        # point as a deletion — the reviewer is handed inverted hunks removing
        # code this branch never touched, and asked to approve it.
        MERGE_BASE=$(git merge-base "$BASE" HEAD 2>/dev/null || echo "$BASE")
        DIFF=$(git diff --no-color "$MERGE_BASE")
        SUBJECT="working tree vs $BASE"
    else
        DIFF=$(git diff --no-color HEAD)
        SUBJECT="working tree vs HEAD"
    fi
    [ -n "$COMMIT_MSG" ] || COMMIT_MSG="[Uncommitted work in progress]"
    SOURCE="working tree"
else
    DIFF=$(git diff --staged --no-color)
    [ -n "$COMMIT_MSG" ] || COMMIT_MSG="[No commit message provided]"
    SUBJECT="staged changes"
    SOURCE="index"
fi

if [ -z "$DIFF" ]; then
    if [ "$SOURCE" = "index" ]; then
        echo "⚠️  No staged changes to review"
        echo "   To review a change that is already committed:"
        echo "     ./scripts/review-commit.sh HEAD"
    else
        echo "⚠️  $SUBJECT changes nothing — nothing to review"
    fi
    exit 0
fi

DIFF_LINES=$(printf '%s\n' "$DIFF" | wc -l)

if [ "$DRY_RUN" = "1" ]; then
    echo "Would review: $SUBJECT"
    echo "Diff:         $DIFF_LINES lines"
    echo "Timeout:      ${TIMEOUT_SECONDS}s"
    echo "Message:      $(printf '%s' "$COMMIT_MSG" | head -1)"
    exit 0
fi

# Determine which AI tool to use
AI_CMD=""
AI_NAME=""

if [ -n "$CLAUDECODE" ]; then
    AI_CMD="claude"
    AI_NAME="Claude Code"
elif [ -n "$GEMINI_CLI" ]; then
    AI_CMD="gemini"
    AI_NAME="Gemini CLI"
else
    # Read strict preference from local git config
    PREFERRED_AI=$(git config --get ai.reviewer || echo "")

    if [ "$PREFERRED_AI" = "claude" ] && command -v claude >/dev/null 2>&1; then
        AI_CMD="claude"
        AI_NAME="Claude Code (Terminal Default)"
    elif [ "$PREFERRED_AI" = "gemini" ] && command -v gemini >/dev/null 2>&1; then
        AI_CMD="gemini"
        AI_NAME="Gemini CLI (Terminal Default)"
    else
        echo "⚠️  No AI reviewer set or installed."
        echo "   To enable manual AI review, set your preferred reviewer:"
        echo "   git config --local ai.reviewer claude  (or gemini)"
        exit 0
    fi
fi

echo "🔍 Reviewing $SUBJECT with $AI_NAME..."
echo "   ($DIFF_LINES diff lines, up to ${TIMEOUT_SECONDS}s)"
echo ""

# Build review prompt
REVIEW_PROMPT=$(cat <<EOF
You are an independent code reviewer conducting a pre-commit review.

**IMPORTANT**: You have NOT seen the implementation process. You are reviewing this commit with fresh eyes from an outsider's perspective.

## Commit Message:
\`\`\`
$COMMIT_MSG
\`\`\`

## What has already been run:
The pre-commit hook runs lint and the **whole test suite on every supported
distribution** — Debian 11/12/13, Ubuntu 20.04/22.04/24.04/26.04, Fedora 41,
Arch and openSUSE Tumbleweed, which is every supported GnuCash from 3.8 to
5.16 — and stops before reaching you unless all of it passed. Running tests yourself is optional and
"the cross-version sweep should be run" is not a finding. What is worth
reporting is a behaviour no test covers.

## Your Task:
1. Understand what this commit is trying to do
2. Verify the changes are correct and complete
3. Check for: logic errors, missing edge cases, security issues, missing tests
4. Output your decision:
   - If issues found: Start your response with "CONCERNS:" and list specific issues
   - If approved: Start your response with "APPROVED:" and briefly explain why

Be concise but specific. Focus on real issues that would cause problems.

=== CHANGES UNDER REVIEW ($SUBJECT) ===
$DIFF
EOF
)

# Save prompt to temp file
TEMP_PROMPT=$(mktemp)
echo "$REVIEW_PROMPT" > "$TEMP_PROMPT"

# Helper function to isolate AI env and protect git index
run_ai() {
  unset CLAUDECODE
  unset GEMINI_CLI
  unset GEMINI_CLI_NO_RELAUNCH

  local index_file
  index_file=$(git rev-parse --git-path index 2>/dev/null || true)
  # Resolve to absolute path so it works in worktrees and subshells
  if [ -n "$index_file" ] && [ -f "$index_file" ]; then
    index_file=$(realpath "$index_file")
  else
    index_file=""
  fi
  local index_backup=""
  if [ -n "$index_file" ]; then
    index_backup="${index_file}.pre-review-backup"
    cp "$index_file" "$index_backup"
  fi

  # Ensure cleanup happens even if subshell is aborted
  trap '[[ -n "$index_backup" ]] && cp "$index_backup" "$index_file" && rm -f "$index_backup"' EXIT INT TERM

  local exit_code
  if [ "$AI_CMD" = "gemini" ]; then
      # Gemini CLI can read from stdin, avoiding ARG_MAX limits for large diffs
      timeout "${TIMEOUT_SECONDS}s" gemini < "$TEMP_PROMPT" 2>&1
      exit_code=$?
  else
      # Claude Code takes prompt via stdin
      timeout "${TIMEOUT_SECONDS}s" claude < "$TEMP_PROMPT" 2>&1
      exit_code=$?
  fi

  # The trap will handle the cleanup upon successful exit as well
  return $exit_code
}

# Execute review and capture output
set +e # Disable exit on error to capture timeout/failure
REVIEW_OUTPUT=$(run_ai)
REVIEW_EXIT=$?
set -e

# Display the review output
echo "-------------------------------------------------------------"
echo "$REVIEW_OUTPUT"
echo "-------------------------------------------------------------"
echo ""

# Cleanup
rm -f "$TEMP_PROMPT"

# The verdict decides, and it is looked for FIRST. Anything else — a timeout, a
# non-zero exit, a message about a usage limit — is only meaningful when the
# reviewer produced no verdict at all. Asking "did it run?" first got this
# backwards: a completed review whose own text discussed rate limiting matched
# the out-of-budget heuristic and was announced as "No AI review", exit 0, with
# its objections on screen and unheeded.
#
# The verdict is matched through whatever markdown wrapped it — `## CONCERNS:`
# and `**CONCERNS:**` are both how one actually came back. Concerns outrank
# approval when both appear: a reviewer that approves parts and objects to
# others has objected.
# Only a run that finished has a verdict. A review killed mid-sentence may
# already have printed "APPROVED:" for one part of a change it never got to
# the end of, and counting that would approve on partial evidence.
VERDICT_LINES=""
if [ $REVIEW_EXIT -eq 0 ]; then
    VERDICT_LINES=$(printf '%s\n' "$REVIEW_OUTPUT" | sed -E 's/^[[:space:]#*_>-]+//')
fi

if printf '%s\n' "$VERDICT_LINES" | grep -qE "^CONCERNS"; then
    echo "❌ AI review found concerns"
    exit 1
fi

if printf '%s\n' "$VERDICT_LINES" | grep -qE "^APPROVED"; then
    echo "✅ AI review approved!"
    exit 0
fi

# No verdict. Either the reviewer could not run — a timeout, a missing CLI, an
# account out of budget — or it answered without deciding. Neither is an
# objection to the change, so only the second blocks: an unavailable reviewer
# would otherwise strand every commit until its limit resets.
if [ $REVIEW_EXIT -eq 124 ]; then
    UNAVAILABLE="it timed out after ${TIMEOUT_SECONDS}s ($DIFF_LINES diff lines)"
elif [ $REVIEW_EXIT -ne 0 ]; then
    UNAVAILABLE="the reviewer exited $REVIEW_EXIT without reviewing"
elif printf '%s\n' "$REVIEW_OUTPUT" | grep -qiE "session limit|usage limit|rate limit"; then
    UNAVAILABLE="the reviewer is out of budget until its limit resets"
else
    UNAVAILABLE=""
fi

if [ -n "$UNAVAILABLE" ]; then
    echo "⚠️  No AI review: $UNAVAILABLE"
    if [ "$SOURCE" = "index" ]; then
        echo "   The commit is NOT reviewed. Review it once it exists with:"
        echo "     AI_REVIEW_TIMEOUT=1800 ./scripts/review-commit.sh HEAD"
    else
        echo "   Retry with:"
        echo "     AI_REVIEW_TIMEOUT=1800 ./scripts/review-commit.sh $REVISION"
    fi
    exit 0
fi

echo "❌ The reviewer answered but gave no verdict — treating as unreviewed"
echo "   Expected a line starting with APPROVED: or CONCERNS:."
exit 1

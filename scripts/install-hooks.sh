#!/bin/bash
#
# Install git hooks for the project
#
# Run this script after cloning the repository to enable pre-commit checks
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_HOOKS_DIR="$SCRIPT_DIR/hooks"

# Where the hooks go, asked of git rather than assumed to be `.git/hooks`.
# Every feature branch here is a worktree (CLAUDE.md), and a worktree's `.git`
# is a *file* holding the path of the real directory — so `[ -d .git ]`
# answered "Not in a git repository" in the one place the work is done, and
# the path beside it would have been wrong as well. Hooks live in the common
# directory, shared by the main checkout and every worktree of it, so one
# install serves them all.
if ! COMMON=$(cd "$PROJECT_ROOT" && git rev-parse --git-common-dir 2>/dev/null); then
    echo "Error: Not in a git repository"
    exit 1
fi
case "$COMMON" in
    /*) ;;
    *) COMMON="$PROJECT_ROOT/$COMMON" ;;
esac
HOOKS_DIR="$COMMON/hooks"
mkdir -p "$HOOKS_DIR"

# Each hook is installed on its own, and one already there is left alone.
# Two reasons, and both have happened: `commit-msg` arrived after `pre-commit`,
# so a clone that installed hooks before it existed would never get it if the
# check were "are any installed"; and a hook someone has edited is theirs, so
# overwriting it to deliver a *different* one is not an install, it is a loss.
echo "Installing git hooks..."
INSTALLED=0
for hook in pre-commit commit-msg; do
    if [ -f "$HOOKS_DIR/$hook" ]; then
        echo "• $hook is already there — left as it is"
        continue
    fi
    cp "$SOURCE_HOOKS_DIR/$hook" "$HOOKS_DIR/$hook"
    chmod +x "$HOOKS_DIR/$hook"
    echo "✓ Installed $hook hook"
    INSTALLED=$((INSTALLED + 1))
done

if [ "$INSTALLED" = "0" ]; then
    echo ""
    echo "Nothing to do. To take a fresh copy of one, delete it from"
    echo ".git/hooks/ and run this script again."
    exit 0
fi

echo ""
echo "Git hooks installed successfully!"
echo ""
echo "The pre-commit hook will now:"
echo "  - Run ruff linting checks"
echo "  - Run the suite on all eleven supported builds, with coverage, and"
echo "    refuse a commit that leaves the union below 100%"
echo "  - Build the wheel, install it and draw a page with it, which is the"
echo "    only check that sees a data file the wheel leaves out"
echo ""
echo "The commit-msg hook refuses a hard-wrapped message: one paragraph is one"
echo "line, and paragraphs are separated by a blank line. Then it runs an"
echo "independent AI review of the staged diff, given the commit message."
echo ""
echo "Commits will be blocked if checks fail."

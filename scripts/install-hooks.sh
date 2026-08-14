#!/bin/bash
#
# Install git hooks for the project
#
# Run this script after cloning the repository to enable pre-commit checks
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"
SOURCE_HOOKS_DIR="$SCRIPT_DIR/hooks"

# Check if we're in a git repository
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "Error: Not in a git repository"
    exit 1
fi

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
echo "  - Run all tests"
echo "  - Run an independent AI review of the staged diff"
echo ""
echo "The commit-msg hook refuses a hard-wrapped message: one paragraph is one"
echo "line, and paragraphs are separated by a blank line."
echo ""
echo "Commits will be blocked if checks fail."

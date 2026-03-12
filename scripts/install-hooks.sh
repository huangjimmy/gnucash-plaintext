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

# Check if already installed
if [ -f "$HOOKS_DIR/pre-commit" ]; then
    echo "Git hooks are already installed."
    echo ""
    echo "To reinstall, remove .git/hooks/pre-commit and run this script again."
    exit 0
fi

# Install pre-commit hook
echo "Installing git hooks..."
cp "$SOURCE_HOOKS_DIR/pre-commit" "$HOOKS_DIR/pre-commit"
chmod +x "$HOOKS_DIR/pre-commit"
echo "✓ Installed pre-commit hook"

echo ""
echo "Git hooks installed successfully!"
echo ""
echo "The pre-commit hook will now:"
echo "  - Run ruff linting checks"
echo "  - Run all tests"
echo ""
echo "Commits will be blocked if checks fail."

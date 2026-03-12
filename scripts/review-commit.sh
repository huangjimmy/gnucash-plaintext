#!/bin/bash
#
# Manual commit review script
#
# Allows users to review staged changes before committing.
# Uses the same AI review logic as the pre-commit hook.
#
# Usage:
#   ./scripts/review-commit.sh                    # Review staged changes
#   ./scripts/review-commit.sh "commit message"   # Review with proposed message
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Get commit message from argument or use placeholder
if [ -n "$1" ]; then
    COMMIT_MSG="$1"
else
    COMMIT_MSG="[No commit message provided]"
fi

# Get staged changes
STAGED_DIFF=$(git diff --staged --no-color)

if [ -z "$STAGED_DIFF" ]; then
    echo "❌ No staged changes to review"
    echo ""
    echo "Stage some changes first:"
    echo "  git add <files>"
    exit 1
fi

# Check if claude command is available
if ! command -v claude > /dev/null 2>&1; then
    echo "❌ Claude Code not installed"
    echo ""
    echo "Install Claude Code to use AI-powered commit reviews:"
    echo "  https://claude.ai/download"
    exit 1
fi

echo "🔍 Reviewing staged changes..."
echo ""

# Build review prompt
REVIEW_PROMPT=$(cat <<EOF
You are an independent code reviewer conducting a pre-commit review.

**IMPORTANT**: You have NOT seen the implementation process. You are reviewing this commit with fresh eyes from an outsider's perspective.

## Commit Message:
\`\`\`
$COMMIT_MSG
\`\`\`

## Staged Changes:
\`\`\`diff
$STAGED_DIFF
\`\`\`

## Your Task:

1. **Understand Intent**: Read the commit message. What does it claim was done?

2. **Review Changes**: Examine the staged diff carefully.

3. **Verify Completeness**:
   - Does the code match what the commit message claims?
   - Are all claimed changes present?
   - Is anything missing?

4. **Check Correctness**:
   - Do the changes make sense?
   - Are there obvious bugs or edge cases?
   - Is the implementation correct?
   - Are there any syntax errors or typos?

5. **Code Quality**:
   - Is the code clean and maintainable?
   - Are there unnecessary changes (commented code, debug statements)?
   - Does it follow project conventions?

6. **Report**:
   - Start with either "**APPROVED**" or "**CONCERNS**"
   - If approved: Briefly state why the commit looks good
   - If concerns: List specific issues clearly
   - Be constructive and specific

Begin your review now.
EOF
)

# Run review with timeout (90 seconds)
echo "   (Tip: This may take up to 90 seconds)"
echo ""

# Save prompt to temp file
TEMP_PROMPT=$(mktemp)
TEMP_OUTPUT=$(mktemp)
echo "$REVIEW_PROMPT" > "$TEMP_PROMPT"

# Run claude review with timeout and capture output
if timeout 90s claude --no-input < "$TEMP_PROMPT" > "$TEMP_OUTPUT" 2>&1; then
    REVIEW_EXIT=$?
else
    REVIEW_EXIT=$?
fi

# Display the review output
echo "─────────────────────────────────────────────────────────────"
cat "$TEMP_OUTPUT"
echo "─────────────────────────────────────────────────────────────"
echo ""

# Cleanup
rm -f "$TEMP_PROMPT" "$TEMP_OUTPUT"

# Handle timeout
if [ $REVIEW_EXIT -eq 124 ]; then
    echo "⚠️  AI review timed out after 90 seconds"
    echo "   The review is taking longer than expected"
    echo "   You can proceed with manual review or try again"
    exit 0
fi

# Check if review raised concerns (non-zero exit means concerns)
if [ $REVIEW_EXIT -ne 0 ]; then
    echo "⚠️  AI review completed with concerns"
    echo "   Review the feedback above before committing"
    exit 1
fi

echo "✅ AI review approved!"
exit 0

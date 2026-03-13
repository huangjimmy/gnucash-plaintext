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
    echo "⚠️  No staged changes to review"
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

echo "🔍 Reviewing staged changes with $AI_NAME..."
echo "   (Tip: This may take up to 90 seconds)"
echo ""

# Build review prompt
REVIEW_PROMPT=$(cat <<EOF
You are an independent code reviewer conducting a pre-commit review.

**IMPORTANT**: You have NOT seen the implementation process. You are reviewing this commit with fresh eyes from an outsider's perspective.

## Commit Message:
\`\`\`
$COMMIT_MSG
\`\`\`

## Your Task:
1. Understand what this commit is trying to do
2. Verify the changes are correct and complete
3. Check for: logic errors, missing edge cases, security issues, missing tests
4. Output your decision:
   - If issues found: Start your response with "CONCERNS:" and list specific issues
   - If approved: Start your response with "APPROVED:" and briefly explain why

Be concise but specific. Focus on real issues that would cause problems.

=== STAGED CHANGES ===
$STAGED_DIFF
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
  index_file=$(git rev-parse --git-path index)
  local index_backup="${index_file}.pre-review-backup"
  cp "$index_file" "$index_backup"

  # Ensure cleanup happens even if subshell is aborted
  trap 'cp "$index_backup" "$index_file"; rm -f "$index_backup"' EXIT INT TERM
  
  local exit_code
  if [ "$AI_CMD" = "gemini" ]; then
      # Gemini CLI can read from stdin, avoiding ARG_MAX limits for large diffs
      timeout 90s gemini < "$TEMP_PROMPT" 2>&1
      exit_code=$?
  else
      # Claude Code takes prompt via stdin
      timeout 90s claude < "$TEMP_PROMPT" 2>&1
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

# Handle timeout
if [ $REVIEW_EXIT -eq 124 ]; then
    echo "⚠️  AI review timed out after 90 seconds - proceeding without review"
    exit 0
fi

# Check for approval or concerns based on explicit keywords
if echo "$REVIEW_OUTPUT" | grep -q "^APPROVED:"; then
    echo "✅ AI review approved!"
    exit 0
elif echo "$REVIEW_OUTPUT" | grep -q "^CONCERNS:"; then
    echo "❌ AI review found concerns"
    exit 1
else
    echo "⚠️  AI review output format unexpected - proceeding anyway"
    exit 0
fi

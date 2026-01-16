#!/bin/bash
#
# fix.sh - Fix Agent
#
# Implements a fix based on research from the Research Agent.
# Creates a commit with the changes.
#
# Required environment:
#   ISSUE_RUN_DIR - Directory for this issue's run data
#   ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY - Issue details
#   SCRIPT_DIR - Root directory of the fix-all-the-things project
#   PROJECT_DIR - The target repository to fix
#
# Requires:
#   research.state.json - Output from research agent
#
# Outputs:
#   ${ISSUE_RUN_DIR}/fix.state.json - Fix results
#   ${ISSUE_RUN_DIR}/fix.log - Full Claude output
#

set -euo pipefail

AGENT_NAME="FIX"

# Source common utilities
source "${SCRIPT_DIR}/agents/common.sh"

agent_log AGENT "Starting fix implementation for issue #${ISSUE_NUMBER}"

# Check if research exists (allow partial research)
RESEARCH_STATE="${ISSUE_RUN_DIR}/research.state.json"
if [ ! -f "$RESEARCH_STATE" ]; then
    agent_log ERROR "Research agent did not run"
    exit 1
fi

RESEARCH_STATUS=$(load_agent_state "$RESEARCH_STATE" "status")
if [ "$RESEARCH_STATUS" = "failed" ]; then
    agent_log ERROR "Research agent failed, cannot proceed"
    exit 1
fi

# Extract research findings for the prompt
RESEARCH_CONFIDENCE=$(load_agent_state "$RESEARCH_STATE" "confidence")
agent_log INFO "Research confidence: $RESEARCH_CONFIDENCE"

# Get detailed findings
if jq -e '.findings' "$RESEARCH_STATE" &>/dev/null; then
    ROOT_CAUSE=$(jq -r '.findings.root_cause.description // "See research log"' "$RESEARCH_STATE")
    FILES_TO_MODIFY=$(jq -r '.findings.files_to_modify // [] | map("- \(.path): \(.reason)") | join("\n")' "$RESEARCH_STATE")
    PATTERNS_TO_FOLLOW=$(jq -r '.findings.patterns_to_follow // [] | map("- \(.description)") | join("\n")' "$RESEARCH_STATE")
    RISKS=$(jq -r '.findings.risks // [] | map("- \(.description): \(.mitigation)") | join("\n")' "$RESEARCH_STATE")
else
    ROOT_CAUSE=$(load_agent_state "$RESEARCH_STATE" "root_cause_summary")
    FILES_TO_MODIFY="See research log for details"
    PATTERNS_TO_FOLLOW="Follow existing codebase patterns"
    RISKS="Review changes carefully"
fi

export ROOT_CAUSE
export FILES_TO_MODIFY
export PATTERNS_TO_FOLLOW
export RISKS

# Build the prompt
PROMPT_TEMPLATE="${SCRIPT_DIR}/prompts/fix.md"
PROMPT_FILE="${ISSUE_RUN_DIR}/fix.prompt.md"

envsubst '${ISSUE_NUMBER} ${ISSUE_TITLE} ${ISSUE_BODY} ${ROOT_CAUSE} ${FILES_TO_MODIFY} ${PATTERNS_TO_FOLLOW} ${RISKS}' \
    < "$PROMPT_TEMPLATE" > "$PROMPT_FILE"

# Change to project directory
cd "$PROJECT_DIR"

# Run Claude to implement fix
LOG_FILE="${ISSUE_RUN_DIR}/fix.log"

agent_log INFO "Implementing fix (timeout: 10 minutes)..."

if ! run_claude "$PROMPT_FILE" "$LOG_FILE" 600; then
    agent_log ERROR "Claude failed during fix implementation"
    save_agent_state "${ISSUE_RUN_DIR}/fix.state.json" \
        "status=failed" \
        "error=Claude execution failed"
    exit 1
fi

# Check if Claude created SKIP_ISSUE.txt
if [ -f "SKIP_ISSUE.txt" ]; then
    SKIP_REASON=$(cat SKIP_ISSUE.txt)
    agent_log WARNING "Fix agent skipped: $SKIP_REASON"
    rm SKIP_ISSUE.txt

    cat > "${ISSUE_RUN_DIR}/fix.state.json" <<EOF
{
    "status": "skipped",
    "agent": "fix",
    "issue_number": ${ISSUE_NUMBER},
    "fix_applied": false,
    "reason": $(echo "$SKIP_REASON" | jq -R '.'),
    "timestamp": "$(date -Iseconds)"
}
EOF
    exit 2
fi

# Check if changes were made
GIT_STATUS=$(git status --porcelain)

if [ -z "$GIT_STATUS" ]; then
    # Check if there's already a commit
    COMMITS_AHEAD=$(git rev-list --count "origin/${BASE_BRANCH:-develop}..HEAD" 2>/dev/null || echo "0")

    if [ "$COMMITS_AHEAD" -eq 0 ]; then
        agent_log WARNING "No changes made by fix agent"
        cat > "${ISSUE_RUN_DIR}/fix.state.json" <<EOF
{
    "status": "no_changes",
    "agent": "fix",
    "issue_number": ${ISSUE_NUMBER},
    "fix_applied": false,
    "reason": "No code changes were made",
    "timestamp": "$(date -Iseconds)"
}
EOF
        exit 2
    fi
fi

# If there are uncommitted changes, Claude didn't commit - create a fallback commit
if [ -n "$GIT_STATUS" ]; then
    agent_log WARNING "Uncommitted changes detected, creating commit..."

    # Exclude sensitive files
    git add -A ':!.env' ':!.env.*'

    # Verify no sensitive files staged
    STAGED_FILES=$(git diff --cached --name-only)
    if echo "$STAGED_FILES" | grep -qE '^\.env|/\.env'; then
        agent_log ERROR "Refusing to commit .env files"
        git reset HEAD
        exit 1
    fi

    git commit -m "fix: Address issue #${ISSUE_NUMBER} - ${ISSUE_TITLE}

Implemented by Fix Agent based on Research Agent findings.

Co-Authored-By: Claude <noreply@anthropic.com>" || {
        agent_log ERROR "Failed to create commit"
        exit 1
    }
fi

# Extract fix results from log
FIX_JSON=$(cat "$LOG_FILE" | tr '\n' ' ' | grep -oP '\{[^{}]*"fix_applied"[^{}]*\}' | tail -1 || echo "")

# Get commit info
COMMIT_MSG=$(git log -1 --format="%B")
FILES_CHANGED=$(git diff --name-only HEAD~1 2>/dev/null | wc -l || echo "unknown")
LINES_CHANGED=$(git diff --stat HEAD~1 2>/dev/null | tail -1 | grep -oP '\d+ insertion|\d+ deletion' | head -2 | tr '\n' ', ' || echo "unknown")

# Extract confidence from commit message or fix JSON
if [ -n "$FIX_JSON" ] && echo "$FIX_JSON" | jq -e '.confidence.overall' &>/dev/null; then
    CONFIDENCE=$(echo "$FIX_JSON" | jq -r '.confidence.overall')
else
    CONFIDENCE=$(echo "$COMMIT_MSG" | grep -oP 'Overall: \K[0-9.]+' || echo "0.7")
fi

agent_log SUCCESS "Fix implemented (confidence: $CONFIDENCE)"
agent_log INFO "Files changed: $FILES_CHANGED"

# Save state
cat > "${ISSUE_RUN_DIR}/fix.state.json" <<EOF
{
    "status": "success",
    "agent": "fix",
    "issue_number": ${ISSUE_NUMBER},
    "fix_applied": true,
    "confidence": $CONFIDENCE,
    "files_changed": $FILES_CHANGED,
    "commit_sha": "$(git rev-parse HEAD)",
    "timestamp": "$(date -Iseconds)"
}
EOF

agent_log AGENT "Fix implementation complete"
exit 0

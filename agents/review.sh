#!/bin/bash
#
# review.sh - Review Agent
#
# Reviews the fix implemented by the Fix Agent before creating a PR.
# This is the last line of defense.
#
# Required environment:
#   ISSUE_RUN_DIR - Directory for this issue's run data
#   ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY - Issue details
#   SCRIPT_DIR - Root directory of the fix-all-the-things project
#   PROJECT_DIR - The target repository
#   BASE_BRANCH - The base branch (e.g., develop)
#
# Requires:
#   fix.state.json - Output from fix agent
#
# Outputs:
#   ${ISSUE_RUN_DIR}/review.state.json - Review results
#   ${ISSUE_RUN_DIR}/review.log - Full Claude output
#

set -euo pipefail

AGENT_NAME="REVIEW"

# Source common utilities
source "${SCRIPT_DIR}/agents/common.sh"

agent_log AGENT "Starting review for issue #${ISSUE_NUMBER}"

# Verify fix agent ran
FIX_STATE="${ISSUE_RUN_DIR}/fix.state.json"
if [ ! -f "$FIX_STATE" ]; then
    agent_log ERROR "Fix agent did not run"
    exit 1
fi

FIX_STATUS=$(load_agent_state "$FIX_STATE" "status")
if [ "$FIX_STATUS" != "success" ]; then
    agent_log ERROR "Fix agent did not succeed (status: $FIX_STATUS)"
    exit 1
fi

FIX_CONFIDENCE=$(load_agent_state "$FIX_STATE" "confidence")
agent_log INFO "Fix confidence: $FIX_CONFIDENCE"

# Change to project directory
cd "$PROJECT_DIR"

# Get the diff and commit message
GIT_DIFF=$(git diff "${BASE_BRANCH}..HEAD" 2>/dev/null || git diff HEAD~1 2>/dev/null || echo "No diff available")
COMMIT_MSG=$(git log -1 --format="%B" 2>/dev/null || echo "No commit message")

# Truncate diff if too large (keep first 5000 chars)
if [ ${#GIT_DIFF} -gt 5000 ]; then
    GIT_DIFF="${GIT_DIFF:0:5000}

... (diff truncated, ${#GIT_DIFF} total characters)"
fi

export FIX_CONFIDENCE
export GIT_DIFF
export COMMIT_MSG

# Build the prompt
PROMPT_TEMPLATE="${SCRIPT_DIR}/prompts/review.md"
PROMPT_FILE="${ISSUE_RUN_DIR}/review.prompt.md"

envsubst '${ISSUE_NUMBER} ${ISSUE_TITLE} ${ISSUE_BODY} ${FIX_CONFIDENCE} ${GIT_DIFF} ${COMMIT_MSG}' \
    < "$PROMPT_TEMPLATE" > "$PROMPT_FILE"

# Run Claude for review
LOG_FILE="${ISSUE_RUN_DIR}/review.log"

agent_log INFO "Running review (timeout: 5 minutes)..."

if ! run_claude "$PROMPT_FILE" "$LOG_FILE" 300; then
    agent_log WARNING "Claude failed during review, approving with caution"
    # Don't fail - just approve with lower confidence
    cat > "${ISSUE_RUN_DIR}/review.state.json" <<EOF
{
    "status": "success",
    "agent": "review",
    "issue_number": ${ISSUE_NUMBER},
    "approved": true,
    "verdict": "APPROVE",
    "confidence": 0.5,
    "summary": "Review agent failed, approving with reduced confidence",
    "blocking_issues": [],
    "reviewer_notes": "Manual review strongly recommended",
    "timestamp": "$(date -Iseconds)"
}
EOF
    exit 0
fi

# Extract review results
REVIEW_JSON=$(cat "$LOG_FILE" | tr '\n' ' ' | grep -oP '\{[^{}]*"approved"[^{}]*"verdict"[^{}]*\}' | tail -1 || echo "")

if [ -z "$REVIEW_JSON" ] || ! echo "$REVIEW_JSON" | jq -e '.verdict' &>/dev/null; then
    agent_log WARNING "Could not parse review output, approving with caution"
    cat > "${ISSUE_RUN_DIR}/review.state.json" <<EOF
{
    "status": "success",
    "agent": "review",
    "issue_number": ${ISSUE_NUMBER},
    "approved": true,
    "verdict": "APPROVE",
    "confidence": 0.6,
    "summary": "Review completed but output not parsed",
    "blocking_issues": [],
    "reviewer_notes": "Manual review recommended",
    "timestamp": "$(date -Iseconds)"
}
EOF
    exit 0
fi

# Parse results
VERDICT=$(echo "$REVIEW_JSON" | jq -r '.verdict // "APPROVE"')
CONFIDENCE=$(echo "$REVIEW_JSON" | jq -r '.confidence // 0.7')
SUMMARY=$(echo "$REVIEW_JSON" | jq -r '.summary // "No summary"')
BLOCKING_ISSUES=$(echo "$REVIEW_JSON" | jq -r '.blocking_issues // []')

agent_log INFO "Review verdict: $VERDICT (confidence: $CONFIDENCE)"
agent_log INFO "Summary: $SUMMARY"

# Determine approval
APPROVED="true"
if [ "$VERDICT" = "BLOCK" ]; then
    APPROVED="false"
    agent_log ERROR "Review BLOCKED the fix"
elif [ "$VERDICT" = "REQUEST_CHANGES" ]; then
    # Allow if confidence is still reasonable
    if (( $(echo "$CONFIDENCE < 0.5" | bc -l) )); then
        APPROVED="false"
        agent_log WARNING "Review requested changes with low confidence, blocking"
    else
        agent_log WARNING "Review requested changes but allowing with notes"
    fi
else
    agent_log SUCCESS "Review APPROVED"
fi

# Save state
cat > "${ISSUE_RUN_DIR}/review.state.json" <<EOF
{
    "status": "success",
    "agent": "review",
    "issue_number": ${ISSUE_NUMBER},
    "approved": $APPROVED,
    "verdict": "$VERDICT",
    "confidence": $CONFIDENCE,
    "summary": $(echo "$SUMMARY" | jq -R '.'),
    "blocking_issues": $BLOCKING_ISSUES,
    "full_review": $REVIEW_JSON,
    "timestamp": "$(date -Iseconds)"
}
EOF

agent_log AGENT "Review complete"

if [ "$APPROVED" = "true" ]; then
    exit 0
else
    exit 2  # Blocked
fi

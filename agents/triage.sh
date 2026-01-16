#!/bin/bash
#
# triage.sh - Triage Agent
#
# Analyzes an issue and classifies whether it can be auto-fixed.
#
# Required environment:
#   ISSUE_RUN_DIR - Directory for this issue's run data
#   ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY, ISSUE_LABELS - Issue details
#   SCRIPT_DIR - Root directory of the fix-all-the-things project
#
# Outputs:
#   ${ISSUE_RUN_DIR}/triage.state.json - Classification and analysis
#   ${ISSUE_RUN_DIR}/triage.log - Full Claude output
#

set -euo pipefail

AGENT_NAME="TRIAGE"

# Source common utilities
source "${SCRIPT_DIR}/agents/common.sh"

agent_log AGENT "Starting triage analysis for issue #${ISSUE_NUMBER}"

# Build the prompt from template
PROMPT_TEMPLATE="${SCRIPT_DIR}/prompts/triage.md"
PROMPT_FILE="${ISSUE_RUN_DIR}/triage.prompt.md"

# Substitute variables in prompt template
envsubst '${ISSUE_NUMBER} ${ISSUE_TITLE} ${ISSUE_BODY} ${ISSUE_LABELS}' \
    < "$PROMPT_TEMPLATE" > "$PROMPT_FILE"

# Run Claude
LOG_FILE="${ISSUE_RUN_DIR}/triage.log"

if ! run_claude "$PROMPT_FILE" "$LOG_FILE" 180; then
    agent_log ERROR "Claude failed during triage"
    save_agent_state "${ISSUE_RUN_DIR}/triage.state.json" \
        "status=failed" \
        "error=Claude execution failed"
    exit 1
fi

# Extract JSON output from Claude's response
agent_log INFO "Extracting triage results..."

# Look for JSON in the log file - Claude outputs it in the assistant messages
TRIAGE_JSON=$(grep -a '"classification"' "$LOG_FILE" | tail -1 | grep -o '{[^}]*}' | head -1 || echo "")

# Try harder - look for the full JSON block
if [ -z "$TRIAGE_JSON" ] || ! echo "$TRIAGE_JSON" | jq -e '.classification' &>/dev/null; then
    # Extract from text content in stream
    TRIAGE_JSON=$(cat "$LOG_FILE" | tr '\n' ' ' | grep -oP '\{[^{}]*"classification"[^{}]*\}' | tail -1 || echo "")
fi

if [ -z "$TRIAGE_JSON" ] || ! echo "$TRIAGE_JSON" | jq -e '.classification' &>/dev/null; then
    agent_log WARNING "Could not extract structured triage result, defaulting to NEEDS_CLARIFICATION"
    TRIAGE_JSON='{
        "classification": "NEEDS_CLARIFICATION",
        "confidence": 0.3,
        "clarity_score": 0.3,
        "feasibility_score": 0.3,
        "summary": "Could not parse issue automatically",
        "reasoning": "Triage agent failed to produce structured output",
        "risks": ["Unknown issue structure"],
        "suggested_approach": "Manual review required",
        "questions_if_unclear": ["What is the expected behavior?"],
        "estimated_complexity": "unknown"
    }'
fi

# Parse results
CLASSIFICATION=$(echo "$TRIAGE_JSON" | jq -r '.classification // "NEEDS_CLARIFICATION"')
CONFIDENCE=$(echo "$TRIAGE_JSON" | jq -r '.confidence // 0.5')
SUMMARY=$(echo "$TRIAGE_JSON" | jq -r '.summary // "No summary"')
COMPLEXITY=$(echo "$TRIAGE_JSON" | jq -r '.estimated_complexity // "unknown"')

agent_log SUCCESS "Classification: $CLASSIFICATION (confidence: $CONFIDENCE)"
agent_log INFO "Summary: $SUMMARY"
agent_log INFO "Complexity: $COMPLEXITY"

# Determine if we should proceed
SHOULD_PROCEED="false"
if [ "$CLASSIFICATION" = "FIXABLE_CODE" ] || [ "$CLASSIFICATION" = "FIXABLE_CONFIG" ]; then
    if (( $(echo "$CONFIDENCE >= 0.6" | bc -l) )); then
        SHOULD_PROCEED="true"
        agent_log SUCCESS "Issue approved for auto-fix"
    else
        agent_log WARNING "Confidence too low to proceed automatically"
    fi
else
    agent_log INFO "Issue not suitable for auto-fix: $CLASSIFICATION"
fi

# Save state
cat > "${ISSUE_RUN_DIR}/triage.state.json" <<EOF
{
    "status": "success",
    "agent": "triage",
    "issue_number": ${ISSUE_NUMBER},
    "classification": "$CLASSIFICATION",
    "confidence": $CONFIDENCE,
    "should_proceed": $SHOULD_PROCEED,
    "summary": $(echo "$SUMMARY" | jq -R '.'),
    "complexity": "$COMPLEXITY",
    "full_analysis": $TRIAGE_JSON,
    "timestamp": "$(date -Iseconds)"
}
EOF

agent_log AGENT "Triage complete"

# Exit with appropriate code
if [ "$SHOULD_PROCEED" = "true" ]; then
    exit 0
else
    exit 2  # Special code for "skip"
fi

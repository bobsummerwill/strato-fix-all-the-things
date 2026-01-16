#!/bin/bash
#
# research.sh - Research Agent
#
# Deeply explores the codebase to understand everything needed to fix an issue.
# Does NOT make any changes - only gathers information.
#
# Required environment:
#   ISSUE_RUN_DIR - Directory for this issue's run data
#   ISSUE_NUMBER, ISSUE_TITLE, ISSUE_BODY - Issue details
#   SCRIPT_DIR - Root directory of the fix-all-the-things project
#   PROJECT_DIR - The target repository to research
#
# Requires:
#   triage.state.json - Output from triage agent
#
# Outputs:
#   ${ISSUE_RUN_DIR}/research.state.json - Research findings
#   ${ISSUE_RUN_DIR}/research.log - Full Claude output
#

set -euo pipefail

AGENT_NAME="RESEARCH"

# Source common utilities
source "${SCRIPT_DIR}/agents/common.sh"

agent_log AGENT "Starting research for issue #${ISSUE_NUMBER}"

# Verify triage agent ran successfully
if ! check_previous_agent "triage"; then
    exit 1
fi

# Load triage results
TRIAGE_SUMMARY=$(load_agent_state "${ISSUE_RUN_DIR}/triage.state.json" "summary")
SUGGESTED_APPROACH=$(jq -r '.full_analysis.suggested_approach // "No approach suggested"' "${ISSUE_RUN_DIR}/triage.state.json")

agent_log INFO "Triage summary: $TRIAGE_SUMMARY"

# Build the prompt from template
PROMPT_TEMPLATE="${SCRIPT_DIR}/prompts/research.md"
PROMPT_FILE="${ISSUE_RUN_DIR}/research.prompt.md"

# Export variables for envsubst
export TRIAGE_SUMMARY
export SUGGESTED_APPROACH

envsubst '${ISSUE_NUMBER} ${ISSUE_TITLE} ${ISSUE_BODY} ${TRIAGE_SUMMARY} ${SUGGESTED_APPROACH}' \
    < "$PROMPT_TEMPLATE" > "$PROMPT_FILE"

# Change to project directory for research
cd "$PROJECT_DIR"

# Run Claude with longer timeout for research
LOG_FILE="${ISSUE_RUN_DIR}/research.log"

agent_log INFO "Beginning codebase exploration (timeout: 10 minutes)..."

if ! run_claude "$PROMPT_FILE" "$LOG_FILE" 600; then
    agent_log ERROR "Claude failed during research"
    save_agent_state "${ISSUE_RUN_DIR}/research.state.json" \
        "status=failed" \
        "error=Claude execution failed"
    exit 1
fi

# Extract JSON output
agent_log INFO "Extracting research findings..."

# Try to find the research JSON in the output
RESEARCH_JSON=$(cat "$LOG_FILE" | tr '\n' ' ' | grep -oP '\{[^{}]*"research_complete"[^{}]*("files_to_modify"|"root_cause")[^}]*\}' | tail -1 || echo "")

# More aggressive extraction - look for any substantial JSON
if [ -z "$RESEARCH_JSON" ] || ! echo "$RESEARCH_JSON" | jq -e '.research_complete' &>/dev/null; then
    # Try to find JSON blocks in the log
    RESEARCH_JSON=$(grep -a 'research_complete' "$LOG_FILE" | grep -o '{.*}' | tail -1 || echo "")
fi

if [ -z "$RESEARCH_JSON" ] || ! echo "$RESEARCH_JSON" | jq -e '.research_complete' &>/dev/null; then
    agent_log WARNING "Could not extract structured research result"

    # Create minimal state indicating research was attempted but inconclusive
    cat > "${ISSUE_RUN_DIR}/research.state.json" <<EOF
{
    "status": "partial",
    "agent": "research",
    "issue_number": ${ISSUE_NUMBER},
    "research_complete": false,
    "confidence": 0.3,
    "error": "Could not extract structured research findings",
    "raw_log_available": true,
    "timestamp": "$(date -Iseconds)"
}
EOF
    agent_log WARNING "Research incomplete - proceeding with caution"
    exit 0  # Still allow fix agent to try
fi

# Parse and validate research
CONFIDENCE=$(echo "$RESEARCH_JSON" | jq -r '.confidence // 0.5')
FILES_COUNT=$(echo "$RESEARCH_JSON" | jq -r '.files_to_modify | length // 0')
ROOT_CAUSE=$(echo "$RESEARCH_JSON" | jq -r '.root_cause.description // "Unknown"')

agent_log SUCCESS "Research complete (confidence: $CONFIDENCE)"
agent_log INFO "Root cause: $ROOT_CAUSE"
agent_log INFO "Files to modify: $FILES_COUNT"

# Save state with full research
cat > "${ISSUE_RUN_DIR}/research.state.json" <<EOF
{
    "status": "success",
    "agent": "research",
    "issue_number": ${ISSUE_NUMBER},
    "research_complete": true,
    "confidence": $CONFIDENCE,
    "files_to_modify_count": $FILES_COUNT,
    "root_cause_summary": $(echo "$ROOT_CAUSE" | jq -R '.'),
    "findings": $RESEARCH_JSON,
    "timestamp": "$(date -Iseconds)"
}
EOF

agent_log AGENT "Research complete"
exit 0

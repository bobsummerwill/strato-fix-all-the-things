#!/bin/bash
#
# run.sh - STRATO Fix All The Things
#
# Multi-agent system for automatically fixing GitHub issues using Claude Code.
#
# Pipeline stages:
#   1. TRIAGE  - Classify if issue is fixable
#   2. RESEARCH - Deep codebase exploration
#   3. FIX     - Implement changes
#   4. REVIEW  - Self-review before PR
#
# Usage:
#   ./run.sh [--project-dir <path>] <issue_number> [issue_number2] ...
#   ./run.sh 5960
#   ./run.sh 5960 5961 5962
#   ./run.sh --project-dir ~/custom/path/strato-platform 5960
#
# Requirements:
#   Tools:
#     - Claude Code CLI (claude) - npm install -g @anthropic-ai/claude-code
#     - GitHub CLI (gh) - https://cli.github.com/
#     - git, jq, bc, timeout, envsubst
#
#   Environment Variables:
#     - GH_TOKEN - GitHub personal access token (scopes: repo, workflow)
#

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

REPO="blockapps/strato-platform"
BASE_BRANCH="develop"
BRANCH_PREFIX="claude-auto-fix"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default project directory
DEFAULT_PROJECT_DIR="$(cd "${SCRIPT_DIR}/../strato-platform" 2>/dev/null && pwd || echo "")"
PROJECT_DIR="${DEFAULT_PROJECT_DIR}"

# Source .env if exists
if [ -f "${SCRIPT_DIR}/.env" ]; then
    echo "Loading environment from ${SCRIPT_DIR}/.env"
    set -a
    source "${SCRIPT_DIR}/.env"
    set +a
fi

# ============================================================================
# Parse Arguments
# ============================================================================

ISSUE_NUMBERS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --help|-h)
            cat <<EOF
Usage: $0 [--project-dir <path>] <issue_number> [issue_number2] ...

Multi-agent pipeline for automatic issue fixing:
  1. TRIAGE  - Classify if issue is AI-fixable
  2. RESEARCH - Explore codebase, understand root cause
  3. FIX     - Implement minimal changes
  4. REVIEW  - Self-review before creating PR

Options:
  --project-dir <path>  Path to strato-platform repository
  --help, -h            Show this help

Environment:
  GH_TOKEN              GitHub personal access token (required)

Examples:
  $0 5960                    # Fix single issue
  $0 5960 5961 5962          # Fix multiple issues
EOF
            exit 0
            ;;
        *)
            ISSUE_NUMBERS+=("$1")
            shift
            ;;
    esac
done

if [ ${#ISSUE_NUMBERS[@]} -eq 0 ]; then
    echo "ERROR: No issue numbers provided"
    echo "Usage: $0 <issue_number> [issue_number2] ..."
    exit 1
fi

# ============================================================================
# Validation
# ============================================================================

# Check GH_TOKEN
if [ -z "${GH_TOKEN:-}" ]; then
    echo "ERROR: GH_TOKEN not set"
    echo "Create .env file with: GH_TOKEN=your_token"
    exit 1
fi

# Check required tools
for cmd in git jq bc timeout envsubst claude gh; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "ERROR: $cmd not found"
        exit 1
    fi
done

# Check project directory
if [ -z "$PROJECT_DIR" ] || [ ! -d "$PROJECT_DIR" ]; then
    echo "ERROR: Project directory not found: ${PROJECT_DIR:-<not set>}"
    exit 1
fi

cd "$PROJECT_DIR" || exit 1

if ! git rev-parse --is-inside-work-tree &>/dev/null; then
    echo "ERROR: Not a git repository: $PROJECT_DIR"
    exit 1
fi

# ============================================================================
# Colors and Logging
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()    { echo -e "\n${CYAN}════════════════════════════════════════${NC}\n${CYAN}  $1${NC}\n${CYAN}════════════════════════════════════════${NC}\n"; }

# ============================================================================
# Setup
# ============================================================================

log_step "STRATO Fix All The Things - Multi-Agent Pipeline"

log_info "Repository: $REPO"
log_info "Project: $PROJECT_DIR"
log_info "Issues to process: ${#ISSUE_NUMBERS[@]}"

# Create runs directory
RUNS_DIR="${SCRIPT_DIR}/runs"
RUN_TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
mkdir -p "$RUNS_DIR"

# Track results
declare -a SUCCESSFUL_ISSUES=()
declare -a FAILED_ISSUES=()
declare -a SKIPPED_ISSUES=()

# ============================================================================
# Process Each Issue
# ============================================================================

for ISSUE_NUMBER in "${ISSUE_NUMBERS[@]}"; do
    log_step "Issue #${ISSUE_NUMBER} ($(( ${#SUCCESSFUL_ISSUES[@]} + ${#FAILED_ISSUES[@]} + ${#SKIPPED_ISSUES[@]} + 1 ))/${#ISSUE_NUMBERS[@]})"

    BRANCH_NAME="${BRANCH_PREFIX}-${ISSUE_NUMBER}"

    (
        set -e

        # ──────────────────────────────────────────────────────────────────────
        # Fetch Issue
        # ──────────────────────────────────────────────────────────────────────

        log_info "Fetching issue #${ISSUE_NUMBER}..."

        ISSUE_JSON=$(gh issue view "$ISSUE_NUMBER" --repo "$REPO" --json title,body,labels 2>&1) || {
            log_error "Failed to fetch issue"
            exit 1
        }

        ISSUE_TITLE=$(echo "$ISSUE_JSON" | jq -r '.title')
        ISSUE_BODY=$(echo "$ISSUE_JSON" | jq -r '.body // "No description"')
        ISSUE_LABELS=$(echo "$ISSUE_JSON" | jq -r '.labels[].name // empty' | tr '\n' ', ' | sed 's/,$//')

        log_success "Issue: ${ISSUE_TITLE}"
        log_info "Labels: ${ISSUE_LABELS:-none}"

        # Create run directory
        ISSUE_RUN_DIR="${RUNS_DIR}/${RUN_TIMESTAMP}-issue-${ISSUE_NUMBER}"
        mkdir -p "$ISSUE_RUN_DIR"
        echo "$ISSUE_JSON" > "${ISSUE_RUN_DIR}/issue.json"

        # ──────────────────────────────────────────────────────────────────────
        # Prepare Git
        # ──────────────────────────────────────────────────────────────────────

        log_info "Preparing git branch..."

        git fetch origin --quiet
        git checkout "$BASE_BRANCH" --quiet

        # Ensure clean state
        if [ -n "$(git status --porcelain)" ]; then
            log_error "Working tree not clean"
            git status --short
            exit 1
        fi

        git reset --hard "origin/$BASE_BRANCH" --quiet
        log_success "Synced to origin/$BASE_BRANCH"

        # Clean up existing branch/PR
        EXISTING_PR=$(gh pr view "$BRANCH_NAME" --repo "$REPO" --json number -q '.number' 2>/dev/null || echo "")
        if [ -n "$EXISTING_PR" ]; then
            log_warning "Closing existing PR #${EXISTING_PR}..."
            gh pr close "$EXISTING_PR" --repo "$REPO" --delete-branch 2>/dev/null || true
        fi

        git branch -D "$BRANCH_NAME" 2>/dev/null || true
        git push origin --delete "$BRANCH_NAME" 2>/dev/null || true

        git checkout -b "$BRANCH_NAME"
        log_success "Created branch $BRANCH_NAME"

        # ──────────────────────────────────────────────────────────────────────
        # Run Multi-Agent Pipeline
        # ──────────────────────────────────────────────────────────────────────

        log_info "Starting multi-agent pipeline..."

        # Export environment for agents
        export ISSUE_RUN_DIR
        export ISSUE_NUMBER
        export ISSUE_TITLE
        export ISSUE_BODY
        export ISSUE_LABELS
        export SCRIPT_DIR
        export PROJECT_DIR
        export BASE_BRANCH

        # Run orchestrator
        chmod +x "${SCRIPT_DIR}/agents/orchestrator.sh"

        set +e
        bash "${SCRIPT_DIR}/agents/orchestrator.sh"
        PIPELINE_EXIT=$?
        set -e

        if [ $PIPELINE_EXIT -eq 2 ]; then
            log_warning "Pipeline skipped this issue"

            # Get reason from pipeline state
            if [ -f "${ISSUE_RUN_DIR}/pipeline.state.json" ]; then
                SKIP_REASON=$(jq -r '.failure_reason // "Unknown reason"' "${ISSUE_RUN_DIR}/pipeline.state.json")
                log_info "Reason: $SKIP_REASON"

                # Comment on issue
                gh issue comment "$ISSUE_NUMBER" --repo "$REPO" --body "🤖 Auto-fix attempted but skipped.

**Reason:** $SKIP_REASON

The multi-agent pipeline (Triage → Research → Fix → Review) determined this issue cannot be automatically fixed at this time.

---
*Generated with [Claude Code](https://claude.ai/claude-code)*" 2>/dev/null || true
            fi

            git checkout "$BASE_BRANCH" --quiet
            git branch -D "$BRANCH_NAME" 2>/dev/null || true
            exit 2
        elif [ $PIPELINE_EXIT -ne 0 ]; then
            log_error "Pipeline failed"
            git checkout "$BASE_BRANCH" --quiet
            git branch -D "$BRANCH_NAME" 2>/dev/null || true
            exit 1
        fi

        # ──────────────────────────────────────────────────────────────────────
        # Verify Changes
        # ──────────────────────────────────────────────────────────────────────

        COMMITS_AHEAD=$(git rev-list --count "${BASE_BRANCH}..HEAD")
        if [ "$COMMITS_AHEAD" -eq 0 ]; then
            log_warning "No commits made"
            git checkout "$BASE_BRANCH" --quiet
            git branch -D "$BRANCH_NAME" 2>/dev/null || true
            exit 2
        fi

        log_success "Branch has ${COMMITS_AHEAD} commit(s)"

        # ──────────────────────────────────────────────────────────────────────
        # Create PR
        # ──────────────────────────────────────────────────────────────────────

        log_info "Pushing and creating PR..."
        git push -u origin "$BRANCH_NAME" --force

        # Get pipeline confidence
        AGGREGATE_CONF=$(jq -r '.aggregate_confidence // 0.7' "${ISSUE_RUN_DIR}/pipeline.state.json" 2>/dev/null || echo "0.7")
        REVIEW_VERDICT=$(jq -r '.review_verdict // "APPROVE"' "${ISSUE_RUN_DIR}/pipeline.state.json" 2>/dev/null || echo "APPROVE")

        # Determine labels
        PR_LABELS="ai-fixes-experimental"
        if (( $(echo "$AGGREGATE_CONF < 0.6" | bc -l) )); then
            PR_LABELS="${PR_LABELS},low-confidence"
        elif (( $(echo "$AGGREGATE_CONF >= 0.8" | bc -l) )); then
            PR_LABELS="${PR_LABELS},high-confidence"
        fi

        # Build PR body
        COMMIT_MSG=$(git log -1 --format="%B")
        TRIAGE_SUMMARY=$(jq -r '.summary // "N/A"' "${ISSUE_RUN_DIR}/triage.state.json" 2>/dev/null || echo "N/A")
        RESEARCH_ROOT_CAUSE=$(jq -r '.root_cause_summary // "See research log"' "${ISSUE_RUN_DIR}/research.state.json" 2>/dev/null || echo "N/A")
        REVIEW_SUMMARY=$(jq -r '.summary // "N/A"' "${ISSUE_RUN_DIR}/review.state.json" 2>/dev/null || echo "N/A")

        PR_BODY="## Summary
This PR addresses issue #${ISSUE_NUMBER}.

## Multi-Agent Pipeline Results

| Agent | Result |
|-------|--------|
| **Triage** | ${TRIAGE_SUMMARY} |
| **Research** | Root cause: ${RESEARCH_ROOT_CAUSE} |
| **Review** | ${REVIEW_SUMMARY} |
| **Confidence** | ${AGGREGATE_CONF} |

## Issue
**${ISSUE_TITLE}**

${ISSUE_BODY:0:800}

## Changes
\`\`\`
${COMMIT_MSG}
\`\`\`

---
🤖 Generated with [Claude Code](https://claude.ai/claude-code) using multi-agent pipeline
"

        PR_URL=$(gh pr create \
            --repo "$REPO" \
            --base "$BASE_BRANCH" \
            --head "$BRANCH_NAME" \
            --title "Fix #${ISSUE_NUMBER}: ${ISSUE_TITLE}" \
            --body "$PR_BODY" \
            --label "$PR_LABELS" \
            --draft 2>&1) || {
            PR_URL=$(gh pr view "$BRANCH_NAME" --repo "$REPO" --json url -q '.url' 2>/dev/null || echo "unknown")
        }

        log_success "PR created: ${PR_URL}"

        # Save result
        cat > "${ISSUE_RUN_DIR}/result.json" <<EOF
{
    "issue_number": ${ISSUE_NUMBER},
    "status": "success",
    "pr_url": "${PR_URL}",
    "branch": "${BRANCH_NAME}",
    "aggregate_confidence": ${AGGREGATE_CONF},
    "commits": ${COMMITS_AHEAD},
    "timestamp": "$(date -Iseconds)"
}
EOF

        # Comment on issue
        gh issue comment "$ISSUE_NUMBER" --repo "$REPO" --body "🤖 Auto-fix PR created: ${PR_URL}

**Pipeline confidence:** ${AGGREGATE_CONF}
**Review verdict:** ${REVIEW_VERDICT}

This fix was generated using a multi-agent pipeline (Triage → Research → Fix → Review).

---
*Generated with [Claude Code](https://claude.ai/claude-code)*" 2>/dev/null || true

        git checkout "$BASE_BRANCH" --quiet

    ) && {
        SUCCESSFUL_ISSUES+=("$ISSUE_NUMBER")
        log_success "Issue #${ISSUE_NUMBER} completed"
    } || {
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 2 ]; then
            SKIPPED_ISSUES+=("$ISSUE_NUMBER")
            log_warning "Issue #${ISSUE_NUMBER} skipped"
        else
            FAILED_ISSUES+=("$ISSUE_NUMBER")
            log_error "Issue #${ISSUE_NUMBER} failed"
        fi
        git checkout "$BASE_BRANCH" --quiet 2>/dev/null || true
    }

    echo ""
done

# ============================================================================
# Summary
# ============================================================================

log_step "Summary"

echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}  Pipeline Complete${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""

[ ${#SUCCESSFUL_ISSUES[@]} -gt 0 ] && log_success "Successful (${#SUCCESSFUL_ISSUES[@]}): ${SUCCESSFUL_ISSUES[*]}"
[ ${#SKIPPED_ISSUES[@]} -gt 0 ] && log_warning "Skipped (${#SKIPPED_ISSUES[@]}): ${SKIPPED_ISSUES[*]}"
[ ${#FAILED_ISSUES[@]} -gt 0 ] && log_error "Failed (${#FAILED_ISSUES[@]}): ${FAILED_ISSUES[*]}"

echo ""
log_info "Total: ${#ISSUE_NUMBERS[@]} issues processed"
log_info "Run logs: ${RUNS_DIR}/${RUN_TIMESTAMP}-*"
log_warning "Remember to review PRs before merging!"

[ ${#FAILED_ISSUES[@]} -gt 0 ] && exit 1
exit 0

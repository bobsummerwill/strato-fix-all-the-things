# STRATO Fix All The Things

A multi-agent system for automatically fixing GitHub issues using Claude Code.

## Architecture

```
+-------------------------------------------------------------------+
|                      MULTI-AGENT PIPELINE                         |
+-------------------------------------------------------------------+
|                                                                   |
|   +----------+     +----------+     +-------------------+         |
|   |  TRIAGE  | --> | RESEARCH | --> |   FIX <--> REVIEW |         |
|   +----------+     +----------+     |   (up to 3 loops) |         |
|        |                |           +-------------------+         |
|        v                v                    |                    |
|    Classify         Explore              Implement                |
|    issue            codebase             & iterate                |
|                                                                   |
+-------------------------------------------------------------------+
```

### Pipeline Stages

| Agent | Purpose | Key Outputs |
|-------|---------|-------------|
| **Triage** | Classify if issue is AI-fixable | Classification, confidence, complexity |
| **Research** | Deep codebase exploration | Root cause, files to modify, patterns |
| **Fix** | Implement minimal changes | File changes, confidence assessment |
| **Review** | Self-review the fix | APPROVE / REQUEST_CHANGES / BLOCK |

### Fix-Review Loop

If the review agent returns `REQUEST_CHANGES`, the pipeline loops back to revision:
1. Fix agent receives review feedback (concerns, suggestions)
2. Fix agent revises the implementation
3. Review agent re-evaluates
4. Repeat up to 3 times, then block if still not approved

### Agent Details

#### 1. Triage Agent
Classifies issues into categories:
- `FIXABLE_CODE` - Clear bug fixable with code changes
- `FIXABLE_CONFIG` - Configuration/environment changes
- `NEEDS_CLARIFICATION` - Issue too vague
- `NEEDS_HUMAN` - Requires human judgment
- `ALREADY_DONE` - Issue appears resolved
- `OUT_OF_SCOPE` - Not suitable for AI fixing

Only `FIXABLE_CODE` and `FIXABLE_CONFIG` proceed to the next stage.

#### 2. Research Agent
Explores the codebase WITHOUT making changes:
- Locates all relevant files
- Maps architecture and data flow
- Identifies root cause
- Documents patterns to follow
- Notes risks and testing recommendations

#### 3. Fix Agent
Implements changes based on research:
- Executes focused changes
- Follows identified patterns
- Does NOT commit (pipeline handles commits after review)
- Reports confidence scores

#### 4. Review Agent
Self-reviews the fix before PR creation:
- Checks correctness, completeness, safety
- Validates style and scope
- Can block problematic fixes
- Provides concerns and suggestions for revision

## Quick Start

1. **Setup environment:**
```bash
cp .env.sample .env
# Edit .env with your settings
```

2. **Install prerequisites:**
```bash
npm install -g @anthropic-ai/claude-code
# Ensure gh and git are available
```

3. **Run on issues:**
```bash
./run.py 5960              # Single issue
./run.py 5960 5961 5962    # Multiple issues
./run.py 5960 --test-command "make test"  # Run verification tests
```

## Configuration

Environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_REPO` | Repository (owner/repo) | `blockapps/strato-platform` |
| `PROJECT_DIR` | Path to local repo clone | Required |
| `TOOL_CLONE_DIR` | Path to tool-managed clone | `.tool-clone` |
| `BASE_BRANCH` | Base branch for PRs | `develop` |
| `TEST_COMMAND` | Command to run for verification tests | (unset) |
| `TRIAGE_TIMEOUT` | Triage agent timeout (seconds) | `120` |
| `RESEARCH_TIMEOUT` | Research agent timeout (seconds) | `300` |
| `FIX_TIMEOUT` | Fix agent timeout (seconds) | `300` |
| `REVIEW_TIMEOUT` | Review agent timeout (seconds) | `180` |

## Run Output

Each run creates detailed logs in `runs/`:

```
runs/2026-01-15_12-00-00-issue-5960/
├── issue.json              # Original issue data
├── triage.prompt.md        # Prompt sent to triage agent
├── triage.log              # Full triage output
├── triage.state.json       # Classification result
├── research.prompt.md      # Prompt sent to research agent
├── research.log            # Full research output
├── research.state.json     # Research findings
├── fix.prompt.md           # Prompt sent to fix agent
├── fix.log                 # Full fix output
├── fix.state.json          # Fix result
├── review.prompt.md        # Prompt sent to review agent
├── review.log              # Full review output
├── review.state.json       # Review verdict
├── fix-revision-2.prompt.md  # (if revision needed)
├── fix-revision-2.log        # (if revision needed)
├── fix-revision-2.state.json # (if revision needed)
└── pipeline.state.json     # Aggregate pipeline results
```

Aggregate metrics are appended to `runs/metrics.jsonl` for benchmarking across runs.

## Confidence Scoring

Each agent reports confidence (0.0-1.0). The pipeline computes an aggregate:

```
Aggregate = Triage(0.15) + Research(0.20) + Fix(0.35) + Review(0.30)
```

## File Structure

```
strato-fix-all-the-things/
├── run.py                 # Main entry point
├── src/
│   ├── agents/
│   │   ├── base.py        # Base agent class
│   │   ├── triage.py      # Triage agent
│   │   ├── research.py    # Research agent
│   │   ├── fix.py         # Fix agent
│   │   └── review.py      # Review agent
│   ├── claude_runner.py   # Claude Code CLI wrapper
│   ├── config.py          # Configuration loader
│   ├── github_client.py   # GitHub API (via gh CLI)
│   ├── git_ops.py         # Git operations
│   ├── models.py          # Data models
│   └── pipeline.py        # Pipeline orchestrator
├── prompts/
│   ├── triage.md          # Triage prompt template
│   ├── research.md        # Research prompt template
│   ├── fix.md             # Fix prompt template
│   ├── fix-revision.md    # Fix revision prompt template
│   └── review.md          # Review prompt template
├── runs/                  # Run logs (gitignored)
├── .env                   # Environment (gitignored)
├── .env.sample            # Environment template
└── README.md
```

## How It Works

1. **Fetch issue** from GitHub
2. **Triage** classifies if it's AI-fixable
3. **Research** explores codebase, identifies root cause
4. **Fix** implements changes based on research
5. **Review** self-checks the fix
   - If `APPROVE`: proceed to PR
   - If `REQUEST_CHANGES`: loop back to fix (up to 3 times)
   - If `BLOCK`: stop and comment on issue
6. **Commit** changes with detailed message
7. **Create PR** as draft with `ai-fixes-experimental` label
8. **Comment on issue** linking to PR with details

If any stage fails or blocks, the pipeline stops and comments on the issue explaining why.

## Safety Features

- Creates PRs as **drafts** (not ready for review)
- **Review agent** can block problematic fixes
- **Fix-review loop** allows self-correction (up to 3 attempts)
- `.env` files automatically excluded from commits
- Force-syncs to latest `origin/{base_branch}` before each issue
- Cleans up existing branches/PRs to avoid conflicts
- Comments on issues even when blocked/failed (for visibility)

## Requirements

- Python 3.11+
- [Claude Code CLI](https://www.npmjs.com/package/@anthropic-ai/claude-code) (`npm install -g @anthropic-ai/claude-code`)
- [GitHub CLI](https://cli.github.com/) (`gh`) - authenticated
- `git`

## License

Apache-2.0 — see [LICENSE](LICENSE)

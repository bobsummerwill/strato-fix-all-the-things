# Model Benchmark Backlog (Phase 2)

This backlog defines how to add GPT-5.3 Codex as a selectable model provider in SFATT and benchmark outcomes against Claude.

## Goal

Enable side-by-side model evaluation for issue fixing workflows without changing default safety behavior (draft PRs, review gate, issue comments).

## Scope

- Add provider abstraction for agent execution.
- Support at least two providers: Claude and GPT-5.3 Codex.
- Capture run metadata and benchmark metrics per issue.
- Keep existing pipeline behavior unchanged unless explicitly configured.

## Deliverables

### 1) Provider Abstraction

- Introduce a provider-agnostic runner interface:
  - `run(prompt, cwd, timeout_sec, log_file) -> RunnerResult`
- Move current Claude-only logic in `src/claude_runner.py` behind interface adapters.
- Add provider selection in config:
  - `MODEL_PROVIDER` (`claude` default, `codex` optional)
  - Optional per-stage overrides:
    - `TRIAGE_MODEL_PROVIDER`
    - `RESEARCH_MODEL_PROVIDER`
    - `FIX_MODEL_PROVIDER`
    - `REVIEW_MODEL_PROVIDER`

### 2) Codex Runner

- Add `src/codex_runner.py` implementing the same result contract as Claude runner.
- Support deterministic invocation parameters:
  - timeout
  - log capture
  - structured JSON extraction compatibility
- Ensure failures map to current pipeline error handling semantics.

### 3) Pipeline Wiring

- Update `src/pipeline.py` and agent classes to choose runner by configured provider.
- Preserve existing behavior when no provider is configured (Claude default).
- Add clear logging per stage:
  - provider name
  - model identifier (if available)

### 4) Benchmark Data Model

- Extend `src/models.py` with benchmark/run metadata structures.
- Persist metadata in `runs/<timestamp>-issue-<n>/pipeline.state.json`:
  - provider per stage
  - stage duration
  - stage status
  - stage confidence
  - iteration count
  - aggregate confidence
  - PR created (boolean)
  - final pipeline status

### 5) Benchmark Report Utility

- Add a small script (example: `scripts/benchmark_report.py`) to aggregate `runs/` results.
- CSV/JSON outputs should include:
  - issue number
  - provider/stage mapping
  - total runtime
  - success/skipped/failed/blocked
  - confidence breakdown
  - revision loop count
  - PR URL presence

### 6) README + Ops Notes

- Update `README.md` with:
  - provider config examples
  - benchmark workflow
  - interpretation caveats (confidence != correctness)
- Document safe rollout:
  - start with fix/review on Claude, research on Codex (or vice versa)
  - compare before switching defaults

## Suggested File Touches

- `src/claude_runner.py`
- `src/codex_runner.py` (new)
- `src/agents/base.py`
- `src/agents/triage.py`
- `src/agents/research.py`
- `src/agents/fix.py`
- `src/agents/review.py`
- `src/pipeline.py`
- `src/config.py`
- `src/models.py`
- `README.md`
- `scripts/benchmark_report.py` (new)

## Benchmark Methodology

- Use the same issue batch for both providers.
- Keep prompts, branch strategy, and base branch identical.
- Compare:
  - `PipelineStatus` outcome rate
  - review pass rate on first iteration
  - number of revision loops
  - elapsed time
  - human acceptance/merge rate (manual follow-up)

## Acceptance Criteria

- Provider is selectable without code changes.
- Both providers can complete at least one end-to-end issue run.
- Run artifacts contain benchmark metadata for all stages.
- A single command can produce an aggregate benchmark report across runs.

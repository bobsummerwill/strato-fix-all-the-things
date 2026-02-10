#!/usr/bin/env python3
"""Aggregate SFATT run metadata into benchmark reports."""

import argparse
import csv
import json
from pathlib import Path


def load_pipeline_state(run_dir: Path) -> dict | None:
    state_file = run_dir / "pipeline.state.json"
    if not state_file.exists():
        return None
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError:
        return None


def summarize_run(run_dir: Path, state: dict) -> dict:
    stage_metrics = state.get("stage_metrics", {})
    provider_config = state.get("provider_config", {})
    confidence_breakdown = state.get("confidence_breakdown", {})
    issue_number = state.get("issue_number")
    duration_seconds = state.get("duration_seconds", 0.0)
    status = state.get("status", "unknown")
    revisions = len([k for k in stage_metrics.keys() if k.startswith("fix-revision-")])

    pr_created = False
    issue_file = run_dir / "issue.json"
    if issue_file.exists():
        # PR creation still best inferred from success + output artifacts
        pr_created = status == "success"

    return {
        "run_dir": run_dir.name,
        "issue_number": issue_number,
        "status": status,
        "duration_seconds": duration_seconds,
        "aggregate_confidence": state.get("aggregate_confidence", 0.0),
        "triage_confidence": confidence_breakdown.get("triage", 0.0),
        "research_confidence": confidence_breakdown.get("research", 0.0),
        "fix_confidence": confidence_breakdown.get("fix", 0.0),
        "review_confidence": confidence_breakdown.get("review", 0.0),
        "default_provider": provider_config.get("default", ""),
        "triage_provider": provider_config.get("triage", ""),
        "research_provider": provider_config.get("research", ""),
        "fix_provider": provider_config.get("fix", ""),
        "review_provider": provider_config.get("review", ""),
        "revision_count": revisions,
        "pr_created": pr_created,
    }


def write_csv(rows: list[dict], output_file: Path) -> None:
    if not rows:
        output_file.write_text("")
        return
    fieldnames = list(rows[0].keys())
    with output_file.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate benchmark report from SFATT runs")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"), help="Path to SFATT runs directory")
    parser.add_argument("--json-out", type=Path, help="Optional JSON output file")
    parser.add_argument("--csv-out", type=Path, help="Optional CSV output file")
    args = parser.parse_args()

    if not args.runs_dir.exists():
        print(f"[ERROR] Runs directory does not exist: {args.runs_dir}")
        return 1

    rows: list[dict] = []
    for run_dir in sorted([p for p in args.runs_dir.iterdir() if p.is_dir()]):
        state = load_pipeline_state(run_dir)
        if not state:
            continue
        rows.append(summarize_run(run_dir, state))

    if args.json_out:
        args.json_out.write_text(json.dumps(rows, indent=2))
        print(f"[INFO] Wrote JSON report: {args.json_out}")

    if args.csv_out:
        write_csv(rows, args.csv_out)
        print(f"[INFO] Wrote CSV report: {args.csv_out}")

    print(f"[INFO] Runs analyzed: {len(rows)}")
    if rows:
        success_count = sum(1 for r in rows if r["status"] == "success")
        print(f"[INFO] Success rate: {success_count}/{len(rows)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

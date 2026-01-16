#!/usr/bin/env python3
"""
STRATO Fix All The Things - Main Entry Point

Usage:
    ./run.py <issue_numbers...>
    ./run.py 1234 5678 9012

Environment:
    GITHUB_TOKEN - GitHub personal access token
    GITHUB_REPO - Repository (default: blockapps/strato-platform)
    PROJECT_DIR - Path to local repository clone
    BASE_BRANCH - Base branch for PRs (default: develop)
"""

import argparse
import fcntl
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from src.config import Config
from src.git_ops import GitOps, GitError
from src.github_client import GitHubClient, GitHubError
from src.models import PipelineStatus
from src.pipeline import Pipeline


def ensure_tool_clone(config: Config) -> Path:
    """Ensure a reusable tool clone exists for running fixes."""
    tool_dir = config.tool_clone_dir
    git_dir = tool_dir / ".git"
    if tool_dir.exists():
        if not git_dir.exists():
            raise RuntimeError(f"Tool clone dir exists but is not a git repo: {tool_dir}")
        return tool_dir

    source_dir = config.project_dir
    if source_dir.exists() and (source_dir / ".git").exists():
        cmd = ["git", "clone", "--shared", str(source_dir), str(tool_dir)]
    else:
        repo_url = f"https://github.com/{config.github_repo}.git"
        cmd = ["git", "clone", repo_url, str(tool_dir)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create tool clone: {result.stderr.strip()}")

    return tool_dir


def acquire_work_lock(work_dir: Path):
    """Acquire an exclusive lock for the shared tool clone."""
    lock_path = work_dir / ".strato.lock"
    lock_file = open(lock_path, "a")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    return lock_file


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Auto-fix GitHub issues using AI agents")
    parser.add_argument("issues", nargs="+", type=int, help="Issue numbers to process")
    parser.add_argument("--env", type=Path, help="Path to .env file")
    args = parser.parse_args()

    # Load configuration
    script_dir = Path(__file__).parent.resolve()
    env_file = args.env or script_dir / ".env"

    try:
        config = Config.load(env_file)
    except ValueError as e:
        print(f"[ERROR] Configuration error: {e}")
        return 1

    print("=" * 50)
    print("  STRATO Fix All The Things - Multi-Agent Pipeline")
    print("=" * 50)
    try:
        work_dir = ensure_tool_clone(config)
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return 1
    config.work_dir = work_dir

    print(f"[INFO] Repository: {config.github_repo}")
    print(f"[INFO] Project: {config.project_dir}")
    print(f"[INFO] Work repo: {config.work_dir}")
    print(f"[INFO] Issues to process: {len(args.issues)}")

    lock_handle = acquire_work_lock(config.work_dir)
    try:
        # Initialize clients
        github = GitHubClient(config.github_repo)
        git = GitOps(config.work_dir)

        # Ensure runs directory exists
        config.runs_dir.mkdir(exist_ok=True)

        # Track results
        results = {"success": [], "failed": [], "skipped": []}

        for i, issue_num in enumerate(args.issues, 1):
            print()
            print("=" * 50)
            print(f"  Issue #{issue_num} ({i}/{len(args.issues)})")
            print("=" * 50)

            try:
                result = process_issue(config, github, git, issue_num)
                if result == PipelineStatus.SUCCESS:
                    results["success"].append(issue_num)
                elif result == PipelineStatus.SKIPPED:
                    results["skipped"].append(issue_num)
                else:
                    results["failed"].append(issue_num)
            except Exception as e:
                print(f"[ERROR] Unexpected error processing #{issue_num}: {e}")
                results["failed"].append(issue_num)

        # Print summary
        print()
        print("=" * 50)
        print("  Summary")
        print("=" * 50)

        if results["success"]:
            print(f"[SUCCESS] Completed ({len(results['success'])}): {', '.join(map(str, results['success']))}")
        if results["skipped"]:
            print(f"[WARNING] Skipped ({len(results['skipped'])}): {', '.join(map(str, results['skipped']))}")
        if results["failed"]:
            print(f"[ERROR] Failed ({len(results['failed'])}): {', '.join(map(str, results['failed']))}")

        print()
        print(f"[INFO] Total: {len(args.issues)} issues processed")
        print(f"[INFO] Run logs: {config.runs_dir}")

        return 0 if not results["failed"] else 1
    finally:
        lock_handle.close()


def cleanup_git_state(git: GitOps, base_branch: str, feature_branch: str) -> None:
    """Clean up git state - discard changes and return to base branch.

    Always performs destructive cleanup since we're working in a tool-managed
    clone, not the developer's actual repository.
    """
    try:
        # Discard any uncommitted changes
        git._run("checkout", "--", ".", check=False)
        git._run("clean", "-fd", check=False)
        # Return to base branch
        git._run("checkout", base_branch, check=False)
        # Delete feature branch
        git.delete_branch(feature_branch, force=True)
    except Exception:
        pass  # Best effort cleanup


def record_run_metrics(config: Config, state, run_dir: Path) -> None:
    """Append run metrics for benchmarking."""
    metrics_file = config.runs_dir / "metrics.jsonl"
    entry = {
        "issue_number": state.issue_number,
        "status": state.status.value,
        "aggregate_confidence": state.aggregate_confidence,
        "confidence_breakdown": state.confidence_breakdown,
        "duration_seconds": state.to_dict().get("duration_seconds"),
        "agents_completed": state.agents_completed,
        "run_dir": str(run_dir),
        "completed_at": state.completed_at.isoformat() if state.completed_at else None,
    }
    with open(metrics_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def process_issue(
    config: Config,
    github: GitHubClient,
    git: GitOps,
    issue_num: int,
) -> PipelineStatus:
    """Process a single issue through the pipeline.

    Always performs destructive git operations since we're working in a
    tool-managed clone, not the developer's actual repository.
    """
    # Fetch issue details
    print(f"[INFO] Fetching issue #{issue_num}...")
    try:
        issue = github.get_issue(issue_num)
    except GitHubError as e:
        print(f"[ERROR] Failed to fetch issue: {e}")
        return PipelineStatus.FAILED

    print(f"[SUCCESS] Issue: {issue.title}")
    print(f"[INFO] Labels: {', '.join(issue.labels) if issue.labels else 'none'}")

    # Create run directory
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = config.runs_dir / f"{timestamp}-issue-{issue_num}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save issue data
    with open(run_dir / "issue.json", "w") as f:
        json.dump({
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "labels": issue.labels,
            "url": issue.url,
        }, f, indent=2)

    # Prepare git branch
    branch_name = f"claude-auto-fix-{issue_num}"
    print(f"[INFO] Preparing git branch...")

    try:
        # Ensure clean state before starting (always clean since it's a tool clone)
        if git.is_dirty():
            git._run("checkout", "--", ".", check=False)
            git._run("clean", "-fd", check=False)

        # Fetch latest and hard reset to ensure we're at latest base branch
        print(f"[INFO] Fetching latest from origin...")
        git.fetch("origin")

        # Force checkout to base branch (in case we're on a different branch)
        git._run("checkout", config.base_branch, check=True)

        # Hard reset to match remote exactly (discards any local commits)
        git.reset_hard(f"origin/{config.base_branch}")
        print(f"[SUCCESS] Reset to origin/{config.base_branch}")

        # Close existing PR if any
        existing_pr = github.find_open_pr(branch_name)
        if existing_pr:
            print(f"[WARNING] Closing existing PR #{existing_pr.number}...")
            github.close_pr(existing_pr.number)

        # Delete existing branch (local and remote)
        if git.branch_exists(branch_name):
            git.delete_branch(branch_name, force=True)
        git.delete_remote_branch(branch_name)

        # Create new branch
        git.create_branch(branch_name)
        print(f"[SUCCESS] Created branch {branch_name}")

    except GitError as e:
        print(f"[ERROR] Git error: {e}")
        return PipelineStatus.FAILED

    # Run pipeline with cleanup on any failure
    try:
        print(f"[INFO] Starting multi-agent pipeline...")
        pipeline = Pipeline(config, issue, run_dir)
        state = pipeline.run()
        record_run_metrics(config, state, run_dir)

        # Handle results
        if state.status == PipelineStatus.SUCCESS:
            return handle_success(config, github, git, issue, branch_name, state, run_dir)
        elif state.status == PipelineStatus.SKIPPED:
            cleanup_git_state(git, config.base_branch, branch_name)
            return handle_skip(github, issue, state, run_dir)
        else:
            return handle_failure(
                github,
                git,
                issue,
                branch_name,
                state,
                config.base_branch,
                run_dir,
            )
    except Exception as e:
        # Unexpected error - clean up and re-raise
        print(f"[ERROR] Unexpected error: {e}")
        cleanup_git_state(git, config.base_branch, branch_name)
        raise


def handle_success(
    config: Config,
    github: GitHubClient,
    git: GitOps,
    issue,
    branch_name: str,
    state,
    run_dir: Path,
) -> PipelineStatus:
    """Handle successful pipeline completion."""
    print(f"[INFO] Pipeline succeeded, creating PR...")

    try:
        # Standard title format for commit and PR
        fix_title = f"Claude Fix #{issue.number}: {issue.title}"
        confidence = state.aggregate_confidence

        # Load fix state to get details
        files_changed = []
        caveats = []
        testing_notes = []
        fix_state_file = run_dir / "fix.state.json"
        if fix_state_file.exists():
            try:
                with open(fix_state_file) as f:
                    fix_data = json.load(f)
                files_changed = fix_data.get("files_changed", [])
                full_result = fix_data.get("full_result", {})
                caveats = full_result.get("caveats", [])
                testing_notes = full_result.get("testing_notes", [])
            except (json.JSONDecodeError, KeyError):
                pass

        # Load research state to get root cause
        root_cause = ""
        research_state_file = run_dir / "research.state.json"
        if research_state_file.exists():
            try:
                with open(research_state_file) as f:
                    research_data = json.load(f)
                rc = research_data.get("root_cause", {})
                if isinstance(rc, dict):
                    root_cause = rc.get("description", "")
                else:
                    root_cause = str(rc) if rc else ""
            except (json.JSONDecodeError, KeyError):
                pass

        # Build the detailed body (used for commit, PR, and issue comment)
        files_list = ", ".join(f"`{f}`" for f in files_changed[:5]) if files_changed else "See changes"

        detail_body = f"**Files changed:** {files_list}\n"

        if root_cause:
            detail_body += f"\n**Root cause:** {root_cause}\n"

        if caveats:
            detail_body += "\n**Caveats:**\n"
            for caveat in caveats[:3]:
                detail_body += f"- {caveat}\n"

        if testing_notes:
            detail_body += "\n**Testing notes:**\n"
            for note in testing_notes[:3]:
                detail_body += f"- {note}\n"

        detail_body += f"\n**Confidence:** {confidence:.0%}"

        # Build commit message with full details
        commit_body = f"""{fix_title}

Fixes #{issue.number}

{detail_body}

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"""

        # Commit any uncommitted changes (fix agent may or may not have committed)
        if git.has_changes():
            git.add(exclude_patterns=[".env", "*.env"])
            git.commit(commit_body)

        # Check if there are commits to push
        if not git.has_unpushed_commits("origin", branch_name):
            print("[WARNING] No commits to push")
            github.add_issue_comment(
                issue.number,
                f"Pipeline completed but no code changes were made.\n\n"
                f"Aggregate confidence: {state.aggregate_confidence}"
            )
            return PipelineStatus.SKIPPED
        diff_files = git._run("diff", "--name-only", f"origin/{config.base_branch}", check=False)
        if not diff_files.strip():
            print("[WARNING] No diff against base branch")
            github.add_issue_comment(
                issue.number,
                f"Pipeline completed but no code changes were detected against base branch.\n\n"
                f"Aggregate confidence: {state.aggregate_confidence}"
            )
            return PipelineStatus.SKIPPED

        # Push
        git.push("origin", branch_name, set_upstream=True)
        print(f"[SUCCESS] Pushed to origin/{branch_name}")

        # Build PR body with full details
        pr_body = f"""## Summary

Auto-generated fix for issue #{issue.number}

{detail_body}

## Confidence Breakdown

{json.dumps(state.confidence_breakdown, indent=2)}

## Test Plan

- [ ] Review the changes
- [ ] Run tests
- [ ] Verify fix addresses the issue

---
*Generated by [STRATO Fix All The Things](https://github.com/strato-net/strato-fix-all-the-things)*"""

        pr = github.create_pr(
            title=fix_title,
            body=pr_body,
            head=branch_name,
            base=config.base_branch,
            draft=True,
        )
        print(f"[SUCCESS] Created PR: {pr.url}")

        # Build issue comment
        comment = f"""🤖 **Automated Fix Created**

**PR:** {pr.url}

{detail_body}

Please review the PR before merging.

---
*Generated by [STRATO Fix All The Things](https://github.com/strato-net/strato-fix-all-the-things)*"""

        github.add_issue_comment(issue.number, comment)

        return PipelineStatus.SUCCESS

    except (GitError, GitHubError) as e:
        print(f"[ERROR] Failed to create PR: {e}")
        return PipelineStatus.FAILED


def handle_fix_no_changes(github: GitHubClient, issue, run_dir: Path) -> PipelineStatus:
    """Handle case where fix agent completed but made no changes."""
    print(f"[WARNING] Fix agent made no code changes")

    # Load research and triage data for context
    research_summary = ""
    triage_summary = ""

    triage_state_file = run_dir / "triage.state.json"
    if triage_state_file.exists():
        try:
            with open(triage_state_file) as f:
                triage_data = json.load(f)
            full_analysis = triage_data.get("full_analysis", {})
            triage_summary = full_analysis.get("summary", triage_data.get("summary", ""))
        except (json.JSONDecodeError, KeyError):
            pass

    research_state_file = run_dir / "research.state.json"
    if research_state_file.exists():
        try:
            with open(research_state_file) as f:
                research_data = json.load(f)
            research_summary = research_data.get("summary", "")
        except (json.JSONDecodeError, KeyError):
            pass

    # Build informative comment
    comment_parts = [
        "🤖 **Auto-Fix Analysis Complete**\n",
        "The issue was analyzed and deemed fixable, but the fix agent was unable to make any code changes.\n",
    ]

    if triage_summary:
        comment_parts.append(f"\n## Triage Analysis\n{triage_summary}\n")

    if research_summary:
        comment_parts.append(f"\n## Research Findings\n{research_summary}\n")

    comment_parts.append(
        "\n## Next Steps\n"
        "- A human developer should review this issue\n"
        "- The automated analysis above may provide useful context\n"
        "- Consider if the issue requires architectural changes beyond simple fixes\n"
    )

    comment_parts.append(
        "\n---\n"
        "*Generated by [STRATO Fix All The Things](https://github.com/strato-net/strato-fix-all-the-things)*"
    )

    try:
        github.add_issue_comment(issue.number, "".join(comment_parts))
    except GitHubError as e:
        print(f"[WARNING] Failed to comment on issue: {e}")

    return PipelineStatus.SKIPPED


def handle_skip(github: GitHubClient, issue, state, run_dir: Path) -> PipelineStatus:
    """Handle skipped pipeline."""
    print(f"[WARNING] Pipeline skipped: {state.failure_reason}")

    # Check if skip happened at fix stage (no changes made)
    fix_state_file = run_dir / "fix.state.json"
    if fix_state_file.exists() and "no changes" in state.failure_reason.lower():
        return handle_fix_no_changes(github, issue, run_dir)

    # Load triage analysis for detailed comment
    triage_state_file = run_dir / "triage.state.json"
    classification = ""
    analysis_summary = ""

    if triage_state_file.exists():
        try:
            with open(triage_state_file) as f:
                triage_data = json.load(f)

            classification = triage_data.get("classification", "")
            full_analysis = triage_data.get("full_analysis", {})
            summary = full_analysis.get("summary", triage_data.get("summary", ""))
            reasoning = full_analysis.get("reasoning", "")
            risks = full_analysis.get("risks", [])
            suggested_approach = full_analysis.get("suggested_approach", "")
            questions = full_analysis.get("questions_if_unclear", [])

            analysis_summary = f"""
## Analysis Summary

**Summary:** {summary}

**Reasoning:** {reasoning}
"""
            # Add classification-specific sections
            if classification == "NEEDS_HUMAN":
                if risks:
                    analysis_summary += f"""
**Risks:**
{chr(10).join(f"- {r}" for r in risks)}
"""
                if suggested_approach:
                    analysis_summary += f"""
**Suggested Approach:** {suggested_approach}
"""
                if questions:
                    analysis_summary += f"""
**Questions for Clarification:**
{chr(10).join(f"- {q}" for q in questions)}
"""

            elif classification == "NEEDS_CLARIFICATION":
                if questions:
                    analysis_summary += f"""
**Please provide clarification on:**
{chr(10).join(f"- {q}" for q in questions)}
"""

            elif classification == "OUT_OF_SCOPE":
                analysis_summary += """
**Why this is out of scope:** This issue does not appear to be a bug or configuration issue that can be addressed through code changes. It may be a feature request, documentation issue, or external dependency problem.
"""

            elif classification == "DUPLICATE":
                analysis_summary += """
**Note:** This issue appears to be a duplicate. Please check for related issues that may already address this problem.
"""

        except (json.JSONDecodeError, KeyError):
            pass

    # Build classification-specific intro message
    intro_messages = {
        "NEEDS_HUMAN": "This issue requires human review due to its complexity or risk level.",
        "NEEDS_CLARIFICATION": "This issue needs more information before it can be addressed.",
        "OUT_OF_SCOPE": "This issue is outside the scope of automated fixes.",
        "DUPLICATE": "This issue appears to be a duplicate of an existing issue.",
    }
    intro = intro_messages.get(classification, "This issue was analyzed but cannot be auto-fixed.")

    try:
        github.add_issue_comment(
            issue.number,
            f"🤖 **Auto-Fix Analysis Complete**\n\n"
            f"{intro}\n\n"
            f"**Classification:** `{classification}`\n"
            f"{analysis_summary}\n"
            f"---\n"
            f"*Generated by [STRATO Fix All The Things](https://github.com/strato-net/strato-fix-all-the-things)*"
        )
    except GitHubError as e:
        print(f"[WARNING] Failed to comment on issue: {e}")

    return PipelineStatus.SKIPPED


def handle_failure(
    github: GitHubClient,
    git: GitOps,
    issue,
    branch_name: str,
    state,
    base_branch: str,
    run_dir: Path,
) -> PipelineStatus:
    """Handle failed or blocked pipeline."""
    print(f"[ERROR] Pipeline failed: {state.failure_reason}")
    cleanup_git_state(git, base_branch, branch_name)

    # Build informative comment about the failure
    status_emoji = "🚫" if state.status == PipelineStatus.BLOCKED else "❌"
    status_label = "Blocked" if state.status == PipelineStatus.BLOCKED else "Failed"

    # Check which stage we got to
    agents_completed = state.agents_completed if hasattr(state, 'agents_completed') else []
    got_to_fix = any("fix" in a for a in agents_completed)
    got_to_review = any("review" in a for a in agents_completed)

    # Build the comment
    comment_parts = [
        f"{status_emoji} **Auto-Fix {status_label}**\n",
        f"**Reason:** {state.failure_reason}\n",
    ]

    # If we got to fix/review, include more context
    if got_to_fix or got_to_review:
        comment_parts.append("\n## What Happened\n")

        # Load fix state for context
        fix_state_file = run_dir / "fix.state.json"
        if fix_state_file.exists():
            try:
                with open(fix_state_file) as f:
                    fix_data = json.load(f)
                files_changed = fix_data.get("files_changed", [])
                if files_changed:
                    comment_parts.append(f"**Files attempted:** {', '.join(f'`{f}`' for f in files_changed[:5])}\n")
            except (json.JSONDecodeError, KeyError):
                pass

        # Load review state for context
        review_state_file = run_dir / "review.state.json"
        if review_state_file.exists():
            try:
                with open(review_state_file) as f:
                    review_data = json.load(f)
                verdict = review_data.get("verdict", "")
                concerns = review_data.get("concerns", [])
                suggestions = review_data.get("suggestions", [])

                if verdict:
                    comment_parts.append(f"\n**Review verdict:** `{verdict}`\n")

                if concerns:
                    comment_parts.append("\n**Concerns:**\n")
                    for c in concerns[:3]:
                        comment_parts.append(f"- {c}\n")

                if suggestions:
                    comment_parts.append("\n**Suggestions:**\n")
                    for s in suggestions[:3]:
                        comment_parts.append(f"- {s}\n")
            except (json.JSONDecodeError, KeyError):
                pass

        # Check for revision attempts
        revision_count = sum(1 for a in agents_completed if "fix-revision" in a)
        if revision_count > 0:
            comment_parts.append(f"\n**Revision attempts:** {revision_count}\n")

    # Load research for root cause context
    research_state_file = run_dir / "research.state.json"
    if research_state_file.exists():
        try:
            with open(research_state_file) as f:
                research_data = json.load(f)
            rc = research_data.get("root_cause", {})
            if isinstance(rc, dict):
                root_cause = rc.get("description", "")
            else:
                root_cause = str(rc) if rc else ""
            if root_cause:
                comment_parts.append(f"\n**Identified root cause:** {root_cause[:500]}{'...' if len(root_cause) > 500 else ''}\n")
        except (json.JSONDecodeError, KeyError):
            pass

    comment_parts.append(
        "\n---\n"
        "*Generated by [STRATO Fix All The Things](https://github.com/strato-net/strato-fix-all-the-things)*"
    )

    try:
        github.add_issue_comment(issue.number, "".join(comment_parts))
    except GitHubError as e:
        print(f"[WARNING] Failed to comment on issue: {e}")

    return PipelineStatus.FAILED


if __name__ == "__main__":
    sys.exit(main())

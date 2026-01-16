"""GitHub API interactions using gh CLI."""

import json
import subprocess
import time
from dataclasses import dataclass

from .models import Issue


class GitHubError(Exception):
    """GitHub API error."""
    pass


@dataclass
class PullRequest:
    """Pull request data."""
    number: int
    url: str
    head_branch: str


class GitHubClient:
    """GitHub client using gh CLI."""

    def __init__(self, repo: str):
        self.repo = repo

    def _run_gh(self, *args: str, check: bool = True, retries: int = 2) -> str:
        """Run gh command and return output."""
        cmd = ["gh", *args, "-R", self.repo]
        attempt = 0
        last_error = ""
        while attempt <= retries:
            attempt += 1
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
            last_error = result.stderr.strip()
            if not check or attempt > retries:
                break
            retryable = any(
                token in last_error.lower()
                for token in ("rate limit", "timeout", "temporarily", "503", "502", "network")
            )
            if not retryable:
                break
            time.sleep(attempt)
        if check and last_error:
            raise GitHubError(f"gh command failed: {last_error}")
        return result.stdout.strip()

    def get_issue(self, issue_number: int) -> Issue:
        """Fetch issue details."""
        output = self._run_gh(
            "issue", "view", str(issue_number),
            "--json", "number,title,body,labels,url"
        )
        data = json.loads(output)
        return Issue(
            number=data["number"],
            title=data["title"],
            body=data["body"] or "",
            labels=[label["name"] for label in data.get("labels", [])],
            url=data.get("url", ""),
        )

    def add_issue_comment(self, issue_number: int, body: str) -> None:
        """Add a comment to an issue."""
        self._run_gh("issue", "comment", str(issue_number), "--body", body)

    def find_open_pr(self, branch: str) -> PullRequest | None:
        """Find an open PR for the given branch."""
        output = self._run_gh(
            "pr", "list",
            "--head", branch,
            "--state", "open",
            "--json", "number,url,headRefName",
            check=False,
        )
        if not output:
            return None
        prs = json.loads(output)
        if not prs:
            return None
        pr = prs[0]
        return PullRequest(
            number=pr["number"],
            url=pr["url"],
            head_branch=pr["headRefName"],
        )

    def close_pr(self, pr_number: int) -> None:
        """Close a pull request."""
        self._run_gh("pr", "close", str(pr_number))

    def create_pr(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = True,
    ) -> PullRequest:
        """Create a pull request."""
        args = [
            "pr", "create",
            "--title", title,
            "--body", body,
            "--head", head,
            "--base", base,
            "--label", "ai-fixes-experimental",
        ]
        if draft:
            args.append("--draft")

        output = self._run_gh(*args)
        # gh pr create outputs the PR URL
        pr_url = output.strip()

        # Get PR details
        pr_output = self._run_gh(
            "pr", "view", pr_url,
            "--json", "number,url,headRefName"
        )
        data = json.loads(pr_output)
        return PullRequest(
            number=data["number"],
            url=data["url"],
            head_branch=data["headRefName"],
        )

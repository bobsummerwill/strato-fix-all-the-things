"""GitHub API interactions using gh CLI."""

import json
import subprocess
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


@dataclass
class IssueComment:
    """Issue comment data."""
    id: int
    body: str
    author: str
    issue_number: int
    issue_url: str


class GitHubClient:
    """GitHub client using gh CLI."""

    def __init__(self, repo: str):
        self.repo = repo

    def _run_gh(self, *args: str, check: bool = True) -> str:
        """Run gh command and return output."""
        cmd = ["gh", *args, "-R", self.repo]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if check and result.returncode != 0:
            raise GitHubError(f"gh command failed: {result.stderr}")
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

    def get_issue_comment(self, comment_id: int) -> IssueComment:
        """Fetch issue comment details by comment id."""
        owner, repo_name = self.repo.split("/", maxsplit=1)
        output = self._run_gh(
            "api",
            f"repos/{owner}/{repo_name}/issues/comments/{comment_id}",
        )
        data = json.loads(output)

        issue_url = data.get("issue_url", "")
        issue_number = 0
        if issue_url:
            try:
                issue_number = int(issue_url.rstrip("/").split("/")[-1])
            except (ValueError, IndexError):
                issue_number = 0

        return IssueComment(
            id=int(data["id"]),
            body=data.get("body", "") or "",
            author=(data.get("user") or {}).get("login", ""),
            issue_number=issue_number,
            issue_url=issue_url,
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

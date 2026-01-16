"""Configuration and environment handling."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class Config:
    """Pipeline configuration."""
    github_token: str
    github_repo: str
    project_dir: Path
    work_dir: Path
    base_branch: str
    script_dir: Path
    prompts_dir: Path
    runs_dir: Path
    tool_clone_dir: Path
    test_command: str | None = None

    # Timeouts (seconds)
    triage_timeout: int = 180
    research_timeout: int = 300
    fix_timeout: int = 600
    review_timeout: int = 300

    # Confidence thresholds
    min_triage_confidence: float = 0.6
    min_research_confidence: float = 0.4

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        """Load configuration from environment."""
        if env_file and env_file.exists():
            load_dotenv(env_file)

        script_dir = Path(__file__).parent.parent.resolve()
        prompts_dir = script_dir / "prompts"

        github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not github_token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN not set")

        github_repo = os.environ.get("GITHUB_REPO", "blockapps/strato-platform")
        project_dir = Path(os.environ.get("PROJECT_DIR", script_dir.parent / "strato-platform"))
        tool_clone_dir = Path(os.environ.get("TOOL_CLONE_DIR", script_dir / ".tool-clone"))
        base_branch = os.environ.get("BASE_BRANCH", "develop")
        runs_dir = script_dir / "runs"
        test_command = os.environ.get("TEST_COMMAND")

        return cls(
            github_token=github_token,
            github_repo=github_repo,
            project_dir=project_dir,
            work_dir=tool_clone_dir,
            base_branch=base_branch,
            script_dir=script_dir,
            prompts_dir=prompts_dir,
            runs_dir=runs_dir,
            tool_clone_dir=tool_clone_dir,
            test_command=test_command,
        )

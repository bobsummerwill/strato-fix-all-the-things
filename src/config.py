"""Configuration and environment handling."""

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv


class ConfigError(Exception):
    """Configuration error."""
    pass


def _parse_int(value: str | None, default: int, name: str, min_val: int = 1) -> int:
    """Parse an integer from string with validation."""
    if value is None:
        return default
    try:
        result = int(value)
        if result < min_val:
            raise ConfigError(f"{name} must be >= {min_val}, got {result}")
        return result
    except ValueError:
        raise ConfigError(f"{name} must be an integer, got '{value}'")


def _parse_float(value: str | None, default: float, name: str, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Parse a float from string with validation."""
    if value is None:
        return default
    try:
        result = float(value)
        if result < min_val or result > max_val:
            raise ConfigError(f"{name} must be between {min_val} and {max_val}, got {result}")
        return result
    except ValueError:
        raise ConfigError(f"{name} must be a number, got '{value}'")


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

    # Timeouts (seconds)
    triage_timeout: int = 180
    research_timeout: int = 300
    fix_timeout: int = 600
    review_timeout: int = 300

    # Confidence thresholds
    min_triage_confidence: float = 0.6
    min_research_confidence: float = 0.4

    # Fix-review loop settings
    max_fix_review_iterations: int = 3

    # Lock timeout (0 = wait forever)
    lock_timeout_sec: int = 0

    def validate(self) -> None:
        """Validate configuration values.

        Raises ConfigError if any values are invalid.
        """
        errors = []

        # Validate required paths exist
        if not self.prompts_dir.exists():
            errors.append(f"Prompts directory not found: {self.prompts_dir}")

        # Validate required prompts exist
        required_prompts = ["triage.md", "research.md", "fix.md", "review.md", "fix-revision.md"]
        for prompt in required_prompts:
            if not (self.prompts_dir / prompt).exists():
                errors.append(f"Required prompt template missing: {self.prompts_dir / prompt}")

        # Validate github_repo format
        if "/" not in self.github_repo:
            errors.append(f"GITHUB_REPO must be in 'owner/repo' format, got '{self.github_repo}'")

        # Validate timeouts are reasonable
        max_timeout = 3600  # 1 hour max
        if self.triage_timeout > max_timeout:
            errors.append(f"TRIAGE_TIMEOUT too large: {self.triage_timeout}s (max {max_timeout}s)")
        if self.research_timeout > max_timeout:
            errors.append(f"RESEARCH_TIMEOUT too large: {self.research_timeout}s (max {max_timeout}s)")
        if self.fix_timeout > max_timeout:
            errors.append(f"FIX_TIMEOUT too large: {self.fix_timeout}s (max {max_timeout}s)")
        if self.review_timeout > max_timeout:
            errors.append(f"REVIEW_TIMEOUT too large: {self.review_timeout}s (max {max_timeout}s)")

        if errors:
            raise ConfigError("Configuration errors:\n" + "\n".join(f"  - {e}" for e in errors))

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        """Load configuration from environment.

        Raises ConfigError if required values are missing or invalid.
        """
        if env_file and env_file.exists():
            load_dotenv(env_file)

        script_dir = Path(__file__).parent.parent.resolve()
        prompts_dir = script_dir / "prompts"

        # Required: GitHub token
        github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not github_token:
            raise ConfigError("GH_TOKEN or GITHUB_TOKEN environment variable not set")

        # Optional with defaults
        github_repo = os.environ.get("GITHUB_REPO", "blockapps/strato-platform")
        project_dir = Path(os.environ.get("PROJECT_DIR", script_dir.parent / "strato-platform"))
        tool_clone_dir = Path(os.environ.get("TOOL_CLONE_DIR", script_dir / ".tool-clone"))
        base_branch = os.environ.get("BASE_BRANCH", "develop")
        runs_dir = script_dir / "runs"

        # Parse timeouts
        triage_timeout = _parse_int(os.environ.get("TRIAGE_TIMEOUT"), 180, "TRIAGE_TIMEOUT")
        research_timeout = _parse_int(os.environ.get("RESEARCH_TIMEOUT"), 300, "RESEARCH_TIMEOUT")
        fix_timeout = _parse_int(os.environ.get("FIX_TIMEOUT"), 600, "FIX_TIMEOUT")
        review_timeout = _parse_int(os.environ.get("REVIEW_TIMEOUT"), 300, "REVIEW_TIMEOUT")

        # Parse confidence thresholds
        min_triage_confidence = _parse_float(
            os.environ.get("MIN_TRIAGE_CONFIDENCE"), 0.6, "MIN_TRIAGE_CONFIDENCE"
        )
        min_research_confidence = _parse_float(
            os.environ.get("MIN_RESEARCH_CONFIDENCE"), 0.4, "MIN_RESEARCH_CONFIDENCE"
        )

        # Parse other settings
        max_fix_review_iterations = _parse_int(
            os.environ.get("MAX_FIX_REVIEW_ITERATIONS"), 3, "MAX_FIX_REVIEW_ITERATIONS"
        )
        lock_timeout_sec = _parse_int(
            os.environ.get("STRATO_LOCK_TIMEOUT_SEC"), 0, "STRATO_LOCK_TIMEOUT_SEC", min_val=0
        )

        config = cls(
            github_token=github_token,
            github_repo=github_repo,
            project_dir=project_dir,
            work_dir=tool_clone_dir,
            base_branch=base_branch,
            script_dir=script_dir,
            prompts_dir=prompts_dir,
            runs_dir=runs_dir,
            tool_clone_dir=tool_clone_dir,
            triage_timeout=triage_timeout,
            research_timeout=research_timeout,
            fix_timeout=fix_timeout,
            review_timeout=review_timeout,
            min_triage_confidence=min_triage_confidence,
            min_research_confidence=min_research_confidence,
            max_fix_review_iterations=max_fix_review_iterations,
            lock_timeout_sec=lock_timeout_sec,
        )

        # Validate all config values
        config.validate()

        return config

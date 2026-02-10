"""Configuration and environment handling."""

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - fallback for minimal environments
    load_dotenv = None


def load_env_file_fallback(env_file: Path) -> None:
    """Minimal .env parser used when python-dotenv is unavailable."""
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class Config:
    """Pipeline configuration."""
    github_token: str
    github_repo: str
    project_dir: Path
    base_branch: str
    script_dir: Path
    runs_dir: Path

    # Timeouts (seconds)
    triage_timeout: int = 180
    research_timeout: int = 300
    fix_timeout: int = 600
    review_timeout: int = 300

    # Confidence thresholds
    min_triage_confidence: float = 0.6
    min_research_confidence: float = 0.4
    model_provider: str = "claude"
    triage_model_provider: str | None = None
    research_model_provider: str | None = None
    fix_model_provider: str | None = None
    review_model_provider: str | None = None
    claude_cli_command: str = "claude"
    codex_cli_command: str = "codex"

    @classmethod
    def load(cls, env_file: Path | None = None) -> "Config":
        """Load configuration from environment."""
        if env_file and env_file.exists():
            if load_dotenv:
                load_dotenv(env_file)
            else:
                load_env_file_fallback(env_file)

        script_dir = Path(__file__).parent.parent.resolve()

        github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        if not github_token:
            raise ValueError("GH_TOKEN or GITHUB_TOKEN not set")

        github_repo = os.environ.get("GITHUB_REPO", "blockapps/strato-platform")
        project_dir = Path(os.environ.get("PROJECT_DIR", script_dir.parent / "strato-platform"))
        base_branch = os.environ.get("BASE_BRANCH", "develop")
        runs_dir = script_dir / "runs"
        model_provider = os.environ.get("MODEL_PROVIDER", "claude").strip().lower()
        triage_model_provider = os.environ.get("TRIAGE_MODEL_PROVIDER", "").strip().lower() or None
        research_model_provider = os.environ.get("RESEARCH_MODEL_PROVIDER", "").strip().lower() or None
        fix_model_provider = os.environ.get("FIX_MODEL_PROVIDER", "").strip().lower() or None
        review_model_provider = os.environ.get("REVIEW_MODEL_PROVIDER", "").strip().lower() or None
        claude_cli_command = os.environ.get("CLAUDE_CLI_COMMAND", "claude").strip() or "claude"
        codex_cli_command = os.environ.get("CODEX_CLI_COMMAND", "codex").strip() or "codex"

        allowed_providers = {"claude", "codex"}
        all_providers = [
            model_provider,
            triage_model_provider,
            research_model_provider,
            fix_model_provider,
            review_model_provider,
        ]
        invalid = {p for p in all_providers if p and p not in allowed_providers}
        if invalid:
            invalid_list = ", ".join(sorted(invalid))
            raise ValueError(f"Invalid model provider(s): {invalid_list}. Allowed: claude, codex")

        return cls(
            github_token=github_token,
            github_repo=github_repo,
            project_dir=project_dir,
            base_branch=base_branch,
            script_dir=script_dir,
            runs_dir=runs_dir,
            model_provider=model_provider,
            triage_model_provider=triage_model_provider,
            research_model_provider=research_model_provider,
            fix_model_provider=fix_model_provider,
            review_model_provider=review_model_provider,
            claude_cli_command=claude_cli_command,
            codex_cli_command=codex_cli_command,
        )

    def provider_for_stage(self, stage_name: str) -> str:
        """Resolve model provider for a pipeline stage."""
        stage_overrides = {
            "triage": self.triage_model_provider,
            "research": self.research_model_provider,
            "fix": self.fix_model_provider,
            "review": self.review_model_provider,
        }
        return stage_overrides.get(stage_name) or self.model_provider

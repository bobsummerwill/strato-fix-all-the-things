"""Provider-agnostic LLM runner interface."""

from dataclasses import dataclass
from pathlib import Path

from .claude_runner import ClaudeError, ClaudeTimeoutError, run_claude
from .codex_runner import CodexError, CodexTimeoutError, run_codex
from .config import Config


class LLMRunnerError(Exception):
    """Generic provider execution error."""


class LLMRunnerTimeoutError(LLMRunnerError):
    """Generic provider timeout error."""


@dataclass
class LLMRunnerResult:
    """Normalized result for all providers."""

    provider: str
    success: bool
    output: str
    duration_ms: int
    cost_usd: float
    error: str = ""


def run_llm(
    *,
    provider: str,
    prompt: str,
    cwd: Path,
    timeout_sec: int,
    log_file: Path | None,
    config: Config,
) -> LLMRunnerResult:
    """Execute configured provider and normalize output."""
    normalized_provider = provider.strip().lower()

    if normalized_provider == "claude":
        try:
            result = run_claude(
                prompt=prompt,
                cwd=cwd,
                timeout_sec=timeout_sec,
                log_file=log_file,
                cli_command=config.claude_cli_command,
            )
        except ClaudeTimeoutError as e:
            raise LLMRunnerTimeoutError(str(e)) from e
        except ClaudeError as e:
            raise LLMRunnerError(str(e)) from e

        return LLMRunnerResult(
            provider="claude",
            success=result.success,
            output=result.output,
            duration_ms=result.duration_ms,
            cost_usd=result.cost_usd,
            error=result.error,
        )

    if normalized_provider == "codex":
        try:
            result = run_codex(
                prompt=prompt,
                cwd=cwd,
                timeout_sec=timeout_sec,
                log_file=log_file,
                cli_command=config.codex_cli_command,
            )
        except CodexTimeoutError as e:
            raise LLMRunnerTimeoutError(str(e)) from e
        except CodexError as e:
            raise LLMRunnerError(str(e)) from e

        return LLMRunnerResult(
            provider="codex",
            success=result.success,
            output=result.output,
            duration_ms=result.duration_ms,
            cost_usd=result.cost_usd,
            error=result.error,
        )

    raise LLMRunnerError(f"Unsupported provider: {provider}")

"""Codex CLI execution and output parsing."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class CodexError(Exception):
    """Codex execution error."""


class CodexTimeoutError(CodexError):
    """Codex execution timed out."""


@dataclass
class CodexResult:
    """Result from Codex execution."""

    success: bool
    output: str
    duration_ms: int
    cost_usd: float
    error: str = ""


def run_codex(
    prompt: str,
    cwd: Path,
    timeout_sec: int = 600,
    log_file: Path | None = None,
    cli_command: str = "codex",
) -> CodexResult:
    """Run Codex CLI with a prompt and return the result."""
    cmd = [
        cli_command,
        "exec",
        "--skip-git-repo-check",
        "--full-auto",
        prompt,
    ]
    started = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as e:
        raise CodexError(f"Codex CLI not found: {cli_command}") from e
    except subprocess.TimeoutExpired as e:
        raise CodexTimeoutError(f"Codex timed out after {timeout_sec}s") from e

    output = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    combined = output if output else stderr
    if log_file:
        log_file.write_text(combined)

    return CodexResult(
        success=result.returncode == 0,
        output=combined,
        duration_ms=int((time.time() - started) * 1000),
        cost_usd=0.0,
        error=stderr if result.returncode != 0 else "",
    )

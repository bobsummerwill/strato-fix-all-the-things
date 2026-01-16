"""Claude CLI execution and output parsing."""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ClaudeError(Exception):
    """Claude execution error."""
    pass


class ClaudeTimeoutError(ClaudeError):
    """Claude timed out."""
    pass


@dataclass
class ClaudeResult:
    """Result from Claude execution."""
    success: bool
    output: str
    duration_ms: int
    cost_usd: float
    error: str = ""


def run_claude(
    prompt: str,
    cwd: Path,
    timeout_sec: int = 600,
    log_file: Path | None = None,
) -> ClaudeResult:
    """Run Claude CLI with a prompt and return the result."""
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "--verbose",
        "--output-format", "stream-json",
        "--print",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )

        output = result.stdout
        if log_file:
            log_file.write_text(output)

        # Parse the final result message
        duration_ms = 0
        cost_usd = 0.0

        for line in output.split("\n"):
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
                if msg.get("type") == "result":
                    duration_ms = msg.get("duration_ms", 0)
                    cost_usd = msg.get("total_cost_usd", 0.0)
            except json.JSONDecodeError:
                continue

        return ClaudeResult(
            success=result.returncode == 0,
            output=output,
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            error=result.stderr if result.returncode != 0 else "",
        )

    except subprocess.TimeoutExpired:
        raise ClaudeTimeoutError(f"Claude timed out after {timeout_sec}s")


def extract_json_from_output(output: str, required_field: str = "classification") -> dict[str, Any] | None:
    """Extract JSON from Claude's stream-json output.

    Looks for JSON blocks in markdown code fences with the required field.
    """
    # Unescape JSON-encoded strings
    text = output.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

    # Find ```json ... ``` blocks
    matches = re.findall(r"```json\s*(\{.+?\})\s*```", text, re.DOTALL)

    # Try each match from last to first (most recent is usually most complete)
    for match in reversed(matches):
        try:
            obj = json.loads(match)
            if required_field in obj:
                return obj
        except json.JSONDecodeError:
            continue

    # Fallback: look for raw JSON with required field
    pattern = rf'\{{[^{{}}]*"{required_field}"[^{{}}]*\}}'
    matches = re.findall(pattern, text)
    for match in reversed(matches):
        try:
            obj = json.loads(match)
            if required_field in obj:
                return obj
        except json.JSONDecodeError:
            continue

    return None

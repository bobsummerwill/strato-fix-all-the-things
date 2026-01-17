"""Claude CLI execution and output parsing."""

import json
import re
import subprocess
import time
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
    retries: int = 2,
    retry_backoff_sec: float = 1.0,
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

    attempt = 0
    last_error = ""
    while attempt <= retries:
        attempt += 1
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

            if result.returncode == 0:
                return ClaudeResult(
                    success=True,
                    output=output,
                    duration_ms=duration_ms,
                    cost_usd=cost_usd,
                    error="",
                )

            last_error = result.stderr or "Claude CLI failed"
            if attempt <= retries:
                time.sleep(retry_backoff_sec * attempt)
                continue
            return ClaudeResult(
                success=False,
                output=output,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                error=last_error,
            )

        except subprocess.TimeoutExpired:
            last_error = f"Claude timed out after {timeout_sec}s"
            if attempt <= retries:
                time.sleep(retry_backoff_sec * attempt)
                continue
            raise ClaudeTimeoutError(last_error)


def _contains_required_field(value: Any, required_field: str) -> bool:
    """Check if a JSON value contains the required field at any nesting level."""
    if isinstance(value, dict):
        if required_field in value:
            return True
        return any(_contains_required_field(v, required_field) for v in value.values())
    if isinstance(value, list):
        return any(_contains_required_field(v, required_field) for v in value)
    return False


def _extract_json_blocks(text: str) -> list[str]:
    """Extract content from ```json ... ``` blocks.

    Uses a simple state machine to handle nested code blocks properly.
    Returns list of JSON strings (content between the markers).
    """
    blocks = []
    i = 0
    while i < len(text):
        # Look for ```json marker
        start_marker = text.find("```json", i)
        if start_marker == -1:
            break

        # Find the end of the opening marker line
        content_start = text.find("\n", start_marker)
        if content_start == -1:
            break
        content_start += 1

        # Find the closing ``` - but be careful of nested code blocks
        # We look for ``` at the start of a line (or after whitespace)
        search_pos = content_start
        while search_pos < len(text):
            close_marker = text.find("```", search_pos)
            if close_marker == -1:
                # No closing marker found, take rest of text
                blocks.append(text[content_start:].strip())
                i = len(text)
                break

            # Check if this is a closing marker (not opening another block)
            # A closing marker should not be followed by a language identifier
            after_close = close_marker + 3
            if after_close >= len(text) or text[after_close] in ("\n", " ", "\t", "\r"):
                # This is a closing marker
                blocks.append(text[content_start:close_marker].strip())
                i = after_close
                break
            else:
                # This opens another code block, skip past it
                search_pos = after_close
        else:
            break

    return blocks


def _try_parse_json(text: str, required_field: str) -> dict[str, Any] | None:
    """Try to parse text as JSON and verify it contains the required field."""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and _contains_required_field(obj, required_field):
            return obj
    except json.JSONDecodeError:
        pass
    return None


def _find_json_objects(text: str, required_field: str) -> dict[str, Any] | None:
    """Find JSON objects in text using incremental parsing.

    More efficient than O(n²) scanning - uses the JSON decoder's ability
    to report where parsing stopped.
    """
    decoder = json.JSONDecoder()

    # Find all positions where a JSON object might start
    i = 0
    while i < len(text):
        # Skip to next potential JSON start
        while i < len(text) and text[i] not in "{[":
            i += 1
        if i >= len(text):
            break

        try:
            obj, end_idx = decoder.raw_decode(text, i)
            if isinstance(obj, dict) and _contains_required_field(obj, required_field):
                return obj
            # Move past this object to find others
            i += end_idx
        except json.JSONDecodeError:
            # Not valid JSON at this position, move to next character
            i += 1

    return None


def extract_json_from_output(output: str, required_field: str = "classification") -> dict[str, Any] | None:
    """Extract JSON from Claude's stream-json output.

    Parses stream-json lines to find assistant message text containing JSON blocks.
    Strategy:
    1. Parse stream-json format and extract text content
    2. Look for ```json ... ``` blocks in text content
    3. Fall back to finding raw JSON objects in text
    """
    # First, try to properly parse stream-json lines and extract text content
    text_contents = []
    for line in output.split("\n"):
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
            if msg.get("type") == "assistant":
                for content in msg.get("message", {}).get("content", []):
                    if content.get("type") == "text":
                        text_contents.append(content.get("text", ""))
        except json.JSONDecodeError:
            continue

    # Search through all text content for JSON blocks (most recent first)
    for text in reversed(text_contents):
        # Extract ```json ... ``` blocks
        json_blocks = _extract_json_blocks(text)
        for block in reversed(json_blocks):
            result = _try_parse_json(block, required_field)
            if result:
                return result

        # Try finding raw JSON objects in the text
        result = _find_json_objects(text, required_field)
        if result:
            return result

    # Fallback: try on raw output (for non-stream-json format)
    # Unescape common escape sequences
    raw_text = output.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

    json_blocks = _extract_json_blocks(raw_text)
    for block in reversed(json_blocks):
        result = _try_parse_json(block, required_field)
        if result:
            return result

    # Last resort: scan raw output for JSON objects
    return _find_json_objects(raw_text, required_field)

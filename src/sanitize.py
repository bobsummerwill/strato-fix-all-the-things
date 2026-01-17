"""Input sanitization utilities to prevent prompt injection."""

import re


def sanitize_for_prompt(text: str | None, max_length: int = 50000) -> str:
    """Sanitize user-provided text before including in prompts.

    This helps prevent prompt injection attacks where malicious issue
    content could try to override agent instructions.

    Args:
        text: The text to sanitize (issue title, body, labels, etc.)
        max_length: Maximum allowed length (truncate if exceeded)

    Returns:
        Sanitized text safe for prompt inclusion
    """
    if text is None:
        return ""

    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[TRUNCATED - content too long]"

    # Escape markdown code fence delimiters that could break out of code blocks
    # Replace ``` with escaped version
    text = text.replace("```", "` ` `")

    # Remove or escape sequences that look like prompt instructions
    # These patterns try to inject new instructions
    injection_patterns = [
        # "Ignore previous instructions" style attacks
        (r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)", "[FILTERED]"),
        (r"(?i)disregard\s+(all\s+)?(previous|prior|above)", "[FILTERED]"),
        (r"(?i)forget\s+(everything|all)\s+(above|before)", "[FILTERED]"),
        # "New instructions" style attacks
        (r"(?i)new\s+instructions?:", "[FILTERED]"),
        (r"(?i)system\s*prompt:", "[FILTERED]"),
        (r"(?i)override\s*:", "[FILTERED]"),
        # Role switching attacks
        (r"(?i)you\s+are\s+now\s+(a|an)\s+", "you were described as a "),
        (r"(?i)act\s+as\s+(a|an)\s+", "described as a "),
        # Output format manipulation
        (r"(?i)output\s+only\s*:", "[FILTERED]"),
        (r"(?i)respond\s+only\s+with", "[FILTERED]"),
    ]

    for pattern, replacement in injection_patterns:
        text = re.sub(pattern, replacement, text)

    return text


def sanitize_label(label: str) -> str:
    """Sanitize a single label string."""
    if not label:
        return ""
    # Labels should be short, alphanumeric with hyphens/underscores
    # Truncate and remove anything suspicious
    label = label[:100]  # Labels shouldn't be very long
    return sanitize_for_prompt(label, max_length=100)


def sanitize_labels(labels: list[str] | None) -> list[str]:
    """Sanitize a list of labels."""
    if not labels:
        return []
    return [sanitize_label(label) for label in labels[:20]]  # Max 20 labels

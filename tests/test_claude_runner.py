"""Tests for Claude runner and JSON extraction."""

import pytest
from src.claude_runner import (
    _contains_required_field,
    _extract_json_blocks,
    _find_json_objects,
    _try_parse_json,
    extract_json_from_output,
)


class TestContainsRequiredField:
    """Tests for _contains_required_field function."""

    def test_direct_field(self):
        """Field at top level is found."""
        assert _contains_required_field({"classification": "bug"}, "classification")

    def test_nested_field(self):
        """Field in nested dict is found."""
        data = {"result": {"classification": "bug"}}
        assert _contains_required_field(data, "classification")

    def test_field_in_list(self):
        """Field in list items is found."""
        data = {"items": [{"name": "a"}, {"classification": "bug"}]}
        assert _contains_required_field(data, "classification")

    def test_missing_field(self):
        """Missing field returns False."""
        assert not _contains_required_field({"other": "value"}, "classification")

    def test_non_dict(self):
        """Non-dict values return False."""
        assert not _contains_required_field("string", "classification")
        assert not _contains_required_field(123, "classification")
        assert not _contains_required_field(None, "classification")


class TestExtractJsonBlocks:
    """Tests for _extract_json_blocks function."""

    def test_single_block(self):
        """Single JSON block is extracted."""
        text = 'Some text\n```json\n{"key": "value"}\n```\nMore text'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 1
        assert '{"key": "value"}' in blocks[0]

    def test_multiple_blocks(self):
        """Multiple JSON blocks are all extracted."""
        text = '```json\n{"a": 1}\n```\n\n```json\n{"b": 2}\n```'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 2

    def test_no_blocks(self):
        """Text without JSON blocks returns empty list."""
        text = "Just some regular text"
        blocks = _extract_json_blocks(text)
        assert blocks == []

    def test_nested_code_blocks(self):
        """Handles code blocks containing other code fences."""
        text = '```json\n{"code": "```python\\nprint()\\n```"}\n```'
        blocks = _extract_json_blocks(text)
        # Should still extract something
        assert len(blocks) >= 1

    def test_unclosed_block(self):
        """Unclosed block extracts remaining text."""
        text = '```json\n{"key": "value"}'
        blocks = _extract_json_blocks(text)
        assert len(blocks) == 1


class TestTryParseJson:
    """Tests for _try_parse_json function."""

    def test_valid_json_with_field(self):
        """Valid JSON with required field is parsed."""
        text = '{"classification": "bug", "confidence": 0.9}'
        result = _try_parse_json(text, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_valid_json_without_field(self):
        """Valid JSON without required field returns None."""
        text = '{"other": "value"}'
        result = _try_parse_json(text, "classification")
        assert result is None

    def test_invalid_json(self):
        """Invalid JSON returns None."""
        text = '{"broken": json'
        result = _try_parse_json(text, "classification")
        assert result is None

    def test_json_array(self):
        """JSON array (not object) returns None."""
        text = '[1, 2, 3]'
        result = _try_parse_json(text, "classification")
        assert result is None


class TestFindJsonObjects:
    """Tests for _find_json_objects function."""

    def test_json_at_start(self):
        """JSON at start of text is found."""
        text = '{"classification": "bug"} and some text'
        result = _find_json_objects(text, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_json_in_middle(self):
        """JSON in middle of text is found."""
        text = 'Some text {"classification": "bug"} more text'
        result = _find_json_objects(text, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_multiple_objects_finds_first_match(self):
        """First JSON with required field is returned."""
        text = '{"other": 1} {"classification": "bug"}'
        result = _find_json_objects(text, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_nested_json(self):
        """Nested JSON is parsed correctly."""
        text = '{"result": {"classification": "bug"}}'
        result = _find_json_objects(text, "classification")
        assert result is not None

    def test_no_matching_json(self):
        """No matching JSON returns None."""
        text = '{"other": "value"} text'
        result = _find_json_objects(text, "classification")
        assert result is None


class TestExtractJsonFromOutput:
    """Tests for extract_json_from_output function."""

    def test_stream_json_format(self):
        """Parses Claude's stream-json format."""
        output = '''{"type": "assistant", "message": {"content": [{"type": "text", "text": "```json\\n{\\"classification\\": \\"bug\\"}\\n```"}]}}'''
        result = extract_json_from_output(output, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_plain_json_block(self):
        """Parses plain JSON blocks in raw text."""
        output = 'Here is my analysis:\n```json\n{"classification": "bug", "confidence": 0.9}\n```'
        result = extract_json_from_output(output, "classification")
        assert result is not None
        assert result["classification"] == "bug"

    def test_raw_json(self):
        """Parses raw JSON without code blocks."""
        output = 'Analysis complete. {"classification": "bug"}'
        result = extract_json_from_output(output, "classification")
        assert result is not None

    def test_most_recent_first(self):
        """Most recent matching JSON is returned (from reversed search)."""
        output = '''```json
{"classification": "old"}
```

Updated analysis:

```json
{"classification": "new"}
```'''
        result = extract_json_from_output(output, "classification")
        assert result is not None
        assert result["classification"] == "new"

    def test_no_json_found(self):
        """Returns None when no JSON found."""
        output = "Just some regular text without any JSON"
        result = extract_json_from_output(output, "classification")
        assert result is None

    def test_escaped_json(self):
        """Handles escaped JSON in output."""
        output = 'Result: {\\"classification\\": \\"bug\\"}'
        result = extract_json_from_output(output, "classification")
        assert result is not None

    def test_complex_nested_json(self):
        """Handles complex nested JSON structures."""
        output = '''```json
{
    "classification": "FIXABLE_CODE",
    "confidence": 0.85,
    "details": {
        "root_cause": "Missing null check",
        "files": ["src/main.py", "src/utils.py"]
    }
}
```'''
        result = extract_json_from_output(output, "classification")
        assert result is not None
        assert result["classification"] == "FIXABLE_CODE"
        assert result["details"]["files"] == ["src/main.py", "src/utils.py"]

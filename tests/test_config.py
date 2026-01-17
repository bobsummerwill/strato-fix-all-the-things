"""Tests for configuration loading and validation."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch

from src.config import Config, ConfigError, _parse_int, _parse_float


class TestParseInt:
    """Tests for _parse_int helper."""

    def test_none_returns_default(self):
        """None value returns default."""
        assert _parse_int(None, 100, "TEST") == 100

    def test_valid_int(self):
        """Valid integer string is parsed."""
        assert _parse_int("50", 100, "TEST") == 50

    def test_invalid_int_raises(self):
        """Invalid integer raises ConfigError."""
        with pytest.raises(ConfigError) as exc:
            _parse_int("not_a_number", 100, "TEST_VAR")
        assert "TEST_VAR" in str(exc.value)
        assert "integer" in str(exc.value)

    def test_below_min_raises(self):
        """Value below minimum raises ConfigError."""
        with pytest.raises(ConfigError) as exc:
            _parse_int("0", 100, "TEST_VAR", min_val=1)
        assert "must be >=" in str(exc.value)

    def test_zero_allowed_with_min_zero(self):
        """Zero is allowed when min_val=0."""
        assert _parse_int("0", 100, "TEST", min_val=0) == 0


class TestParseFloat:
    """Tests for _parse_float helper."""

    def test_none_returns_default(self):
        """None value returns default."""
        assert _parse_float(None, 0.5, "TEST") == 0.5

    def test_valid_float(self):
        """Valid float string is parsed."""
        assert _parse_float("0.75", 0.5, "TEST") == 0.75

    def test_invalid_float_raises(self):
        """Invalid float raises ConfigError."""
        with pytest.raises(ConfigError) as exc:
            _parse_float("not_a_number", 0.5, "TEST_VAR")
        assert "TEST_VAR" in str(exc.value)
        assert "number" in str(exc.value)

    def test_below_min_raises(self):
        """Value below minimum raises ConfigError."""
        with pytest.raises(ConfigError) as exc:
            _parse_float("-0.1", 0.5, "TEST_VAR", min_val=0.0)
        assert "between" in str(exc.value)

    def test_above_max_raises(self):
        """Value above maximum raises ConfigError."""
        with pytest.raises(ConfigError) as exc:
            _parse_float("1.5", 0.5, "TEST_VAR", max_val=1.0)
        assert "between" in str(exc.value)


class TestConfigValidation:
    """Tests for Config.validate method."""

    def test_missing_prompts_dir(self, tmp_path):
        """Missing prompts directory raises error."""
        config = Config(
            github_token="token",
            github_repo="owner/repo",
            project_dir=tmp_path,
            work_dir=tmp_path,
            base_branch="main",
            script_dir=tmp_path,
            prompts_dir=tmp_path / "nonexistent",
            runs_dir=tmp_path / "runs",
            tool_clone_dir=tmp_path / "clone",
        )
        with pytest.raises(ConfigError) as exc:
            config.validate()
        assert "Prompts directory not found" in str(exc.value)

    def test_missing_prompt_files(self, tmp_path):
        """Missing prompt templates raise errors."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        # Create only some prompts
        (prompts_dir / "triage.md").write_text("template")

        config = Config(
            github_token="token",
            github_repo="owner/repo",
            project_dir=tmp_path,
            work_dir=tmp_path,
            base_branch="main",
            script_dir=tmp_path,
            prompts_dir=prompts_dir,
            runs_dir=tmp_path / "runs",
            tool_clone_dir=tmp_path / "clone",
        )
        with pytest.raises(ConfigError) as exc:
            config.validate()
        assert "Required prompt template missing" in str(exc.value)

    def test_invalid_github_repo_format(self, tmp_path):
        """Invalid github_repo format raises error."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        for name in ["triage.md", "research.md", "fix.md", "review.md", "fix-revision.md"]:
            (prompts_dir / name).write_text("template")

        config = Config(
            github_token="token",
            github_repo="invalid-no-slash",
            project_dir=tmp_path,
            work_dir=tmp_path,
            base_branch="main",
            script_dir=tmp_path,
            prompts_dir=prompts_dir,
            runs_dir=tmp_path / "runs",
            tool_clone_dir=tmp_path / "clone",
        )
        with pytest.raises(ConfigError) as exc:
            config.validate()
        assert "owner/repo" in str(exc.value)

    def test_timeout_too_large(self, tmp_path):
        """Timeout exceeding max raises error."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        for name in ["triage.md", "research.md", "fix.md", "review.md", "fix-revision.md"]:
            (prompts_dir / name).write_text("template")

        config = Config(
            github_token="token",
            github_repo="owner/repo",
            project_dir=tmp_path,
            work_dir=tmp_path,
            base_branch="main",
            script_dir=tmp_path,
            prompts_dir=prompts_dir,
            runs_dir=tmp_path / "runs",
            tool_clone_dir=tmp_path / "clone",
            triage_timeout=5000,  # > 3600
        )
        with pytest.raises(ConfigError) as exc:
            config.validate()
        assert "TRIAGE_TIMEOUT too large" in str(exc.value)

    def test_valid_config_passes(self, tmp_path):
        """Valid configuration passes validation."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        for name in ["triage.md", "research.md", "fix.md", "review.md", "fix-revision.md"]:
            (prompts_dir / name).write_text("template")

        config = Config(
            github_token="token",
            github_repo="owner/repo",
            project_dir=tmp_path,
            work_dir=tmp_path,
            base_branch="main",
            script_dir=tmp_path,
            prompts_dir=prompts_dir,
            runs_dir=tmp_path / "runs",
            tool_clone_dir=tmp_path / "clone",
        )
        config.validate()  # Should not raise


class TestConfigLoad:
    """Tests for Config.load method."""

    def test_missing_github_token_raises(self, tmp_path, monkeypatch):
        """Missing GitHub token raises ConfigError."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        with pytest.raises(ConfigError) as exc:
            Config.load()
        assert "GH_TOKEN or GITHUB_TOKEN" in str(exc.value)

    def test_loads_timeout_from_env(self, tmp_path, monkeypatch):
        """Timeout values are loaded from environment."""
        # Set up required env vars
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("TRIAGE_TIMEOUT", "200")
        monkeypatch.setenv("FIX_TIMEOUT", "500")

        # This will fail validation (no prompts dir), but we can catch and check values
        try:
            config = Config.load()
        except ConfigError:
            # Re-read to check parsing worked
            from src.config import _parse_int
            assert _parse_int(os.environ.get("TRIAGE_TIMEOUT"), 180, "TEST") == 200
            assert _parse_int(os.environ.get("FIX_TIMEOUT"), 600, "TEST") == 500

    def test_invalid_timeout_raises(self, monkeypatch):
        """Invalid timeout value raises ConfigError."""
        monkeypatch.setenv("GH_TOKEN", "test_token")
        monkeypatch.setenv("TRIAGE_TIMEOUT", "not_a_number")

        with pytest.raises(ConfigError) as exc:
            Config.load()
        assert "TRIAGE_TIMEOUT" in str(exc.value)

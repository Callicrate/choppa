"""Unit tests for choppa core functionality."""

from __future__ import annotations

from pathlib import Path

import pytest

from choppa import RemoteError, RemoteExecutionFailed, RemoteFunction
from choppa._internal import _strip_leading_decorators
from choppa.choppa import _read_cluster_id_from_config, _resolve_cluster_id


class TestClusterIdResolution:
    """Tests for cluster ID resolution logic."""

    def test_explicit_parameter_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Explicit cluster_id parameter should override env vars."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster")
        result = _resolve_cluster_id("explicit-cluster")
        assert result == "explicit-cluster"

    def test_env_var_used_when_no_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DATABRICKS_CLUSTER_ID env var used when no param provided."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster")
        result = _resolve_cluster_id(None)
        assert result == "env-cluster"

    def test_config_file_profile_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """cluster_id from profile specified by DATABRICKS_CONFIG_PROFILE."""
        config_content = """[myprofile]
cluster_id = profile-cluster
host = https://example.databricks.com
"""
        config_file = tmp_path / ".databrickscfg"
        config_file.write_text(config_content)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "myprofile")
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        result = _read_cluster_id_from_config()
        assert result == "profile-cluster"

    def test_config_file_default_profile(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """cluster_id from DEFAULT profile when no profile env var set."""
        config_content = """[DEFAULT]
cluster_id = default-cluster
host = https://example.databricks.com
"""
        config_file = tmp_path / ".databrickscfg"
        config_file.write_text(config_content)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        result = _read_cluster_id_from_config()
        assert result == "default-cluster"

    def test_no_cluster_id_raises_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """ValueError raised when no cluster_id can be resolved."""
        config_file = tmp_path / ".databrickscfg"
        config_file.write_text("[DEFAULT]\nhost = https://example.com\n")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        with pytest.raises(ValueError, match="No cluster_id provided"):
            _resolve_cluster_id(None)

    def test_missing_config_file_continues(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Missing config file doesn't raise, just returns None."""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        result = _read_cluster_id_from_config()
        assert result is None

    def test_profile_env_priority_over_default(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Profile from env var takes priority over DEFAULT profile."""
        config_content = """[DEFAULT]
cluster_id = default-cluster
host = https://default.databricks.com

[myprofile]
cluster_id = profile-cluster
host = https://profile.databricks.com
"""
        config_file = tmp_path / ".databrickscfg"
        config_file.write_text(config_content)

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "myprofile")
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)

        result = _read_cluster_id_from_config()
        assert result == "profile-cluster"


class TestStripLeadingDecorators:
    """Tests for function source extraction."""

    def test_strips_decorators(self) -> None:
        source = "@decorator\ndef foo(): pass"
        result = _strip_leading_decorators(source)
        assert result.startswith("def")
        assert "@decorator" not in result


class TestRemoteFunction:
    """Tests for RemoteFunction dataclass."""

    def test_creation(self) -> None:
        rf = RemoteFunction(
            name="test",
            source="def test(): pass",
        )
        assert rf.name == "test"

    def test_call_expr(self) -> None:
        rf = RemoteFunction(
            name="my_func",
            source="def my_func(): pass",
        )
        assert rf.call_expr() == "my_func(*__choppa_args, **__choppa_kwargs)"


class TestRemoteErrors:
    """Tests for exception classes."""

    def test_basic_error(self) -> None:
        err = RemoteError("Test error")
        assert str(err) == "Test error"

    def test_execution_failed(self) -> None:
        err = RemoteExecutionFailed(
            message="Something went wrong",
            traceback="Traceback...",
            output="Full output",
        )
        assert err.remote_message == "Something went wrong"
        assert err.remote_traceback == "Traceback..."
        assert "Remote traceback" in str(err)

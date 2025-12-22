"""Unit tests for choppa core functionality."""

from __future__ import annotations

import pytest

from choppa import (
    ArtifactRef,
    RemoteError,
    RemoteExecutionFailed,
    RemoteFunction,
    RemoteResultTooLargeError,
)
from choppa._internal import _now_utc_day, _safe_name, _strip_leading_decorators
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

    def test_config_file_profile_from_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
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

    def test_config_file_default_profile(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
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

    def test_no_cluster_id_raises_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        """ValueError raised when no cluster_id can be resolved."""
        # Empty config file (no cluster_id)
        config_file = tmp_path / ".databrickscfg"
        config_file.write_text("[DEFAULT]\nhost = https://example.com\n")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("DATABRICKS_CLUSTER_ID", raising=False)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        with pytest.raises(ValueError, match="No cluster_id provided"):
            _resolve_cluster_id(None)

    def test_missing_config_file_continues(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Missing config file doesn't raise, just returns None."""
        # Point to empty directory (no config file)
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        monkeypatch.delenv("DATABRICKS_CONFIG_PROFILE", raising=False)

        result = _read_cluster_id_from_config()
        assert result is None

    def test_profile_env_priority_over_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
    ) -> None:
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


class TestResultSizeMaxValidation:
    """Tests for result_size_max parameter validation."""

    def test_none_is_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """result_size_max=None is valid (unlimited inline)."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "test-cluster")
        from choppa import Choppa

        # Should not raise
        choppa = Choppa(result_size_max=None)
        assert choppa.result_size_max is None

    def test_positive_is_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Positive result_size_max is valid."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "test-cluster")
        from choppa import Choppa

        choppa = Choppa(result_size_max=1024)
        assert choppa.result_size_max == 1024

    def test_zero_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """result_size_max=0 raises ValueError."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "test-cluster")
        from choppa import Choppa

        with pytest.raises(ValueError, match="result_size_max must be > 0 or None"):
            Choppa(result_size_max=0)

    def test_negative_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Negative result_size_max raises ValueError."""
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "test-cluster")
        from choppa import Choppa

        with pytest.raises(ValueError, match="result_size_max must be > 0 or None"):
            Choppa(result_size_max=-100)


class TestSafeName:
    """Tests for safe name generation."""

    def test_simple_name(self) -> None:
        assert _safe_name("foo") == "foo"

    def test_special_chars_replaced(self) -> None:
        assert _safe_name("foo@bar#baz") == "foo_bar_baz"

    def test_empty_becomes_func(self) -> None:
        assert _safe_name("@#$") == "func"


class TestStripLeadingDecorators:
    """Tests for function source extraction."""

    def test_strips_decorators(self) -> None:
        source = "@decorator\ndef foo(): pass"
        result = _strip_leading_decorators(source)
        assert result.startswith("def")
        assert "@decorator" not in result


class TestNowUtcDay:
    """Tests for UTC date generation."""

    def test_format(self) -> None:
        day = _now_utc_day()
        assert len(day) == 8  # YYYYMMDD
        assert day.isdigit()


class TestArtifactRef:
    """Tests for ArtifactRef dataclass."""

    def test_str_representation(self) -> None:
        ref = ArtifactRef(
            path="/Users/test/artifact.pklz",
            fuse_path="/Workspace/Users/test/artifact.pklz",
            artifact_bytes=100,
        )
        s = str(ref)
        assert "path=" in s
        assert "fuse_path=" in s
        assert "bytes=100" in s

    def test_fuse_path(self) -> None:
        ref = ArtifactRef(
            path="/Users/test/artifact.pklz",
            fuse_path="/Workspace/Users/test/artifact.pklz",
        )
        assert ref.fuse_path == "/Workspace/Users/test/artifact.pklz"

    def test_fuse_path_already_workspace(self) -> None:
        ref = ArtifactRef(
            path="/Workspace/Users/test/artifact.pklz",
            fuse_path="/Workspace/Users/test/artifact.pklz",
        )
        assert ref.fuse_path == "/Workspace/Users/test/artifact.pklz"

    def test_immutable(self) -> None:
        ref = ArtifactRef(
            path="/test",
            fuse_path="/Workspace/test",
        )
        with pytest.raises(AttributeError):
            ref.path = "/other"  # type: ignore[misc]


class TestRemoteFunction:
    """Tests for RemoteFunction dataclass."""

    def test_creation(self) -> None:
        rf = RemoteFunction(
            name="test",
            source="def test(): pass",
            artifacts=False,
        )
        assert rf.name == "test"
        assert not rf.artifacts

    def test_call_expr(self) -> None:
        rf = RemoteFunction(
            name="my_func",
            source="def my_func(): pass",
            artifacts=False,
        )
        assert rf.call_expr() == "my_func(*__choppa_args, **__choppa_kwargs)"
        assert not rf.artifacts


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

    def test_too_large_error(self) -> None:
        ref = ArtifactRef(
            path="/test.pklz",
            fuse_path="/Workspace/test.pklz",
            artifact_bytes=1000000,
        )
        err = RemoteResultTooLargeError(
            artifact=ref,
            inline_bytes=1000000,
            result_size_max=256000,
        )
        assert err.artifact == ref
        assert err.result_size_max == 256000
        assert "too large" in str(err).lower()

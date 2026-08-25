"""Configuration and cluster lifecycle tests."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute

from choppa import Choppa
from choppa.choppa import _read_cluster_id_from_config, _resolve_cluster_id
from tests.fakes import FakeWorkspace


def _clear_cluster_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("DATABRICKS_CLUSTER_ID", "DATABRICKS_CONFIG_PROFILE", "DATABRICKS_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)


def _write_config(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


class TestClusterIdResolution:
    """Cluster resolution must be deterministic and profile-atomic."""

    def test_explicit_parameter_takes_priority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster")
        assert _resolve_cluster_id("explicit-cluster") == "explicit-cluster"

    def test_environment_precedes_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        _write_config(tmp_path / ".databrickscfg", "[DEFAULT]\ncluster_id = config-cluster\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CLUSTER_ID", "env-cluster")
        assert _resolve_cluster_id(None) == "env-cluster"

    def test_selected_profile_is_used(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        _write_config(
            tmp_path / ".databrickscfg",
            "[DEFAULT]\ncluster_id = default-cluster\n[research]\ncluster_id = research-cluster\n",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "research")
        assert _read_cluster_id_from_config() == "research-cluster"

    def test_selected_profile_does_not_fall_back(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        _write_config(
            tmp_path / ".databrickscfg",
            "[DEFAULT]\ncluster_id = default-cluster\n[research]\nhost = https://example.databricks.com\n",
        )
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "research")
        assert _read_cluster_id_from_config() is None

    def test_missing_selected_profile_does_not_fall_back(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        _write_config(tmp_path / ".databrickscfg", "[DEFAULT]\ncluster_id = default-cluster\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        monkeypatch.setenv("DATABRICKS_CONFIG_PROFILE", "missing")
        assert _read_cluster_id_from_config() is None

    def test_default_profile_is_used_without_selection(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        _write_config(tmp_path / ".databrickscfg", "[DEFAULT]\ncluster_id = default-cluster\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _read_cluster_id_from_config() == "default-cluster"

    def test_custom_config_file_is_respected(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        config_path = tmp_path / "custom-config"
        _write_config(config_path, "[DEFAULT]\ncluster_id = custom-cluster\n")
        monkeypatch.setenv("DATABRICKS_CONFIG_FILE", str(config_path))
        assert _read_cluster_id_from_config() == "custom-cluster"

    def test_malformed_config_returns_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        config_path = tmp_path / ".databrickscfg"
        _write_config(config_path, "not a valid config")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _read_cluster_id_from_config() is None

    def test_missing_cluster_raises_clear_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        with pytest.raises(ValueError, match="No cluster_id provided"):
            _resolve_cluster_id(None)


class TestChoppaConfiguration:
    """Validate configuration and explicit cluster lifecycle operations."""

    def test_result_size_limit_must_be_positive(self) -> None:
        fake = FakeWorkspace()
        with pytest.raises(ValueError, match="greater than zero"):
            Choppa(cluster_id="cluster", result_size_max=0, w=cast(WorkspaceClient, fake))

    def test_argument_size_limit_must_be_positive(self) -> None:
        fake = FakeWorkspace()
        with pytest.raises(ValueError, match="greater than zero"):
            Choppa(cluster_id="cluster", argument_size_max=0, w=cast(WorkspaceClient, fake))

    def test_session_requires_cluster_before_api_call(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _clear_cluster_environment(monkeypatch)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        fake = FakeWorkspace()
        client = Choppa(w=cast(WorkspaceClient, fake))
        with pytest.raises(ValueError, match="No cluster_id configured"), client.session():
            pass
        assert fake.command_execution.events == []

    @pytest.mark.parametrize(
        ("state", "expected_operation"),
        [
            (compute.State.TERMINATED, "start"),
            (compute.State.PENDING, "wait"),
            (compute.State.RUNNING, None),
        ],
    )
    def test_ensure_cluster_running_is_explicit(
        self,
        state: compute.State,
        expected_operation: str | None,
    ) -> None:
        fake = FakeWorkspace()
        fake.clusters.state = state
        client = Choppa(
            cluster_id="cluster-a",
            timeout=timedelta(seconds=30),
            w=cast(WorkspaceClient, fake),
        )
        client.ensure_cluster_running()
        operations = [operation for operation, _ in fake.clusters.events]
        if expected_operation is None:
            assert operations == ["get"]
        else:
            assert operations == ["get", expected_operation]

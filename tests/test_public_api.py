"""Public package and README workflow tests."""

from __future__ import annotations

from importlib.metadata import version
from typing import cast

import pytest
from databricks.sdk import WorkspaceClient

import choppa
from choppa import Choppa
from tests.fakes import FakeWorkspace


def test_runtime_version_matches_distribution() -> None:
    assert choppa.__version__ == version("choppa")


def test_expected_public_exports() -> None:
    expected = {
        "Choppa",
        "RemoteArgumentsTooLarge",
        "RemoteError",
        "RemoteExecutionFailed",
        "RemoteFunction",
        "RemoteOutputTruncated",
        "RemoteProtocolError",
        "RemoteResultTooLarge",
        "RemoteSession",
        "__version__",
        "remote",
        "session",
        "set_cluster",
    }
    assert set(choppa.__all__) == expected


def test_readme_quickstart(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeWorkspace("readme")
    default = Choppa(cluster_id="cluster", w=cast(WorkspaceClient, fake))
    monkeypatch.setattr(choppa, "_default_choppa", default)

    @choppa.remote
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3

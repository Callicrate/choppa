"""Integration test stubs for choppa.

These tests require explicitly authorized, disposable classic compute. They
run only when CHOPPA_RUN_INTEGRATION=1 and CHOPPA_TEST_CLUSTER_ID is set.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CHOPPA_RUN_INTEGRATION") != "1" or not os.environ.get("CHOPPA_TEST_CLUSTER_ID"),
        reason="Set CHOPPA_RUN_INTEGRATION=1 and CHOPPA_TEST_CLUSTER_ID to opt in",
    ),
]


def _cluster_id() -> str:
    """Return the explicitly authorized integration-test cluster."""
    cluster_id = os.environ.get("CHOPPA_TEST_CLUSTER_ID")
    if not cluster_id:
        raise RuntimeError("CHOPPA_TEST_CLUSTER_ID is required")
    return cluster_id


class TestRemoteExecution:
    """Integration tests for remote execution."""

    def test_simple_function(self) -> None:
        """Test basic remote function execution."""
        from choppa import Choppa

        choppa = Choppa(cluster_id=_cluster_id())

        @choppa.remote
        def add(a: int, b: int) -> int:
            return a + b

        result = add(1, 2)
        assert result == 3

    def test_session_reuse(self) -> None:
        """Test that session context manager works."""
        from choppa import Choppa

        choppa = Choppa(cluster_id=_cluster_id())

        @choppa.remote
        def double(x: int) -> int:
            return x * 2

        with choppa.session():
            assert double(5) == 10
            assert double(10) == 20

    def test_remote_exception(self) -> None:
        """Test remote exception reconstruction and context cleanup."""
        from choppa import Choppa, RemoteExecutionFailed

        choppa = Choppa(cluster_id=_cluster_id())

        @choppa.remote
        def fail() -> None:
            raise ValueError("expected live failure")

        with pytest.raises(RemoteExecutionFailed, match="expected live failure"):
            fail()

    def test_result_size_limit(self) -> None:
        """Test explicit oversized-result handling against the live service."""
        from choppa import Choppa, RemoteResultTooLarge

        choppa = Choppa(cluster_id=_cluster_id(), result_size_max=128)

        @choppa.remote
        def large_result() -> str:
            return "x" * 1_000

        with pytest.raises(RemoteResultTooLarge):
            large_result()

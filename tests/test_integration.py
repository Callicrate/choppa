"""Integration test stubs for choppa.

These tests require a running Databricks cluster and are skipped by default.
Set CHOPPA_TEST_CLUSTER_ID environment variable to run them.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("CHOPPA_TEST_CLUSTER_ID"),
    reason="CHOPPA_TEST_CLUSTER_ID not set",
)


class TestRemoteExecution:
    """Integration tests for remote execution."""

    def test_simple_function(self) -> None:
        """Test basic remote function execution."""
        from choppa import Choppa

        choppa = Choppa()

        @choppa.remote
        def add(a: int, b: int) -> int:
            return a + b

        result = add(1, 2)
        assert result == 3

    def test_session_reuse(self) -> None:
        """Test that session context manager works."""
        from choppa import Choppa

        choppa = Choppa()

        @choppa.remote
        def double(x: int) -> int:
            return x * 2

        with choppa.session():
            assert double(5) == 10
            assert double(10) == 20

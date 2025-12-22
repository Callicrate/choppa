"""Test that matches the README usage example."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def _has_cluster_id() -> bool:
    """Check if cluster_id is available from env or config."""
    if os.environ.get("CHOPPA_TEST_CLUSTER_ID") or os.environ.get("DATABRICKS_CLUSTER_ID"):
        return True
    # Check databrickscfg
    config_path = Path.home() / ".databrickscfg"
    if config_path.exists():
        content = config_path.read_text()
        if "cluster_id" in content:
            return True
    return False


pytestmark = pytest.mark.skipif(
    not _has_cluster_id(),
    reason="No cluster ID available (set DATABRICKS_CLUSTER_ID or add cluster_id to ~/.databrickscfg)",
)


class TestReadmeUsage:
    """Test the exact usage example from README."""

    def test_basic_usage_example(self) -> None:
        """Test the basic usage example from README.md Usage section."""
        from choppa import Choppa

        dutch = Choppa()

        @dutch.remote
        def add(a: int, b: int) -> int:
            return a + b

        result = add(1, 2)
        assert result == 3

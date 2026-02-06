"""
Choppa: Get to da cluster!

Remote function execution for Databricks clusters via the Command Execution API.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, ParamSpec, TypeVar

from choppa._version import __version__
from choppa.choppa import Choppa, _read_cluster_id_from_env
from choppa.codegen import RemoteFunction
from choppa.errors import RemoteError, RemoteExecutionFailed
from choppa.session import RemoteSession

__all__ = [
    "Choppa",
    "RemoteError",
    "RemoteExecutionFailed",
    "RemoteFunction",
    "RemoteSession",
    "__version__",
    "remote",
    "session",
    "set_cluster",
]

if TYPE_CHECKING:
    from choppa.session import RemoteSession as _RemoteSessionType

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

_default_choppa: Choppa | None = None


def _discover_cluster_id() -> str | None:
    """Attempt to resolve a cluster ID at import time without raising."""
    return _read_cluster_id_from_env()


_discovered_cluster_id = _discover_cluster_id()

if _discovered_cluster_id is None:
    logger.warning(
        "No Databricks cluster ID found. Set DATABRICKS_CLUSTER_ID, "
        "configure a profile in ~/.databrickscfg, or call "
        "choppa.set_cluster(cluster_id='...')"
    )


def _get_default() -> Choppa:
    """Lazily initialize the default Choppa instance."""
    global _default_choppa
    if _default_choppa is None:
        _default_choppa = Choppa(cluster_id=_discovered_cluster_id)
    return _default_choppa


def remote(
    fn: Callable[P, R] | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
    """
    Decorator to run a function remotely on the Databricks cluster.

    Uses a default Choppa instance with cluster resolution from environment.

    Example:
        import choppa

        @choppa.remote
        def add(a: int, b: int) -> int:
            return a + b

        add(1, 2)  # 3
    """
    return _get_default().remote(fn)


def session() -> _RemoteSessionType:
    """
    Create a session for reusing execution context across multiple calls.

    Uses a default Choppa instance with cluster resolution from environment.

    Example:
        import choppa

        @choppa.remote
        def add(a: int, b: int) -> int:
            return a + b

        with choppa.session():
            results = [add(i, 1) for i in range(100)]
    """
    return _get_default().session()


def set_cluster(cluster_id: str | None = None) -> None:
    """Change the target cluster for the default Choppa instance.

    Args:
        cluster_id: New cluster ID, or None to re-resolve from environment/config

    Raises:
        ValueError: If no cluster ID can be resolved

    Example:
        import choppa

        choppa.set_cluster("0123-456789-abcdef")
    """
    _get_default().set_cluster(cluster_id)

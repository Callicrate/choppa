"""
Choppa: Get to da cluster!

Remote function execution for Databricks clusters via the Command Execution API.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ParamSpec, TypeVar, overload

from choppa._version import __version__
from choppa.choppa import Choppa
from choppa.codegen import RemoteFunction
from choppa.errors import (
    RemoteArgumentsTooLarge,
    RemoteError,
    RemoteExecutionFailed,
    RemoteOutputTruncated,
    RemoteProtocolError,
    RemoteResultTooLarge,
)
from choppa.session import RemoteSession

__all__ = [
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
]

P = ParamSpec("P")
R = TypeVar("R")

_default_choppa: Choppa | None = None


def _get_default() -> Choppa:
    """Lazily initialize the default Choppa instance."""
    global _default_choppa
    if _default_choppa is None:
        _default_choppa = Choppa()
    return _default_choppa


@overload
def remote(fn: Callable[P, R], /) -> Callable[P, R]: ...


@overload
def remote(fn: None = None, /) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


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


def session() -> RemoteSession:
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

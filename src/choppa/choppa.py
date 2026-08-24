"""Main Choppa class for remote execution."""

from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Callable
from configparser import ConfigParser
from configparser import Error as ConfigError
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar, overload

from databricks.sdk import WorkspaceClient

from choppa._internal import _strip_leading_decorators
from choppa.codegen import RemoteFunction

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(__name__)


def _read_cluster_id_from_env() -> str | None:
    """
    Resolve cluster ID from environment / config without raising.

    Resolution order:
    1. DATABRICKS_CLUSTER_ID environment variable
    2. cluster_id from databricks config file profile:
       a. Profile from DATABRICKS_CONFIG_PROFILE env var
       b. DEFAULT profile

    Returns:
        Resolved cluster ID, or None if not found
    """
    env_cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
    if env_cluster_id:
        return env_cluster_id

    return _read_cluster_id_from_config()


def _resolve_cluster_id(cluster_id: str | None) -> str:
    """
    Resolve cluster ID, raising if none is found.

    Args:
        cluster_id: Explicitly provided cluster ID, or None to resolve

    Returns:
        Resolved cluster ID

    Raises:
        ValueError: If no cluster ID can be resolved from any source
    """
    if cluster_id:
        return cluster_id

    resolved = _read_cluster_id_from_env()
    if resolved:
        return resolved

    raise ValueError(
        "No cluster_id provided and could not resolve from environment.\n"
        "Options:\n"
        "  1. Pass cluster_id to Choppa(cluster_id='...')\n"
        "  2. Set DATABRICKS_CLUSTER_ID environment variable\n"
        "  3. Add cluster_id to your ~/.databrickscfg profile"
    )


def _read_cluster_id_from_config() -> str | None:
    """
    Read cluster_id from Databricks config file.

    If DATABRICKS_CONFIG_PROFILE is set, only that profile is read. Otherwise,
    the DEFAULT profile is used. DATABRICKS_CONFIG_FILE overrides the path.

    Returns:
        cluster_id if found, None otherwise
    """
    configured_path = os.environ.get("DATABRICKS_CONFIG_FILE")
    config_path = Path(configured_path).expanduser() if configured_path else Path.home() / ".databrickscfg"
    if not config_path.exists():
        return None

    try:
        # Databricks uses a literal [DEFAULT] profile. Disable ConfigParser's
        # implicit default inheritance so named profiles cannot borrow from it.
        config = ConfigParser(default_section="__choppa_implicit_defaults__")
        with config_path.open(encoding="utf-8") as config_file:
            config.read_file(config_file)

        profile_name = os.environ.get("DATABRICKS_CONFIG_PROFILE")
        if profile_name:
            if profile_name not in config:
                return None
            return config.get(profile_name, "cluster_id", fallback=None)

        return config.get("DEFAULT", "cluster_id", fallback=None)
    except (OSError, UnicodeError, ConfigError):
        logger.debug("Could not read Databricks config file %s", config_path, exc_info=True)

    return None


@dataclass
class Choppa:
    """
    Get to da cluster!

    High-level interface for remote function execution on Databricks.
    Provides a decorator for marking functions as remote and session management.
    """

    cluster_id: str | None = None
    timeout: timedelta = timedelta(minutes=20)
    argument_size_max: int = 256_000
    result_size_max: int = 256_000
    w: WorkspaceClient | None = None

    def __post_init__(self) -> None:
        if self.argument_size_max <= 0:
            raise ValueError("argument_size_max must be greater than zero")
        if self.result_size_max <= 0:
            raise ValueError("result_size_max must be greater than zero")
        if self.cluster_id is None:
            self.cluster_id = _read_cluster_id_from_env()
        if self.w is None:
            self.w = WorkspaceClient()

    def _client_and_cluster(self) -> tuple[WorkspaceClient, str]:
        """Return the initialized client and target cluster, or fail clearly."""
        if self.w is None:
            raise RuntimeError("WorkspaceClient not initialized")
        if not self.cluster_id:
            raise ValueError(
                "No cluster_id configured. Set DATABRICKS_CLUSTER_ID, add cluster_id to the selected "
                "Databricks profile, or call choppa.set_cluster(cluster_id='...')."
            )
        return self.w, self.cluster_id

    def set_cluster(self, cluster_id: str | None = None) -> None:
        """
        Change the target cluster for remote execution.

        Args:
            cluster_id: New cluster ID, or None to resolve from environment/config

        Raises:
            ValueError: If no cluster ID can be resolved
        """
        self.cluster_id = _resolve_cluster_id(cluster_id)

    def ensure_cluster_running(self) -> None:
        """
        Check if the cluster is running and start it if not.

        Blocks until the cluster reaches RUNNING state.

        Raises:
            RuntimeError: If WorkspaceClient is not initialized
            ValueError: If cluster_id is not set
        """
        from databricks.sdk.service.compute import State

        client, cluster_id = self._client_and_cluster()

        cluster = client.clusters.get(cluster_id)

        if cluster.state == State.RUNNING:
            return

        if cluster.state in (State.TERMINATED, State.TERMINATING, State.ERROR, State.UNKNOWN):
            client.clusters.start_and_wait(cluster_id)
        elif cluster.state in (State.PENDING, State.RESTARTING, State.RESIZING):
            client.clusters.wait_get_cluster_running(cluster_id)

    def session(self) -> RemoteSession:
        """Create a session for reusing execution context across multiple calls."""
        from choppa.session import RemoteSession

        return RemoteSession(self)

    @overload
    def remote(self, fn: Callable[P, R], /) -> Callable[P, R]: ...

    @overload
    def remote(self, fn: None = None, /) -> Callable[[Callable[P, R]], Callable[P, R]]: ...

    def remote(
        self,
        fn: Callable[P, R] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
        """
        Decorator to run a function remotely on the Databricks cluster.

        The decorated function runs on the cluster and returns the result.
        """
        from choppa.session import _current_session

        def decorate(func: Callable[P, R]) -> Callable[P, R]:
            if getattr(func, "__choppa_remote__", None) is not None:
                raise TypeError("Do not stack choppa decorators.")
            if inspect.iscoroutinefunction(func):
                raise TypeError("Async functions are not supported by @choppa.remote.")
            if func.__code__.co_freevars:
                names = ", ".join(func.__code__.co_freevars)
                raise TypeError(f"Remote functions cannot close over local variables: {names}")

            try:
                src = _strip_leading_decorators(inspect.getsource(func))
            except (OSError, TypeError) as exc:
                raise RuntimeError("inspect.getsource() failed. Define the function in a normal .py file.") from exc

            remote_def: RemoteFunction[P, R] = RemoteFunction(name=func.__name__, source=src)

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                self._client_and_cluster()
                sess = _current_session.get()
                if sess is not None and sess.choppa is self:
                    return sess.call(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call(remote_def, *args, **kwargs)

            wrapper.__choppa_remote__ = remote_def  # type: ignore[attr-defined]
            return wrapper

        return decorate if fn is None else decorate(fn)


from choppa.session import RemoteSession  # noqa: E402

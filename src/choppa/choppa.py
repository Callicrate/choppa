"""Main Choppa class for remote execution."""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import ParamSpec, TypeVar

from databricks.sdk import WorkspaceClient

from choppa._internal import _strip_leading_decorators
from choppa.codegen import RemoteFunction

P = ParamSpec("P")
R = TypeVar("R")


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

    Checks profile specified by DATABRICKS_CONFIG_PROFILE env var first,
    then falls back to DEFAULT profile.

    Returns:
        cluster_id if found, None otherwise
    """
    config_path = Path.home() / ".databrickscfg"
    if not config_path.exists():
        return None

    try:
        import configparser

        config = configparser.ConfigParser()
        config.read(config_path)

        profile_name = os.environ.get("DATABRICKS_CONFIG_PROFILE")
        if profile_name and profile_name in config:
            cluster_id = config.get(profile_name, "cluster_id", fallback=None)
            if cluster_id:
                return cluster_id

        if "DEFAULT" in config:
            cluster_id = config.get("DEFAULT", "cluster_id", fallback=None)
            if cluster_id:
                return cluster_id

    except Exception:
        pass

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
    w: WorkspaceClient | None = None

    def __post_init__(self) -> None:
        if self.cluster_id is None:
            self.cluster_id = _read_cluster_id_from_env()
        if self.w is None:
            self.w = WorkspaceClient()

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

        if self.w is None:
            raise RuntimeError("WorkspaceClient not initialized")

        if self.cluster_id is None:
            raise ValueError("cluster_id is not set")

        cluster = self.w.clusters.get(self.cluster_id)

        if cluster.state == State.RUNNING:
            return

        if cluster.state in (State.TERMINATED, State.TERMINATING, State.ERROR, State.UNKNOWN):
            self.w.clusters.start_and_wait(self.cluster_id)
        elif cluster.state in (State.PENDING, State.RESTARTING, State.RESIZING):
            self.w.clusters.wait_get_cluster_running(self.cluster_id)

    def session(self) -> RemoteSession:
        """Create a session for reusing execution context across multiple calls."""
        from choppa.session import RemoteSession

        return RemoteSession(self)

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

            try:
                src = _strip_leading_decorators(inspect.getsource(func))
            except OSError as e:
                raise RuntimeError("inspect.getsource() failed. Define the function in a normal .py file.") from e

            remote_def = RemoteFunction(name=func.__name__, source=src)

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                if not self.cluster_id:
                    raise ValueError(
                        "No cluster_id configured. "
                        "Set DATABRICKS_CLUSTER_ID, add cluster_id to "
                        "~/.databrickscfg, or call choppa.set_cluster(cluster_id='...')"
                    )
                sess = _current_session.get()
                if sess is not None:
                    return sess.call(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call(remote_def, *args, **kwargs)

            wrapper.__choppa_remote__ = remote_def
            return wrapper

        return decorate if fn is None else decorate(fn)


# Import for type hints only - avoid circular import at runtime
from choppa.session import RemoteSession

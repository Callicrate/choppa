"""Main Choppa class for remote execution."""

from __future__ import annotations

import inspect
import os
import textwrap
import uuid
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute
from databricks.sdk.service import workspace as ws

from choppa._internal import _normalize_artifact_dir, _now_utc_day, _safe_name, _strip_leading_decorators
from choppa.artifacts import (
    ArtifactRef,
    _require_cloudpickle_local,
    _restore_refs_local,
)
from choppa.codegen import RemoteFunction, _build_invoke_code
from choppa.errors import RemoteError

P = ParamSpec("P")
R = TypeVar("R")


def _resolve_cluster_id(cluster_id: str | None) -> str:
    """
    Resolve cluster ID from multiple sources in priority order.

    Resolution order:
    1. Explicit parameter (if provided)
    2. DATABRICKS_CLUSTER_ID environment variable
    3. cluster_id from databricks config file profile:
       a. Profile from DATABRICKS_CONFIG_PROFILE env var
       b. DEFAULT profile

    Args:
        cluster_id: Explicitly provided cluster ID, or None to resolve

    Returns:
        Resolved cluster ID

    Raises:
        ValueError: If no cluster ID can be resolved from any source
    """
    # 1. Explicit parameter takes highest priority
    if cluster_id:
        return cluster_id

    # 2. Environment variable
    env_cluster_id = os.environ.get("DATABRICKS_CLUSTER_ID")
    if env_cluster_id:
        return env_cluster_id

    # 3. Databricks config file
    config_cluster_id = _read_cluster_id_from_config()
    if config_cluster_id:
        return config_cluster_id

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

        # Check profile from env var first
        profile_name = os.environ.get("DATABRICKS_CONFIG_PROFILE")
        if profile_name and profile_name in config:
            cluster_id = config.get(profile_name, "cluster_id", fallback=None)
            if cluster_id:
                return cluster_id

        # Fall back to DEFAULT profile
        if "DEFAULT" in config:
            cluster_id = config.get("DEFAULT", "cluster_id", fallback=None)
            if cluster_id:
                return cluster_id

    except Exception:
        # Config parsing failed, continue to next resolution method
        pass

    return None


@dataclass
class Choppa:
    """
    Get to da cluster!

    High-level interface for remote function execution on Databricks.
    Provides decorators for marking functions as remote, session management,
    and artifact storage configuration.
    """

    cluster_id: str | None = None
    timeout: timedelta = timedelta(minutes=20)
    artifact_dir: str | None = None
    result_size_max: int | None = 256 * 1024  # 256 KiB, or None to always return inline
    w: WorkspaceClient | None = None

    def __post_init__(self) -> None:
        # Resolve cluster_id from multiple sources and update the field
        self.cluster_id = _resolve_cluster_id(self.cluster_id)

        if self.w is None:
            self.w = WorkspaceClient()

        # Initialize artifact paths only if artifact_dir is configured
        if self.artifact_dir is not None:
            self._artifact_dir_fuse, self._artifact_dir_api = _normalize_artifact_dir(self.artifact_dir)
            # best-effort ensure directory exists in workspace namespace
            try:
                self.w.workspace.mkdirs(self._artifact_dir_api)
            except Exception:
                pass
        else:
            self._artifact_dir_fuse: str | None = None
            self._artifact_dir_api: str | None = None

        if self.result_size_max is not None and self.result_size_max <= 0:
            raise ValueError("result_size_max must be > 0 or None")

    def session(self) -> RemoteSession:
        """Create a session for reusing execution context across multiple calls."""
        from choppa.session import RemoteSession

        return RemoteSession(self)

    # ----- decorators -----

    def remote(
        self,
        fn: Callable[P, R] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, R]] | Callable[P, R]:
        """
        Sync remote call that returns a python value inline when small enough.
        ArtifactRef arguments are auto-loaded on the cluster (unless param opts out).
        """
        from choppa.session import _current_session

        def decorate(func: Callable[P, R]) -> Callable[P, R]:
            if getattr(func, "__choppa_remote__", None) is not None:
                raise TypeError(
                    "Do not stack choppa decorators. "
                    "Choose exactly one of: @choppa.remote, @choppa.artifact, @choppa.submit"
                )

            try:
                src = _strip_leading_decorators(inspect.getsource(func))
            except OSError as e:
                raise RuntimeError(
                    "inspect.getsource() failed. Define the function in a normal .py file "
                    "or use choppa.from_source(...)."
                ) from e

            remote_def = RemoteFunction(name=func.__name__, source=src, artifacts=False)

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                sess = _current_session.get()
                if sess is not None:
                    return sess.call_value(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call_value(remote_def, *args, **kwargs)

            wrapper.__choppa_remote__ = remote_def
            return wrapper

        return decorate if fn is None else decorate(fn)

    def artifact(
        self,
        fn: Callable[P, R] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, ArtifactRef]] | Callable[P, ArtifactRef]:
        """
        Sync remote call that always stores result in artifacts and returns an ArtifactRef.
        ArtifactRef arguments are auto-loaded on the cluster (unless param opts out).
        """
        from choppa.session import _current_session

        def decorate(func: Callable[P, R]) -> Callable[P, ArtifactRef]:
            if getattr(func, "__choppa_remote__", None) is not None:
                raise TypeError(
                    "Do not stack choppa decorators. "
                    "Choose exactly one of: @choppa.remote, @choppa.artifact, @choppa.submit"
                )

            try:
                src = _strip_leading_decorators(inspect.getsource(func))
            except OSError as e:
                raise RuntimeError(
                    "inspect.getsource() failed. Define the function in a normal .py file "
                    "or use choppa.from_source(...)."
                ) from e

            remote_def = RemoteFunction(name=func.__name__, source=src, artifacts=True)

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> ArtifactRef:
                sess = _current_session.get()
                if sess is not None:
                    return sess.call_artifact(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call_artifact(remote_def, *args, **kwargs)

            wrapper.__choppa_remote__ = remote_def
            return wrapper

        return decorate if fn is None else decorate(fn)

    def submit(
        self,
        fn: Callable[P, R] | None = None,
    ) -> Callable[[Callable[P, R]], Callable[P, RemoteHandle]] | Callable[P, RemoteHandle]:
        """
        ASYNC decorator: calling the function returns a RemoteHandle immediately.
        Async calls ALWAYS store results in artifacts; handle yields an ArtifactRef.
        """

        def decorate(func: Callable[P, R]) -> Callable[P, RemoteHandle]:
            if getattr(func, "__choppa_remote__", None) is not None:
                raise TypeError(
                    "Do not stack choppa decorators. "
                    "Choose exactly one of: @choppa.remote, @choppa.artifact, @choppa.submit"
                )

            try:
                src = _strip_leading_decorators(inspect.getsource(func))
            except OSError as e:
                raise RuntimeError(
                    "inspect.getsource() failed. Define the function in a normal .py file "
                    "or use choppa.from_source(...)."
                ) from e

            remote_def = RemoteFunction(name=func.__name__, source=src, artifacts=True)

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> RemoteHandle:
                return self._start_async(remote_def, args, kwargs)

            wrapper.__choppa_remote__ = remote_def
            return wrapper

        return decorate if fn is None else decorate(fn)

    # ----- artifacts: download + deserialize (LOCAL) -----

    def dereference(
        self,
        ref_or_path: ArtifactRef | str,
    ) -> Any:
        """Download and deserialize an artifact from Workspace Files."""
        if isinstance(ref_or_path, ArtifactRef):
            path = ref_or_path.path
        else:
            path = ref_or_path

        if path.startswith("/Workspace/"):
            path = path[len("/Workspace") :]

        with self.w.workspace.download(path, format=ws.ExportFormat.AUTO) as f:
            data = f.read()

        # Always use pickle-zlib
        cloudpickle = _require_cloudpickle_local()
        return _restore_refs_local(cloudpickle.loads(zlib.decompress(data)))

    # ----- optional: define from source (REPL/notebook fallback) -----

    def from_source(
        self,
        *,
        name: str,
        source: str,
        mode: Literal["remote", "artifact", "submit"] = "remote",
    ) -> Callable[..., Any]:
        """Create a remote function from source code string."""
        from choppa.session import _current_session

        src = textwrap.dedent(source).rstrip() + "\n"

        if mode == "remote":
            remote_def = RemoteFunction(name=name, source=src, artifacts=False)

            def f(*args: Any, **kwargs: Any) -> Any:
                sess = _current_session.get()
                if sess is not None:
                    return sess.call_value(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call_value(remote_def, *args, **kwargs)

            f.__choppa_remote__ = remote_def
            return f

        if mode == "artifact":
            remote_def = RemoteFunction(name=name, source=src, artifacts=True)

            def f(*args: Any, **kwargs: Any) -> ArtifactRef:
                sess = _current_session.get()
                if sess is not None:
                    return sess.call_artifact(remote_def, *args, **kwargs)
                with self.session() as s:
                    return s.call_artifact(remote_def, *args, **kwargs)

            f.__choppa_remote__ = remote_def
            return f

        if mode == "submit":
            remote_def = RemoteFunction(name=name, source=src, artifacts=True)

            def f(*args: Any, **kwargs: Any) -> RemoteHandle:
                return self._start_async(remote_def, args, kwargs)

            f.__choppa_remote__ = remote_def
            return f

        raise ValueError(f"Unknown mode: {mode!r}")

    # ----- async internals -----

    def _require_artifact_dir(self, operation: str) -> None:
        """Raise ArtifactDirNotConfiguredError if artifact_dir is not set."""
        from choppa.errors import ArtifactDirNotConfiguredError

        if self._artifact_dir_fuse is None or self._artifact_dir_api is None:
            raise ArtifactDirNotConfiguredError(operation)

    def _artifact_base_paths(self, func_name: str) -> tuple[str | None, str | None]:
        """Generate unique artifact paths for a function invocation.

        Returns (None, None) if artifact_dir is not configured.
        """
        if self._artifact_dir_fuse is None or self._artifact_dir_api is None:
            return None, None

        safe = _safe_name(func_name)
        day = _now_utc_day()
        uid = uuid.uuid4().hex
        rel = f"{safe}/{day}/{uid}"

        base_fuse = f"{self._artifact_dir_fuse}/{rel}"
        base_api = f"{self._artifact_dir_api.rstrip('/')}/{rel}"
        if not base_api.startswith("/"):
            base_api = "/" + base_api
        return base_fuse, base_api

    def _start_async(
        self, remote_def: RemoteFunction[Any, Any], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> RemoteHandle:
        """Start an async remote execution."""
        from choppa.session import RemoteHandle

        ctx = self.w.command_execution.create_and_wait(
            cluster_id=self.cluster_id,
            language=compute.Language.PYTHON,
            timeout=self.timeout,
        )

        base_fuse, base_api = self._artifact_base_paths(remote_def.name)

        code = _build_invoke_code(
            remote_def=remote_def,
            args=tuple(args),
            kwargs=dict(kwargs),
            artifact_base_fuse=base_fuse,
            artifact_base_api=base_api,
            result_size_max=self.result_size_max,
        )

        started = self.w.command_execution.execute(
            cluster_id=self.cluster_id,
            context_id=ctx.id,
            language=compute.Language.PYTHON,
            command=code,
        )

        command_id = getattr(started, "command_id", None) or getattr(started, "commandId", None) or ""
        if not command_id and hasattr(started, "result"):
            try:
                r0 = started.result(timeout=timedelta(seconds=0))  # type: ignore[attr-defined]
                command_id = getattr(r0, "command_id", None) or getattr(r0, "commandId", None) or ""
            except Exception:
                command_id = ""

        if not command_id:
            raise RemoteError(
                "Could not determine command_id for async handle. "
                "Your databricks-sdk version may not support async polling via command_id."
            )

        return RemoteHandle(
            choppa=self,
            cluster_id=self.cluster_id,
            context_id=ctx.id,
            command_id=command_id,
            _owns_context=True,
        )


# Import for type hints only - avoid circular import at runtime
from choppa.session import RemoteHandle, RemoteSession  # noqa: E402

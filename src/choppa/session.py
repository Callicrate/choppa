"""Session and handle classes for choppa."""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from databricks.sdk.service import compute

from choppa._internal import _done, _extract_text
from choppa.artifacts import ArtifactRef, _restore_refs_local, _unpickle_local_b64
from choppa.codegen import _CHOPPA_META_MARKER, RemoteFunction, _build_invoke_code
from choppa.errors import RemoteError, RemoteExecutionFailed, RemoteResultTooLargeError

if TYPE_CHECKING:
    from choppa.choppa import Choppa


_current_session: contextvars.ContextVar[RemoteSession | None] = contextvars.ContextVar(
    "choppa_current_session", default=None
)


def _find_meta(output: str) -> dict[str, Any]:
    """Find and parse the meta marker line from output."""
    for line in reversed(output.splitlines()):
        if line.startswith(_CHOPPA_META_MARKER):
            import json

            payload = line[len(_CHOPPA_META_MARKER) :].strip()
            return json.loads(payload)
    raise RemoteError(f"Remote meta marker not found. Full output:\n{output}")


def _interpret_meta(meta: dict[str, Any], output: str, *, choppa: Choppa) -> Any:
    """Interpret the meta response from remote execution."""
    ok = bool(meta.get("ok", False))
    storage = meta.get("storage")

    if storage == "inline":
        if not ok:
            raise RemoteExecutionFailed(
                message=str(meta.get("error") or "remote_error"),
                traceback=meta.get("traceback"),
                output=output,
            )

        # Always pickle-zlib
        return _restore_refs_local(_unpickle_local_b64(str(meta.get("data"))))

    if storage == "artifact":
        ref = ArtifactRef(
            path=str(meta.get("path")),
            fuse_path=str(meta.get("fuse_path")),
            artifact_bytes=(int(meta["artifact_bytes"]) if meta.get("artifact_bytes") is not None else None),
        )

        if ok:
            return ref

        if meta.get("error") == "too_large":
            raise RemoteResultTooLargeError(
                artifact=ref,
                inline_bytes=int(meta.get("inline_bytes") or -1),
                result_size_max=int(meta.get("result_size_max") or choppa.result_size_max),
            )

        raise RemoteExecutionFailed(
            message=str(meta.get("error") or "remote_error"),
            traceback=meta.get("traceback"),
            output=output,
        )

    raise RemoteError(f"Unrecognized meta format: {meta!r}\nFull output:\n{output}")


@dataclass
class RemoteSession:
    """
    Sync session that reuses a single execution context for multiple calls.

    Use as a context manager via choppa.session().
    """

    choppa: Choppa
    _context_id: str | None = None
    _token: contextvars.Token | None = None

    def __enter__(self) -> RemoteSession:
        ctx = self.choppa.w.command_execution.create_and_wait(
            cluster_id=self.choppa.cluster_id,
            language=compute.Language.PYTHON,
            timeout=self.choppa.timeout,
        )
        self._context_id = ctx.id
        self._token = _current_session.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _current_session.reset(self._token)
            self._token = None

        if self._context_id:
            self.choppa.w.command_execution.destroy(cluster_id=self.choppa.cluster_id, context_id=self._context_id)
            self._context_id = None

    def call_value(self, remote_def: RemoteFunction[Any, Any], *args: Any, **kwargs: Any) -> Any:
        """Execute remote function and return the value."""
        return self._call(remote_def, *args, **kwargs)

    def call_artifact(self, remote_def: RemoteFunction[Any, Any], *args: Any, **kwargs: Any) -> ArtifactRef:
        """Execute remote function and return artifact reference."""
        out = self._call(remote_def, *args, **kwargs)
        if not isinstance(out, ArtifactRef):
            raise RemoteError("Expected ArtifactRef, got inline value. (This should not happen.)")
        return out

    def _call(self, remote_def: RemoteFunction[Any, Any], *args: Any, **kwargs: Any) -> Any:
        if not self._context_id:
            raise RuntimeError("RemoteSession not initialized. Use: with choppa.session(): ...")

        base_fuse, base_api = self.choppa._artifact_base_paths(remote_def.name)

        code = _build_invoke_code(
            remote_def=remote_def,
            args=tuple(args),
            kwargs=dict(kwargs),
            artifact_base_fuse=base_fuse,
            artifact_base_api=base_api,
            result_size_max=self.choppa.result_size_max,
        )

        resp = self.choppa.w.command_execution.execute_and_wait(
            cluster_id=self.choppa.cluster_id,
            context_id=self._context_id,
            language=compute.Language.PYTHON,
            command=code,
            timeout=self.choppa.timeout,
        )

        output = _extract_text(resp)
        meta = _find_meta(output)
        return _interpret_meta(meta, output, choppa=self.choppa)


@dataclass
class RemoteHandle:
    """
    Handle returned by @choppa.submit.

    Use to poll status and retrieve results:
        handle = slow_job()
        ref = handle.wait()  # waits and returns ArtifactRef
        value = choppa.dereference(ref)
    """

    choppa: Choppa
    cluster_id: str
    context_id: str
    command_id: str
    _owns_context: bool = False

    _cached_status: compute.CommandStatusResponse | None = None
    _cached_artifact: ArtifactRef | None = None

    def status(self) -> compute.CommandStatusResponse:
        """Get current command status."""
        st = self.choppa.w.command_execution.command_status(
            cluster_id=self.cluster_id,
            context_id=self.context_id,
            command_id=self.command_id,
        )
        self._cached_status = st
        return st

    def done(self) -> bool:
        """Check if command has finished."""
        st = self._cached_status or self.status()
        return _done(getattr(st, "status", None))

    def wait(
        self,
        *,
        timeout: timedelta | None = None,
        poll_interval_s: float = 2.0,
        cleanup: bool = True,
    ) -> ArtifactRef:
        """Wait for command to complete and return the ArtifactRef."""
        deadline = None
        timeout = timeout or self.choppa.timeout
        if timeout is not None:
            deadline = time.time() + timeout.total_seconds()

        while True:
            st = self.status()
            if _done(getattr(st, "status", None)):
                return self.get_pointer(wait=False, cleanup=cleanup)
            if deadline is not None and time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for remote command {self.command_id}")
            time.sleep(poll_interval_s)

    def get_pointer(
        self,
        *,
        wait: bool = True,
        timeout: timedelta | None = None,
        poll_interval_s: float = 2.0,
        cleanup: bool = True,
    ) -> ArtifactRef:
        """Get the artifact reference for the result."""
        if self._cached_artifact is not None:
            return self._cached_artifact

        if wait and not self.done():
            self.wait(timeout=timeout, poll_interval_s=poll_interval_s)
        elif not self.done():
            raise RuntimeError("Remote call not finished yet.")

        st = self._cached_status or self.status()
        output = _extract_text(st)
        meta = _find_meta(output)
        result = _interpret_meta(meta, output, choppa=self.choppa)

        if not isinstance(result, ArtifactRef):
            raise RemoteError(f"Expected ArtifactRef from async submit, got: {type(result)}")

        self._cached_artifact = result

        if cleanup:
            self.cleanup()

        return result

    def cleanup(self) -> None:
        """Destroy the execution context if owned."""
        if self._owns_context and self.context_id:
            try:
                self.choppa.w.command_execution.destroy(cluster_id=self.cluster_id, context_id=self.context_id)
            finally:
                self._owns_context = False

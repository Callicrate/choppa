"""Session class for choppa."""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from databricks.sdk.service import compute

from choppa._internal import _extract_text
from choppa.codegen import _CHOPPA_META_MARKER, RemoteFunction, _build_invoke_code
from choppa.errors import RemoteError, RemoteExecutionFailed

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


def _interpret_meta(meta: dict[str, Any], output: str) -> Any:
    """Interpret the meta response from remote execution."""
    ok = bool(meta.get("ok", False))

    if not ok:
        raise RemoteExecutionFailed(
            message=str(meta.get("error") or "remote_error"),
            traceback=meta.get("traceback"),
            output=output,
        )

    # Unpickle the result
    import base64
    import zlib

    try:
        import cloudpickle  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "cloudpickle is required locally to deserialize results. Install with: pip install cloudpickle"
        ) from e

    data = str(meta.get("data"))
    b = base64.b64decode(data.encode("ascii"))
    return cloudpickle.loads(zlib.decompress(b))


@dataclass
class RemoteSession:
    """
    Session that reuses a single execution context for multiple calls.

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

    def call(self, remote_def: RemoteFunction, *args: Any, **kwargs: Any) -> Any:
        """Execute remote function and return the value."""
        if not self._context_id:
            raise RuntimeError("RemoteSession not initialized. Use: with choppa.session(): ...")

        code = _build_invoke_code(
            remote_def=remote_def,
            args=tuple(args),
            kwargs=dict(kwargs),
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
        return _interpret_meta(meta, output)

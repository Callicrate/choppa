"""Session class for choppa."""

from __future__ import annotations

import contextvars
import json
import zlib
from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, cast

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import compute

from choppa._internal import _extract_text
from choppa.codegen import _CHOPPA_META_MARKER, RemoteFunction, _build_invoke_code
from choppa.errors import (
    RemoteExecutionFailed,
    RemoteOutputTruncated,
    RemoteProtocolError,
    RemoteResultTooLarge,
)

if TYPE_CHECKING:
    from choppa.choppa import Choppa

P = ParamSpec("P")
R = TypeVar("R")


_current_session: contextvars.ContextVar[RemoteSession | None] = contextvars.ContextVar(
    "choppa_current_session", default=None
)


def _find_meta(output: str) -> dict[str, Any]:
    """Find and parse the meta marker line from output."""
    for line in reversed(output.splitlines()):
        if line.startswith(_CHOPPA_META_MARKER):
            payload = line[len(_CHOPPA_META_MARKER) :].strip()
            try:
                meta = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise RemoteProtocolError("Remote metadata is not valid JSON.") from exc
            if not isinstance(meta, dict):
                raise RemoteProtocolError("Remote metadata must be a JSON object.")
            return cast(dict[str, Any], meta)
    raise RemoteProtocolError(f"Remote meta marker not found. Full output:\n{output}")


def _bounded_decompress(payload: bytes, *, result_size_max: int) -> bytes:
    """Decompress a result without allowing unbounded expansion."""
    decompressor = zlib.decompressobj()
    try:
        result = decompressor.decompress(payload, result_size_max + 1)
        if len(result) > result_size_max or decompressor.unconsumed_tail:
            raise RemoteResultTooLarge(result_bytes=len(result), result_size_max=result_size_max)
        result += decompressor.flush(result_size_max + 1 - len(result))
    except zlib.error as exc:
        raise RemoteProtocolError("Remote result contains invalid compressed data.") from exc

    if len(result) > result_size_max:
        raise RemoteResultTooLarge(result_bytes=len(result), result_size_max=result_size_max)
    if not decompressor.eof or decompressor.unused_data:
        raise RemoteProtocolError("Remote result contains incomplete or trailing compressed data.")
    return result


def _interpret_meta(meta: dict[str, Any], output: str, *, result_size_max: int) -> Any:
    """Interpret the meta response from remote execution."""
    ok = meta.get("ok")
    if not isinstance(ok, bool):
        raise RemoteProtocolError("Remote metadata field 'ok' must be a boolean.")

    if not ok:
        if meta.get("error_type") == "result_too_large":
            result_bytes = meta.get("result_bytes")
            remote_max = meta.get("result_size_max")
            if not isinstance(result_bytes, int) or not isinstance(remote_max, int):
                raise RemoteProtocolError("Remote result-size metadata is invalid.")
            raise RemoteResultTooLarge(result_bytes=result_bytes, result_size_max=remote_max)
        raise RemoteExecutionFailed(
            message=str(meta.get("error") or "remote_error"),
            traceback=(str(meta["traceback"]) if meta.get("traceback") is not None else None),
            output=output,
        )

    import base64
    import binascii

    import cloudpickle  # type: ignore[import-untyped]

    data = meta.get("data")
    if not isinstance(data, str):
        raise RemoteProtocolError("Successful remote metadata must contain string field 'data'.")
    try:
        compressed = base64.b64decode(data.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise RemoteProtocolError("Remote result is not valid base64 data.") from exc
    if len(compressed) > result_size_max + 65_536:
        raise RemoteResultTooLarge(result_bytes=len(compressed), result_size_max=result_size_max)
    return cloudpickle.loads(_bounded_decompress(compressed, result_size_max=result_size_max))


@dataclass
class RemoteSession:
    """
    Session that reuses a single execution context for multiple calls.

    Use as a context manager via choppa.session().
    """

    choppa: Choppa
    _context_id: str | None = None
    _cluster_id: str | None = None
    _client: WorkspaceClient | None = None
    _token: contextvars.Token[RemoteSession | None] | None = None

    def __enter__(self) -> RemoteSession:
        if self._context_id is not None:
            raise RuntimeError("RemoteSession is already active.")
        client, cluster_id = self.choppa._client_and_cluster()
        ctx = client.command_execution.create_and_wait(
            cluster_id=cluster_id,
            language=compute.Language.PYTHON,
            timeout=self.choppa.timeout,
        )
        if not ctx.id:
            raise RemoteProtocolError("Databricks did not return an execution-context ID.")
        self._client = client
        self._cluster_id = cluster_id
        self._context_id = ctx.id
        self._token = _current_session.set(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _current_session.reset(self._token)
            self._token = None

        context_id = self._context_id
        cluster_id = self._cluster_id
        client = self._client
        self._context_id = None
        self._cluster_id = None
        self._client = None

        if context_id and client and cluster_id:
            client.command_execution.destroy(cluster_id=cluster_id, context_id=context_id)

    def call(self, remote_def: RemoteFunction[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute remote function and return the value."""
        if not self._context_id or not self._client or not self._cluster_id:
            raise RuntimeError("RemoteSession not initialized. Use: with choppa.session(): ...")

        code = _build_invoke_code(
            remote_def=remote_def,
            args=tuple(args),
            kwargs=dict(kwargs),
            argument_size_max=self.choppa.argument_size_max,
            result_size_max=self.choppa.result_size_max,
        )

        resp = self._client.command_execution.execute_and_wait(
            cluster_id=self._cluster_id,
            context_id=self._context_id,
            language=compute.Language.PYTHON,
            command=code,
            timeout=self.choppa.timeout,
        )

        output = _extract_text(resp)
        if resp.results is not None and resp.results.truncated:
            raise RemoteOutputTruncated(output)
        meta = _find_meta(output)
        return cast(R, _interpret_meta(meta, output, result_size_max=self.choppa.result_size_max))

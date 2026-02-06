"""Remote code generation for choppa."""

from __future__ import annotations

import base64
import textwrap
import zlib
from dataclasses import dataclass
from typing import Any, Generic, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")

_CHOPPA_META_MARKER = "__CHOPPA_META__:"


def _require_cloudpickle():
    """Import cloudpickle or raise a helpful error."""
    try:
        import cloudpickle  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "cloudpickle is required locally when arguments use pickle. Install with: pip install cloudpickle"
        ) from e
    return cloudpickle


def _b64_pickle(obj: Any) -> str:
    """Pickle, compress, and base64-encode an object."""
    cloudpickle = _require_cloudpickle()
    b = zlib.compress(cloudpickle.dumps(obj))
    return base64.b64encode(b).decode("ascii")


@dataclass(frozen=True)
class RemoteFunction(Generic[P, R]):
    """Definition of a remote function."""

    name: str
    source: str

    def call_expr(self) -> str:
        return f"{self.name}(*__choppa_args, **__choppa_kwargs)"


def _build_invoke_code(
    *,
    remote_def: RemoteFunction[Any, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> str:
    """
    Build remote code that:
      1) Deserializes pickled arguments
      2) Runs user function
      3) Serializes and returns the result
    """
    args_payload = _b64_pickle(args)
    kwargs_payload = _b64_pickle(kwargs)

    code = f"""
from __future__ import annotations
import base64, json, traceback, zlib

__choppa_marker = {_CHOPPA_META_MARKER!r}

__choppa_args_payload = {args_payload!r}
__choppa_kwargs_payload = {kwargs_payload!r}

def __choppa_emit(meta: dict) -> None:
    print(__choppa_marker + json.dumps(meta, ensure_ascii=False))

def __choppa_decode_pklz(payload: str):
    import cloudpickle  # type: ignore
    b = base64.b64decode(payload.encode("ascii"))
    return cloudpickle.loads(zlib.decompress(b))

def __choppa_encode_result(obj):
    import cloudpickle  # type: ignore
    raw = cloudpickle.dumps(obj)
    rawz = zlib.compress(raw)
    return base64.b64encode(rawz).decode("ascii")

# ------------------- user function definition -------------------
{remote_def.source}

try:
    __choppa_args = __choppa_decode_pklz(__choppa_args_payload)
    __choppa_kwargs = __choppa_decode_pklz(__choppa_kwargs_payload)

    __choppa_res = {remote_def.name}(*__choppa_args, **__choppa_kwargs)

    __choppa_emit({{
        "ok": True,
        "data": __choppa_encode_result(__choppa_res),
    }})

except Exception as e:
    __choppa_emit({{
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
    }})
"""
    return textwrap.dedent(code).lstrip()

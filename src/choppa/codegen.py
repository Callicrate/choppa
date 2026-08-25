"""Remote code generation for choppa."""

from __future__ import annotations

import base64
import textwrap
import zlib
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Generic, ParamSpec, TypeVar, cast

from choppa.errors import RemoteArgumentsTooLarge

P = ParamSpec("P")
R = TypeVar("R")

_CHOPPA_META_MARKER = "__CHOPPA_META__:"


def _require_cloudpickle() -> ModuleType:
    """Import the required serialization dependency."""
    import cloudpickle  # type: ignore[import-untyped]

    return cast(ModuleType, cloudpickle)


def _b64_pickle(obj: Any, *, payload_name: str, argument_size_max: int) -> str:
    """Pickle, compress, and base64-encode an object."""
    cloudpickle = _require_cloudpickle()
    raw = cloudpickle.dumps(obj)
    if len(raw) > argument_size_max:
        raise RemoteArgumentsTooLarge(
            payload_name=payload_name,
            payload_bytes=len(raw),
            argument_size_max=argument_size_max,
        )
    b = zlib.compress(raw)
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
    argument_size_max: int,
    result_size_max: int,
) -> str:
    """
    Build remote code that:
      1) Deserializes pickled arguments
      2) Runs user function
      3) Serializes and returns the result
    """
    args_payload = _b64_pickle(args, payload_name="positional arguments", argument_size_max=argument_size_max)
    kwargs_payload = _b64_pickle(kwargs, payload_name="keyword arguments", argument_size_max=argument_size_max)

    code = f"""
from __future__ import annotations
import base64, json, traceback, zlib

__choppa_marker = {_CHOPPA_META_MARKER!r}
__choppa_result_size_max = {result_size_max!r}

__choppa_args_payload = {args_payload!r}
__choppa_kwargs_payload = {kwargs_payload!r}

def __choppa_emit(meta: dict) -> None:
    print(__choppa_marker + json.dumps(meta, ensure_ascii=False))

def __choppa_decode_pklz(payload: str):
    import cloudpickle  # type: ignore
    b = base64.b64decode(payload.encode("ascii"))
    return cloudpickle.loads(zlib.decompress(b))

# ------------------- user function definition -------------------
{remote_def.source}

try:
    __choppa_args = __choppa_decode_pklz(__choppa_args_payload)
    __choppa_kwargs = __choppa_decode_pklz(__choppa_kwargs_payload)

    __choppa_res = {remote_def.name}(*__choppa_args, **__choppa_kwargs)

    import cloudpickle  # type: ignore
    __choppa_raw = cloudpickle.dumps(__choppa_res)
    if len(__choppa_raw) > __choppa_result_size_max:
        __choppa_emit({{
            "ok": False,
            "error_type": "result_too_large",
            "error": "result_too_large",
            "result_bytes": len(__choppa_raw),
            "result_size_max": __choppa_result_size_max,
        }})
    else:
        __choppa_rawz = zlib.compress(__choppa_raw)
        __choppa_emit({{
            "ok": True,
            "data": base64.b64encode(__choppa_rawz).decode("ascii"),
        }})

except Exception as e:
    __choppa_emit({{
        "ok": False,
        "error": str(e),
        "traceback": traceback.format_exc(),
    }})
"""
    return textwrap.dedent(code).lstrip()

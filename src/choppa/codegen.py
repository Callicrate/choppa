"""Remote code generation for choppa."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import Any, Generic, ParamSpec, TypeVar

from choppa.artifacts import (
    _CHOPPA_ARTIFACT_MARKER_KEY,
    _b64_pickle_local,
    _encode_refs_for_transport,
)

P = ParamSpec("P")
R = TypeVar("R")

_CHOPPA_META_MARKER = "__CHOPPA_META__:"


@dataclass(frozen=True)
class RemoteFunction(Generic[P, R]):
    """Definition of a remote function."""

    name: str
    source: str
    artifacts: bool

    def call_expr(self) -> str:
        return f"{self.name}(*__choppa_args, **__choppa_kwargs)"


def _build_invoke_code(
    *,
    remote_def: RemoteFunction[Any, Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    artifact_base_fuse: str | None,
    artifact_base_api: str | None,
    result_size_max: int | None,
) -> str:
    """
    Build remote code that:
      1) Restore ArtifactRef markers -> remote ArtifactRef objects
      2) Auto-materialize ArtifactRef args (load on cluster) unless param opts out
      3) Run user function
      4) Inline-return small values; else spill to artifact store and return an ArtifactRef
         If result_size_max is None, always return inline (no size limit).

    If artifact_base_fuse/api are None, artifact storage is disabled and
    results exceeding result_size_max will raise an error.
    """
    norm_args = _encode_refs_for_transport(args)
    norm_kwargs = _encode_refs_for_transport(kwargs)

    # Always use pickle-zlib for argument transport
    args_payload = _b64_pickle_local(norm_args)
    kwargs_payload = _b64_pickle_local(norm_kwargs)

    code = f"""
from __future__ import annotations
import base64, json, os, traceback, zlib, inspect
from dataclasses import dataclass
from typing import Any, Optional, get_origin, get_args

__choppa_marker = {_CHOPPA_META_MARKER!r}
__choppa_ref_key = {_CHOPPA_ARTIFACT_MARKER_KEY!r}

__choppa_store = {bool(remote_def.artifacts)!r}
__choppa_max_inline = {int(result_size_max) if result_size_max is not None else 0}
__choppa_max_inline_is_unlimited = {result_size_max is None!r}

__choppa_args_payload = {args_payload!r}
__choppa_kwargs_payload = {kwargs_payload!r}

__choppa_art_base_fuse = {artifact_base_fuse!r}
__choppa_art_base_api = {artifact_base_api!r}

def __choppa_emit(meta: dict) -> None:
    print(__choppa_marker + json.dumps(meta, ensure_ascii=False))

def __choppa_write_atomic_bytes(path: str, data: bytes) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)

def __choppa_write_artifact(data: bytes) -> tuple[str, str]:
    if __choppa_art_base_fuse is None or __choppa_art_base_api is None:
        raise RuntimeError(
            "Result too large for inline return and artifact_dir is not configured. "
            "Set artifact_dir when creating Choppa to enable artifact storage for large results."
        )
    fuse_path = __choppa_art_base_fuse + ".pklz"
    api_path = __choppa_art_base_api + ".pklz"
    __choppa_write_atomic_bytes(fuse_path, data)
    return api_path, fuse_path

def __choppa_decode_pklz(payload: str):
    import cloudpickle  # type: ignore
    b = base64.b64decode(payload.encode("ascii"))
    return cloudpickle.loads(zlib.decompress(b))

@dataclass(frozen=True)
class ArtifactRef:
    path: str
    fuse_path: str
    artifact_bytes: Optional[int] = None

def __choppa_restore_refs(x: Any) -> Any:
    if isinstance(x, dict) and x.get(__choppa_ref_key) is True:
        return ArtifactRef(
            path=str(x.get("path")),
            fuse_path=str(x.get("fuse_path")),
            artifact_bytes=(int(x["artifact_bytes"]) if x.get("artifact_bytes") is not None else None),
        )
    if isinstance(x, list):
        return [__choppa_restore_refs(v) for v in x]
    if isinstance(x, tuple):
        return tuple(__choppa_restore_refs(v) for v in x)
    if isinstance(x, dict):
        return {{k: __choppa_restore_refs(v) for k, v in x.items()}}
    return x

def __choppa_pack_refs(x: Any) -> Any:
    if isinstance(x, ArtifactRef):
        return {{
            __choppa_ref_key: True,
            "path": x.path,
            "fuse_path": x.fuse_path,
            "artifact_bytes": x.artifact_bytes,
        }}
    if isinstance(x, list):
        return [__choppa_pack_refs(v) for v in x]
    if isinstance(x, tuple):
        return tuple(__choppa_pack_refs(v) for v in x)
    if isinstance(x, dict):
        return {{k: __choppa_pack_refs(v) for k, v in x.items()}}
    return x

def __choppa_load_artifact(ref: ArtifactRef) -> Any:
    import cloudpickle  # type: ignore
    with open(ref.fuse_path, "rb") as f:
        b = f.read()
    return cloudpickle.loads(zlib.decompress(b))

def __choppa_materialize(x: Any) -> Any:
    if isinstance(x, ArtifactRef):
        return __choppa_load_artifact(x)
    if isinstance(x, list):
        return [__choppa_materialize(v) for v in x]
    if isinstance(x, tuple):
        return tuple(__choppa_materialize(v) for v in x)
    if isinstance(x, dict):
        return {{k: __choppa_materialize(v) for k, v in x.items()}}
    return x

def __choppa_is_artifactref_annotation(ann: Any) -> bool:
    if ann is ArtifactRef:
        return True
    if isinstance(ann, str):
        return ann.split(".")[-1] == "ArtifactRef"
    origin = get_origin(ann)
    if origin is not None:
        return any(__choppa_is_artifactref_annotation(a) for a in get_args(ann))
    return False

def __choppa_should_keep_ref(param) -> bool:
    # Opt-out of auto-load by:
    #  - annotating param as ArtifactRef, OR
    #  - naming it like "*_ref" / "*_artifact_ref" / "*_artifact"
    if __choppa_is_artifactref_annotation(param.annotation):
        return True
    n = str(param.name)
    return n.endswith("_ref") or n.endswith("_artifact_ref") or n.endswith("_artifact")

def __choppa_encode_result(obj):
    # Always use pickle-zlib. Returns (inline_data, raw_bytes)
    import cloudpickle  # type: ignore
    packed = __choppa_pack_refs(obj)
    raw = cloudpickle.dumps(packed)
    rawz = zlib.compress(raw)
    return base64.b64encode(rawz).decode("ascii"), rawz

# ------------------- user function definition -------------------
{remote_def.source}

try:
    __choppa_args = __choppa_restore_refs(__choppa_decode_pklz(__choppa_args_payload))
    __choppa_kwargs = __choppa_restore_refs(__choppa_decode_pklz(__choppa_kwargs_payload))

    __fn = {remote_def.name}
    __sig = inspect.signature(__fn)
    __bound = __sig.bind(*__choppa_args, **__choppa_kwargs)
    __bound.apply_defaults()

    # Auto-dereference ArtifactRefs unless param opts out.
    for __pname, __pval in list(__bound.arguments.items()):
        __param = __sig.parameters.get(__pname)
        if __param is not None and (not __choppa_should_keep_ref(__param)):
            __bound.arguments[__pname] = __choppa_materialize(__pval)

    __choppa_res = __fn(*__bound.args, **__bound.kwargs)

    # If function returns an ArtifactRef, treat it as "already an artifact pointer".
    if isinstance(__choppa_res, ArtifactRef):
        __choppa_emit({{
            "ok": True,
            "storage": "artifact",
            "path": __choppa_res.path,
            "fuse_path": __choppa_res.fuse_path,
            "inline_bytes": 0,
            "artifact_bytes": __choppa_res.artifact_bytes,
            "note": "returned_ref",
        }})
    else:
        __inline_data, __raw_bytes = __choppa_encode_result(__choppa_res)

        __inline_meta = {{
            "ok": True,
            "storage": "inline",
            "data": __inline_data,
        }}
        __inline_line = __choppa_marker + json.dumps(__inline_meta, ensure_ascii=False)
        __inline_bytes = len(__inline_line.encode("utf-8"))

        # If unlimited mode (result_size_max=None) or within limit, always inline
        if __choppa_max_inline_is_unlimited:
            __inline_meta["inline_bytes"] = __inline_bytes
            __choppa_emit(__inline_meta)
        elif (not __choppa_store) and (__inline_bytes <= __choppa_max_inline):
            __inline_meta["inline_bytes"] = __inline_bytes
            __choppa_emit(__inline_meta)
        else:
            __api_path, __fuse_path = __choppa_write_artifact(__raw_bytes)
            __meta = {{
                "ok": True,
                "storage": "artifact",
                "path": __api_path,
                "fuse_path": __fuse_path,
                "inline_bytes": __inline_bytes,
                "artifact_bytes": len(__raw_bytes),
            }}

            if (not __choppa_store) and (__inline_bytes > __choppa_max_inline):
                __meta.update({{
                    "ok": False,
                    "error": "too_large",
                    "result_size_max": __choppa_max_inline,
                }})

            __choppa_emit(__meta)

except Exception as e:
    __choppa_emit({{
        "ok": False,
        "storage": "inline",
        "error": str(e),
        "traceback": traceback.format_exc(),
    }})
"""
    return textwrap.dedent(code).lstrip()

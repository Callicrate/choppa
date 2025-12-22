"""Artifact reference and serialization utilities."""

from __future__ import annotations

import base64
import zlib
from dataclasses import dataclass
from typing import Any

_CHOPPA_ARTIFACT_MARKER_KEY = "__choppa_artifact_ref__"


@dataclass(frozen=True)
class ArtifactRef:
    """
    Pointer to a persisted artifact stored in Workspace Files.

    `path` is the Workspace API path (e.g. "/Users/alice/choppa_artifacts/.../id.pklz").
    `fuse_path` is the driver mount path ("/Workspace/Users/...").
    """

    path: str
    fuse_path: str
    artifact_bytes: int | None = None

    def __str__(self) -> str:
        return f"ArtifactRef(path={self.path!r}, fuse_path={self.fuse_path!r}, bytes={self.artifact_bytes})"


def _require_cloudpickle_local():
    """Import cloudpickle or raise a helpful error."""
    try:
        import cloudpickle  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "cloudpickle is required locally when arguments or results use pickle. "
            "Install with: pip install cloudpickle"
        ) from e
    return cloudpickle


def _b64_pickle_local(obj: Any) -> str:
    """Pickle, compress, and base64-encode an object locally."""
    cloudpickle = _require_cloudpickle_local()
    b = zlib.compress(cloudpickle.dumps(obj))
    return base64.b64encode(b).decode("ascii")


def _unpickle_local_b64(s: str) -> Any:
    """Base64-decode, decompress, and unpickle an object locally."""
    cloudpickle = _require_cloudpickle_local()
    b = base64.b64decode(s.encode("ascii"))
    return cloudpickle.loads(zlib.decompress(b))


def _encode_refs_for_transport(x: Any) -> Any:
    """
    Replace ArtifactRef objects with a small JSON marker dict (recursively).
    This lets you pass ArtifactRef through JSON or pickle args cleanly.
    """
    if isinstance(x, ArtifactRef):
        return {
            _CHOPPA_ARTIFACT_MARKER_KEY: True,
            "path": x.path,
            "fuse_path": x.fuse_path,
            "artifact_bytes": x.artifact_bytes,
        }
    if isinstance(x, list):
        return [_encode_refs_for_transport(v) for v in x]
    if isinstance(x, tuple):
        return tuple(_encode_refs_for_transport(v) for v in x)
    if isinstance(x, dict):
        return {k: _encode_refs_for_transport(v) for k, v in x.items()}
    return x


def _restore_refs_local(x: Any) -> Any:
    """Convert marker dicts back into local ArtifactRef objects (recursively)."""
    if isinstance(x, dict) and x.get(_CHOPPA_ARTIFACT_MARKER_KEY) is True:
        return ArtifactRef(
            path=str(x.get("path")),
            fuse_path=str(x.get("fuse_path")),
            artifact_bytes=(int(x["artifact_bytes"]) if x.get("artifact_bytes") is not None else None),
        )
    if isinstance(x, list):
        return [_restore_refs_local(v) for v in x]
    if isinstance(x, tuple):
        return tuple(_restore_refs_local(v) for v in x)
    if isinstance(x, dict):
        return {k: _restore_refs_local(v) for k, v in x.items()}
    return x

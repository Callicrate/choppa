"""Internal utilities for choppa."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime, timezone
from typing import Any

from databricks.sdk.service import compute


def _strip_leading_decorators(src: str) -> str:
    """Remove leading decorators from function source."""
    src = textwrap.dedent(src)
    lines = src.splitlines()

    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].lstrip().startswith("@"):
        i += 1

    return "\n".join(lines[i:]).rstrip() + "\n"


def _safe_name(name: str) -> str:
    """Sanitize a name for use in file paths."""
    s = re.sub(r"[^0-9A-Za-z_.-]+", "_", name).strip("_")
    return s or "func"


def _now_utc_day() -> str:
    """Return current UTC date as YYYYMMDD string."""
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _normalize_artifact_dir(path: str) -> tuple[str, str]:
    """
    Normalize artifact directory path.

    Returns (fuse_path, workspace_api_path)

    Accepts:
      - "/Workspace/Users/.../dir"  (fuse path)
      - "/Users/.../dir"           (workspace api path)
    """
    if not path:
        raise ValueError("artifact_dir must be a non-empty string")

    if path.startswith("/Workspace/"):
        fuse = path.rstrip("/")
        api = fuse[len("/Workspace") :]
        if not api.startswith("/"):
            api = "/" + api
        return fuse, api

    api = path.rstrip("/")
    if not api.startswith("/"):
        api = "/" + api
    fuse = "/Workspace" + api
    return fuse, api


def _extract_text(resp: compute.CommandStatusResponse) -> str:
    """Extract text output from command response."""
    r = getattr(resp, "results", None)
    if r is None:
        return repr(resp)
    data = getattr(r, "data", None)
    if isinstance(data, str):
        return data
    return str(r)


def _done(status_obj: Any) -> bool:
    """Check if a command status indicates completion."""
    s = getattr(status_obj, "value", status_obj)
    if s is None:
        return False
    s = str(s).upper()
    return s in {"FINISHED", "ERROR", "CANCELLED"}

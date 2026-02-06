"""Internal utilities for choppa."""

from __future__ import annotations

import textwrap

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


def _extract_text(resp: compute.CommandStatusResponse) -> str:
    """Extract text output from command response."""
    r = getattr(resp, "results", None)
    if r is None:
        return repr(resp)
    data = getattr(r, "data", None)
    if isinstance(data, str):
        return data
    return str(r)

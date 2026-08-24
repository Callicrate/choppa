"""Internal utilities for choppa."""

from __future__ import annotations

import ast
import textwrap

from databricks.sdk.service import compute


def _strip_leading_decorators(src: str) -> str:
    """Return one function definition without its leading decorators."""
    dedented = textwrap.dedent(src)
    try:
        module = ast.parse(dedented)
    except SyntaxError as exc:
        raise ValueError("Function source is not valid Python.") from exc

    functions = [node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(functions) != 1:
        raise ValueError("Expected source containing exactly one function definition.")

    function = functions[0]
    lines = dedented.splitlines()
    source = "\n".join(lines[function.lineno - 1 :]).rstrip() + "\n"
    compile("from __future__ import annotations\n" + source, "<choppa-function>", "exec")
    return source


def _extract_text(resp: compute.CommandStatusResponse) -> str:
    """Extract text output from command response."""
    r = getattr(resp, "results", None)
    if r is None:
        return repr(resp)
    data = getattr(r, "data", None)
    if isinstance(data, str):
        return data
    return str(r)

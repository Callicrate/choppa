"""Verify the installed Choppa wheel's base runtime contract."""

from __future__ import annotations

from importlib.metadata import version

import choppa
from choppa.codegen import RemoteFunction, _build_invoke_code


def main() -> None:
    """Check version identity and mandatory payload generation."""
    distribution_version = version("choppa")
    if choppa.__version__ != distribution_version:
        raise RuntimeError(
            f"Runtime version {choppa.__version__} does not match distribution version {distribution_version}."
        )

    remote: RemoteFunction[[int, int], int] = RemoteFunction(
        name="add",
        source="def add(a, b): return a + b\n",
    )
    code = _build_invoke_code(
        remote_def=remote,
        args=(1, 2),
        kwargs={},
        argument_size_max=256_000,
        result_size_max=256_000,
    )
    if "__CHOPPA_META__" not in code:
        raise RuntimeError("Generated invocation is missing the Choppa protocol marker.")


if __name__ == "__main__":
    main()

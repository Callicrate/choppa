"""Static consumer contract for the installed Choppa wheel."""

from __future__ import annotations

import choppa


@choppa.remote
def add(a: int, b: int) -> int:
    return a + b


@choppa.remote()
def subtract(a: int, b: int) -> int:
    return a - b


sum_result: int = add(1, 2)
difference_result: int = subtract(3, 2)

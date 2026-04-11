from __future__ import annotations

from collections.abc import Iterator
from itertools import product


def parameter_grid(grid: dict[str, list[object]]) -> Iterator[dict[str, object]]:
    keys = list(grid)
    for values in product(*(grid[key] for key in keys)):
        yield dict(zip(keys, values, strict=True))

from __future__ import annotations

from itertools import product
from typing import Iterator


def parameter_grid(grid: dict[str, list[object]]) -> Iterator[dict[str, object]]:
    keys = list(grid)
    for values in product(*(grid[key] for key in keys)):
        yield dict(zip(keys, values))


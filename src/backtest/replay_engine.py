from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class ReplayStep:
    day: int
    timestamp: int
    rows_by_product: dict[str, dict[str, str]]


class ReplayEngine:
    def __init__(self, steps: list[ReplayStep]) -> None:
        self.steps = steps

    @classmethod
    def from_price_files(cls, paths: list[str | Path]) -> "ReplayEngine":
        grouped: dict[tuple[int, int], dict[str, dict[str, str]]] = defaultdict(dict)

        for path in paths:
            with Path(path).open(newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                for row in reader:
                    day = int(row["day"])
                    timestamp = int(row["timestamp"])
                    grouped[(day, timestamp)][row["product"]] = row

        steps = [
            ReplayStep(day=day, timestamp=timestamp, rows_by_product=rows)
            for (day, timestamp), rows in sorted(grouped.items())
        ]
        return cls(steps)

    def iter_steps(self) -> Iterator[ReplayStep]:
        yield from self.steps


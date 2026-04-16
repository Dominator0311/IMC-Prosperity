"""Identify persistent quote-depth bands by order-book rank.

In tutorial-round IMC products, the order book is populated by a small
number of stylized bots that always occupy fixed rank positions:

    bid_1 / ask_1 = innermost level (closest to fair value)
    bid_2 / ask_2 = next level out
    bid_3 / ask_3 = furthest level out

Each rank corresponds to a single bot's quote (with rare exceptions
when a near-FV bot temporarily appears at the inside, displacing the
walls outward by one rank). This module classifies levels by their
rank in the book, then characterizes each rank's offset distribution
to give it a meaningful name.

Why rank rather than histogram peaks:
    Asymmetric rounding rules (e.g., Bot 2 ask = ceil(fv + 0.25) + 6)
    produce offset distributions with two adjacent integer modes
    (offset ~ 6 and 7 alternating with fractional FV). A pure
    histogram approach can't tell whether those are two separate bots
    or one bot with state-dependent placement; rank-based classification
    correctly attributes both to the same bot because they appear at
    the same book rank.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from src.analysis.calibration.types import DepthBand, FactRow

DEFAULT_MAX_LEVELS = 3  # IMC exposes up to 3 levels per side
DEFAULT_OFFSET_MARGIN = 1.0  # padding around observed offset range
DEFAULT_MIN_PRESENCE_RATE = 0.01


def detect_depth_bands(
    facts: Sequence[FactRow],
    *,
    max_levels: int = DEFAULT_MAX_LEVELS,
    offset_margin: float = DEFAULT_OFFSET_MARGIN,
    min_presence_rate: float = DEFAULT_MIN_PRESENCE_RATE,
) -> tuple[DepthBand, ...]:
    """Classify book levels by their rank position.

    For each (side, rank) in {bid, ask} x {1..max_levels}, collect
    every observed level price minus fair value, then build a band
    that covers the empirical [min, max] offset range with a small
    margin. Bands with presence below ``min_presence_rate`` (e.g., the
    rarely-occupied 3rd level) are dropped.

    Returns bands sorted by side then by rank (level1 first = closest
    to FV).
    """
    out: list[DepthBand] = []
    for side in ("bid", "ask"):
        for rank in range(1, max_levels + 1):
            offsets = _collect_offsets_at_rank(facts, side=side, rank=rank)
            if not offsets:
                continue
            n_present = len(offsets)
            presence = n_present / len(facts)
            if presence < min_presence_rate:
                continue
            arr = np.asarray(offsets)
            band = DepthBand(
                name=_band_name(side=side, rank=rank, center=float(arr.mean())),
                side=side,
                offset_min=float(arr.min() - offset_margin),
                offset_max=float(arr.max() + offset_margin),
                presence_rate=presence,
            )
            out.append(band)
    return tuple(out)


def collect_offsets(
    facts: Sequence[FactRow],
) -> tuple[np.ndarray, np.ndarray]:
    """Diagnostic helper: return signed (bid_offsets, ask_offsets) arrays.

    Useful for histogram inspection during development; not used in the
    primary classification path.
    """
    bid_offsets: list[float] = []
    ask_offsets: list[float] = []
    for fact in facts:
        for level in fact.bids:
            bid_offsets.append(level.price - fact.server_fv)
        for level in fact.asks:
            ask_offsets.append(level.price - fact.server_fv)
    return (
        np.asarray(bid_offsets, dtype=float),
        np.asarray(ask_offsets, dtype=float),
    )


def assign_levels_to_bands(
    facts: Sequence[FactRow],
    bands: Sequence[DepthBand],
) -> dict[str, list[tuple[int, int]]]:
    """For each band, list (timestamp, level_price) of matching levels.

    Levels are assigned by RANK match (the band identifies a (side, rank)
    pair in the book), not by offset window. This is consistent with the
    rank-based detection in ``detect_depth_bands``.
    """
    band_index: dict[str, DepthBand] = {b.name: b for b in bands}
    out: dict[str, list[tuple[int, int]]] = {b.name: [] for b in bands}
    for fact in facts:
        for side in ("bid", "ask"):
            levels = fact.bids if side == "bid" else fact.asks
            for rank, level in enumerate(levels, start=1):
                target_name = next(
                    (
                        name for name, b in band_index.items()
                        if b.side == side and _rank_from_name(name) == rank
                    ),
                    None,
                )
                if target_name is None:
                    continue
                out[target_name].append((fact.timestamp, level.price))
    return out


# ----------------------------------------------------------- internals


def _collect_offsets_at_rank(
    facts: Sequence[FactRow], *, side: str, rank: int
) -> list[float]:
    out: list[float] = []
    for fact in facts:
        levels = fact.bids if side == "bid" else fact.asks
        if len(levels) >= rank:
            level = levels[rank - 1]
            out.append(level.price - fact.server_fv)
    return out


def _band_name(*, side: str, rank: int, center: float) -> str:
    """Human-readable band name encoding rank + depth descriptor."""
    abs_offset = abs(center)
    if abs_offset < 2.5:
        depth = "near"
    elif abs_offset < 7.5:
        depth = "inner"
    else:
        depth = "outer"
    return f"level{rank}_{depth}_{side}"


def _rank_from_name(name: str) -> int:
    """Recover the integer rank from a band name like ``level2_inner_ask``."""
    head = name.split("_", 1)[0]  # 'level2'
    return int(head.replace("level", ""))

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
DEFAULT_BIMODALITY_GAP = 3.0  # ticks: minimum mode separation to trigger split
DEFAULT_BIMODALITY_MIN_MASS = 0.01  # drop clusters below 1% of samples (noise)


def detect_depth_bands(
    facts: Sequence[FactRow],
    *,
    max_levels: int = DEFAULT_MAX_LEVELS,
    offset_margin: float = DEFAULT_OFFSET_MARGIN,
    min_presence_rate: float = DEFAULT_MIN_PRESENCE_RATE,
    bimodality_gap: float = DEFAULT_BIMODALITY_GAP,
    bimodality_min_mass: float = DEFAULT_BIMODALITY_MIN_MASS,
) -> tuple[DepthBand, ...]:
    """Classify book levels by rank, splitting bimodal ranks into sub-bands.

    For each (side, rank) in {bid, ask} x {1..max_levels}:

      1. Collect every observed level price minus fair value.
      2. Detect bimodality: if the offset distribution has two clusters
         separated by >= ``bimodality_gap`` ticks AND the smaller cluster
         holds >= ``bimodality_min_mass`` of samples, emit two sub-bands
         (one per cluster).
      3. Otherwise emit a single band covering [min, max] of offsets.

    Bimodality is the signature of two bots sharing the same rank — most
    commonly an "inside" bot (near FV) that displaces the wall bot when
    it's active. The two sub-bands let downstream rule search recover
    each bot's quote rule independently rather than fitting a hybrid
    formula that matches neither.

    Bands with presence below ``min_presence_rate`` are dropped.
    Returns bands sorted by side then rank then proximity to FV.
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
            clusters = _detect_clusters(
                arr, gap=bimodality_gap, min_mass=bimodality_min_mass,
            )
            for sub_idx, cluster in enumerate(clusters):
                cluster_arr = arr[cluster]
                cluster_presence = len(cluster_arr) / len(facts)
                if cluster_presence < min_presence_rate:
                    continue
                suffix = f"_sub{sub_idx + 1}" if len(clusters) > 1 else ""
                out.append(DepthBand(
                    name=_band_name(
                        side=side, rank=rank,
                        center=float(cluster_arr.mean()),
                    ) + suffix,
                    side=side,
                    offset_min=float(cluster_arr.min() - offset_margin),
                    offset_max=float(cluster_arr.max() + offset_margin),
                    presence_rate=cluster_presence,
                ))
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


def _detect_clusters(
    offsets: np.ndarray, *, gap: float, min_mass: float,
) -> list[np.ndarray]:
    """Split an offset array into clusters separated by >= ``gap`` ticks.

    Returns a list of boolean masks (one per cluster) indexing back into
    ``offsets``.

    Algorithm:
      1. Sort offsets, find every successive diff >= ``gap``, declare a
         split point there.
      2. Drop clusters whose mass is < ``min_mass`` of all samples
         (likely noise / outliers).
      3. If only one cluster remains after pruning, return it (no split).
         Otherwise return all surviving clusters.
    """
    if len(offsets) < 2:
        return [np.ones(len(offsets), dtype=bool)]
    sort_idx = np.argsort(offsets)
    sorted_off = offsets[sort_idx]
    diffs = np.diff(sorted_off)
    split_points = np.where(diffs >= gap)[0]
    if len(split_points) == 0:
        return [np.ones(len(offsets), dtype=bool)]

    n = len(offsets)
    starts = [0] + [int(p) + 1 for p in split_points]
    ends = [int(p) + 1 for p in split_points] + [len(sorted_off)]
    surviving: list[np.ndarray] = []
    for s, e in zip(starts, ends):
        original_indices = sort_idx[s:e]
        mass = len(original_indices) / n
        if mass < min_mass:
            continue  # drop noise cluster, keep evaluating others
        mask = np.zeros(n, dtype=bool)
        mask[original_indices] = True
        surviving.append(mask)
    if len(surviving) <= 1:
        return [np.ones(n, dtype=bool)]
    return surviving


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

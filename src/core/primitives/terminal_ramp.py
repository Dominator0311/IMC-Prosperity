"""Terminal risk ramp — linear inventory-band scaling as end-of-round approaches.

IMPORTANT: R3 live round end-ts is 99_900 (1,000 snapshots × step 100),
NOT 999_900 like the historical per-day CSVs. Submission 379928 confirmed
the round never reaches our old 850K ramp start, so we ran at full-bands
through the final tick and ended with open VELVET/VEV_4000 positions.

Current spec (tuned to live round length):
  t <  85_000   → scale = 1.0  (full bands)
  t in [85K, 95K) → scale = (95_000 - t) / 10_000  (linear decay)
  t >= 95_000   → scale = 0.0  (fully flat)

For backtest compatibility with 1M-tick historical days, the constants
below can be overridden via ``configure()`` if needed. Default matches
live R3.

The ZeroBidLottery (VEV_6000 / VEV_6500) is exempt from this ramp —
0-cost fills carry no end-of-round mark risk.
"""

from __future__ import annotations

_RAMP_START: int = 85_000
_RAMP_END: int = 95_000
_RAMP_WIDTH: float = float(_RAMP_END - _RAMP_START)

# Products exempt from the ramp (0-cost lottery orders).
RAMP_EXEMPT_PRODUCTS: frozenset[str] = frozenset({"VEV_6000", "VEV_6500"})


def scale_factor(timestamp: int) -> float:
    """Inventory-band scaling factor at ``timestamp``.

    Returns 1.0 before the ramp, 0.0 after, linear in between.
    """
    if timestamp < _RAMP_START:
        return 1.0
    if timestamp >= _RAMP_END:
        return 0.0
    return (_RAMP_END - timestamp) / _RAMP_WIDTH


def scaled_cap(base_cap: int, timestamp: int) -> int:
    """Apply the ramp to a position cap, returning at least 1 (avoids div-by-zero)."""
    sf = scale_factor(timestamp)
    result = int(base_cap * sf)
    return max(result, 1)


def is_in_ramp(timestamp: int) -> bool:
    return timestamp >= _RAMP_START


def is_post_ramp(timestamp: int) -> bool:
    return timestamp >= _RAMP_END

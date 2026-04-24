"""Terminal risk ramp — linear inventory-band scaling as end-of-round approaches.

Plan G spec:
  t < 850_000   → scale = 1.0  (full bands)
  t in [850K, 950K) → scale = (950_000 - t) / 100_000  (linear decay)
  t >= 950_000  → scale = 0.0  (fully flat)

The ZeroBidLottery (VEV_6000 / VEV_6500) is exempt from this ramp —
0-cost fills carry no end-of-round mark risk.
"""

from __future__ import annotations

_RAMP_START: int = 850_000
_RAMP_END: int = 950_000
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

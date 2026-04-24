"""HYDROGEL_PACK market-maker — Plan A.

Wide-spread (median 16) delta-1 product with balanced flow.
3-day replay: +27,360 at 100% fill. Dominant algorithmic alpha source.

Uses the SST Take/Clear/Make primitive with inventory skew.
Independent of delta budget (HYDROGEL carries no option delta).

Bot shot sizes: {2, 3, 4, 5, 6}. We break large quotes into size-5
child orders for better queue position (Plan L / T13).
"""

from __future__ import annotations

import math

from src.core.primitives.sst import SSTParams, TradingDecision, take_clear_make
from src.core.primitives.terminal_ramp import RAMP_EXEMPT_PRODUCTS, scaled_cap
from src.core.r3_products import HYDROGEL_PACK
from src.core.types import NormalizedSnapshot
from src.datamodel import Order

# Default SST parameters (post-sweep best from T02b)
_DEFAULT_PARAMS: SSTParams = SSTParams(
    take_width=8.0,
    clear_threshold=0.5,
    clear_width=3.0,
    default_edge=3.0,
    disregard_edge=1.0,
    join_edge=3.0,
    default_quote_size=5,   # size-5 child orders to match bot shot sizes
    max_taker_size=30,
    prevent_adverse=False,  # HYDROGEL flow is balanced; no adverse filter
    quote_inside_wall=True, # F2 convergent pattern
    wall_min_volume=10,
)

_POSITION_LIMIT: int = 200


def hydrogel_orders(
    snapshot: NormalizedSnapshot,
    position: int,
    timestamp: int,
    params: SSTParams = _DEFAULT_PARAMS,
    skew_strength: float = 1.0,
) -> list[Order]:
    """Generate HYDROGEL orders for one tick.

    ``skew_strength`` controls how aggressively inventory tilts quotes.
    1.0 = one tick per 100-unit position (at limit → max 2-tick skew).
    """
    if snapshot.mid is None:
        return []

    cap = scaled_cap(_POSITION_LIMIT, timestamp)
    fair_value = _skewed_fair(snapshot, position, cap, skew_strength)

    decision: TradingDecision = take_clear_make(
        product=HYDROGEL_PACK,
        fair_value=fair_value,
        snapshot=snapshot,
        position=position,
        position_limit=cap,
        params=params,
    )
    return decision.orders


def _skewed_fair(
    snapshot: NormalizedSnapshot,
    position: int,
    cap: int,
    strength: float,
) -> float:
    """Shift the fair value to skew quotes away from current inventory."""
    mid = snapshot.mid
    if mid is None:
        return 0.0
    if cap <= 0:
        return mid
    # Skew: positive position → lower fair (suppresses bids, lifts asks)
    pos_ratio = position / cap
    skew = -pos_ratio * strength  # in ticks
    return mid + skew

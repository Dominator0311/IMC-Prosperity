"""VELVETFRUIT_EXTRACT mean-reversion MM + hedge (v6).

Two-role strategy:
  1. MEAN-REVERSION ALPHA — fair value anchored to rolling EWMA mean
     instead of instantaneous mid. VELVET is mildly mean-reverting
     (range ~70-90 ticks per day). Taker-aggressive when mid deviates.
  2. DELTA HEDGE — when options book builds net delta, skew fair
     further to drive VELVET toward hedge target.

Fair construction:
    fair = rolling_ewma_mean + inventory_skew + delta_hedge_skew

take_width tightened to 3 so we cross spread on ~4-tick deviations.
clear_threshold disabled to hold positions through reversion.
"""

from __future__ import annotations

import math

from src.core.primitives.sst import SSTParams, take_clear_make
from src.core.primitives.terminal_ramp import scaled_cap
from src.core.r3_products import VELVETFRUIT_EXTRACT
from src.core.types import NormalizedSnapshot
from src.datamodel import Order

_VELVET_HEDGE_POS_LIMIT: int = 200
_VELVET_HEDGE_TIGHT_BAND: int = 150  # bumped from 60; we want real alpha here too

# Only activate when we have meaningful delta to hedge or inventory to unwind.
_VELVET_HEDGE_IDLE_DELTA: float = 5.0
_VELVET_HEDGE_IDLE_POS: int = 5

_VELVET_HEDGE_PARAMS_PASSIVE: SSTParams = SSTParams(
    # fair = EWMA. take_width 3 = cross when opponent bid > mean+3 or
    # opponent ask < mean-3 (a ~4-5 tick deviation). Leaves meaningful
    # edge to reversion.
    take_width=3.0,
    clear_threshold=0.9,         # safety valve: flatten if |pos| > 90% cap
    clear_width=2.0,
    default_edge=1.0,            # tight edge on 5-wide book
    disregard_edge=1.0,
    join_edge=1.0,
    default_quote_size=20,
    max_taker_size=100,          # willing to take large positions on MR signal
    prevent_adverse=False,
)

_VELVET_HEDGE_PARAMS_CROSS: SSTParams = SSTParams(
    take_width=6.0,
    clear_threshold=0.3,
    clear_width=2.0,
    default_edge=1.0,
    disregard_edge=1.0,
    join_edge=1.0,
    default_quote_size=30,
    max_taker_size=100,
    prevent_adverse=False,
)


def velvet_hedge_orders(
    snapshot: NormalizedSnapshot,
    velvet_position: int,
    net_delta: float,
    timestamp: int,
    rolling_mean: float | None = None,
) -> list[Order]:
    """Generate VELVET mean-reversion + hedge orders for one tick.

    ``rolling_mean`` — EWMA of VELVET mid from the orchestrator. Used as the
    fair-value anchor (mean-reversion). If None, falls back to snapshot.mid
    (pure MM, no MR).

    ``net_delta`` drives a secondary skew on top of the MR anchor — when
    options book accumulates positive delta, skew fair DOWN to sell VELVET
    (hedge). We are NOT gutting MR for hedging; skews compound.
    """
    if snapshot.mid is None:
        return []

    # Active whenever EWMA mean is far from mid OR there's delta to hedge
    # OR inventory to unwind. Only skip if all three are quiet.
    mid = float(snapshot.mid)
    anchor = rolling_mean if rolling_mean is not None else mid
    mr_gap = anchor - mid  # positive → mid is below anchor → BUY side
    abs_delta = abs(net_delta)

    if (
        abs(mr_gap) < 2.0
        and abs_delta < _VELVET_HEDGE_IDLE_DELTA
        and abs(velvet_position) < _VELVET_HEDGE_IDLE_POS
    ):
        return []

    cap = min(
        scaled_cap(_VELVET_HEDGE_POS_LIMIT, timestamp),
        _VELVET_HEDGE_TIGHT_BAND,
    )

    # Choose params: cross-mode when delta budget is stretched
    params = _VELVET_HEDGE_PARAMS_CROSS if abs_delta > 120 else _VELVET_HEDGE_PARAMS_PASSIVE

    # --- Fair value assembly ---
    # Step 1: MR anchor (the primary signal)
    fair = anchor

    # Step 2: inventory skew (±2 ticks max at full cap)
    inv_skew = -(velvet_position / cap) * 2.0 if cap > 0 else 0.0
    fair += inv_skew

    # Step 3: delta-hedge skew (kicks in on big |net_delta|)
    if abs_delta >= 40:
        skew_magnitude = min(3.0, (abs_delta - 40) / 80.0 * 3.0)
        direction = -math.copysign(1.0, net_delta)
        fair += direction * skew_magnitude

    if fair <= 0:
        return []

    decision = take_clear_make(
        product=VELVETFRUIT_EXTRACT,
        fair_value=fair,
        snapshot=snapshot,
        position=velvet_position,
        position_limit=cap,
        params=params,
    )
    return decision.orders

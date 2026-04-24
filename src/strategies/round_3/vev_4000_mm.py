"""VEV_4000 synthetic-underlying MM — Plan B + Plan F (sub-intrinsic guard).

VEV_4000 is a deep-ITM call: mid ≈ VELVET − 4000. Spread median 21 ticks.
3-day hedged replay: +7,546. Second alpha after HYDROGEL.

Fair-value construction (hedge-aware):
    hedge_buffer = 0.5 × velvet_spread  (absorbs VELVET spread cost)
    bid_fair = velvet_bid − 4000 − hedge_buffer
    ask_fair = velvet_ask − 4000 + hedge_buffer

Sub-intrinsic ask guard (Plan F, T09):
    ask_floor = max(velvet_bid − 4000, 0) + 1
    our_ask = max(our_ask, ask_floor)

Scanner: if competitor ask < velvet_bid − 4000, buy + hedge. Fires ~1/30K.
"""

from __future__ import annotations

import math

from src.core.primitives.sst import SSTParams, TradingDecision, take_clear_make
from src.core.primitives.terminal_ramp import scaled_cap
from src.core.r3_products import VELVETFRUIT_EXTRACT
from src.core.types import NormalizedSnapshot
from src.datamodel import Order

_PRODUCT: str = "VEV_4000"
_POSITION_LIMIT: int = 300

_DEFAULT_PARAMS: SSTParams = SSTParams(
    take_width=3.0,
    clear_threshold=0.5,
    clear_width=3.0,
    default_edge=3.0,
    disregard_edge=1.0,
    join_edge=3.0,
    default_quote_size=5,
    max_taker_size=10,
    prevent_adverse=False,
    quote_inside_wall=False,  # use hedge-aware fair, not wall-peg
)

# Hard delta-budget soft cap for this engine (overridden by R3DeltaBudget).
_SOFT_CAP: int = 150
_HARD_CAP: int = 200  # only when delta budget allows


def vev4000_orders(
    vev_snapshot: NormalizedSnapshot,
    velvet_snapshot: NormalizedSnapshot | None,
    position: int,
    timestamp: int,
    delta_remaining: int = 999,
    params: SSTParams = _DEFAULT_PARAMS,
) -> list[Order]:
    """Generate VEV_4000 + sub-intrinsic-scanner orders for one tick.

    ``delta_remaining`` from R3DeltaBudget limits the effective cap.
    Returns VEV_4000 orders only (no VELVET hedge orders — those come
    from the VelvetHedgeInfra component).
    """
    if velvet_snapshot is None:
        return []

    velvet_bid = velvet_snapshot.best_bid
    velvet_ask = velvet_snapshot.best_ask
    if velvet_bid is None or velvet_ask is None:
        return []

    velvet_spread = velvet_ask.price - velvet_bid.price
    hedge_buffer = 0.5 * velvet_spread

    bid_fair = velvet_bid.price - 4000 - hedge_buffer
    ask_fair = velvet_ask.price - 4000 + hedge_buffer
    # Use midpoint of these two fairs as the SST fair value
    fair_value = (bid_fair + ask_fair) / 2.0

    if fair_value <= 0:
        return []

    # Cap: softer when delta budget is tight
    raw_cap = _SOFT_CAP if delta_remaining < 50 else _HARD_CAP
    cap = min(scaled_cap(_POSITION_LIMIT, timestamp), raw_cap)

    decision: TradingDecision = take_clear_make(
        product=_PRODUCT,
        fair_value=fair_value,
        snapshot=vev_snapshot,
        position=position,
        position_limit=cap,
        params=params,
    )

    orders = list(decision.orders)

    # --- Sub-intrinsic ask guard (Plan F / T09) ---
    intrinsic = max(velvet_bid.price - 4000, 0)
    ask_floor = intrinsic + 1
    corrected: list[Order] = []
    for o in orders:
        if o.quantity < 0 and o.price < ask_floor:
            # Raise ask to floor to prevent sub-intrinsic sale
            corrected.append(Order(o.symbol, ask_floor, o.quantity))
        else:
            corrected.append(o)
    orders = corrected

    # --- Sub-intrinsic buy scanner (rare: ~1/30K per strike) ---
    if vev_snapshot.best_ask is not None:
        competitor_ask = vev_snapshot.best_ask.price
        if competitor_ask < intrinsic:
            # Arbitrage: buy voucher + short VELVET (hedge leg added by VelvetHedge)
            buy_qty = min(5, _POSITION_LIMIT - position) if position < _POSITION_LIMIT else 0
            if buy_qty > 0:
                orders.append(Order(_PRODUCT, competitor_ask, buy_qty))

    return orders

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

_VEV4000_PRODUCT: str = "VEV_4000"
_VEV4000_POS_LIMIT: int = 300

# v7 profit-take: when VEV_4000 mid returns to (velvet_mean − 4000) AND
# |position| ≥ MIN_POS, flatten aggressively. Mirrors hydrogel_mm.py logic.
# Band is 8 ticks (vs HYDROGEL's 10) since VEV_4000 spread is wider (21 ticks)
# so we want to exit before the next swing starts.
_VEV4000_PROFIT_TAKE_BAND: float = 8.0
_VEV4000_PROFIT_TAKE_MIN_POS: int = 40

_VEV4000_PARAMS: SSTParams = SSTParams(
    # fair anchored to VELVET_ewma − 4000. VEV_4000 delta=1 so it tracks
    # VELVET closely. MR on VELVET translates 1:1 to MR on VEV_4000.
    # take_width = 4 crosses spread on meaningful (~5-tick) deviations.
    take_width=4.0,
    clear_threshold=0.9,         # safety valve: flatten if |pos| > 270 (90% of 300)
    clear_width=3.0,
    default_edge=3.0,
    disregard_edge=1.0,
    join_edge=3.0,
    default_quote_size=30,
    max_taker_size=150,          # big size for directional conviction on MR
    prevent_adverse=False,
    quote_inside_wall=False,
)

# Hard delta-budget soft cap for this engine (overridden by R3DeltaBudget).
_VEV4000_SOFT_CAP: int = 150
_VEV4000_HARD_CAP: int = 200  # only when delta budget allows


def vev4000_orders(
    vev_snapshot: NormalizedSnapshot,
    velvet_snapshot: NormalizedSnapshot | None,
    position: int,
    timestamp: int,
    delta_remaining: int = 999,
    params: SSTParams = _VEV4000_PARAMS,
    velvet_mean: float | None = None,
) -> list[Order]:
    """Generate VEV_4000 mean-reversion orders (anchored to VELVET EWMA).

    ``velvet_mean`` — rolling EWMA of VELVET from orchestrator. Used as MR
    anchor (fair = velvet_mean − 4000). If None, falls back to VELVET mid.

    ``delta_remaining`` from R3DeltaBudget limits the effective cap.
    """
    if velvet_snapshot is None:
        return []

    velvet_bid = velvet_snapshot.best_bid
    velvet_ask = velvet_snapshot.best_ask
    if velvet_bid is None or velvet_ask is None:
        return []

    velvet_spread = velvet_ask.price - velvet_bid.price
    hedge_buffer = 0.5 * velvet_spread

    # MR fair: prefer VELVET EWMA anchor; else instantaneous mid midpoint
    if velvet_mean is not None:
        fair_value = float(velvet_mean) - 4000.0
    else:
        bid_fair = velvet_bid.price - 4000 - hedge_buffer
        ask_fair = velvet_ask.price - 4000 + hedge_buffer
        fair_value = (bid_fair + ask_fair) / 2.0

    if fair_value <= 0:
        return []

    # === v7 NEW: profit-taking override ===
    # When VEV_4000 mid returns to (velvet_mean − 4000) AND we have a
    # meaningful position, flatten aggressively to lock in cycle gains.
    # Mirrors HYDROGEL v7 logic. Only fires when we have a reliable anchor.
    if velvet_mean is not None and vev_snapshot.mid is not None:
        vev_mid = float(vev_snapshot.mid)
        if (
            abs(vev_mid - fair_value) < _VEV4000_PROFIT_TAKE_BAND
            and abs(position) >= _VEV4000_PROFIT_TAKE_MIN_POS
        ):
            return _vev4000_profit_take_orders(vev_snapshot, position)

    # Cap: softer when delta budget is tight
    raw_cap = _VEV4000_SOFT_CAP if delta_remaining < 50 else _VEV4000_HARD_CAP
    cap = min(scaled_cap(_VEV4000_POS_LIMIT, timestamp), raw_cap)

    decision: TradingDecision = take_clear_make(
        product=_VEV4000_PRODUCT,
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
            buy_qty = min(5, _VEV4000_POS_LIMIT - position) if position < _VEV4000_POS_LIMIT else 0
            if buy_qty > 0:
                orders.append(Order(_VEV4000_PRODUCT, competitor_ask, buy_qty))

    return orders


def _vev4000_profit_take_orders(
    snapshot: NormalizedSnapshot, position: int
) -> list[Order]:
    """Aggressively flatten VEV_4000 position via taker orders (cross spread).

    Long → sell at best_bid. Short → buy at best_ask. Full position size.
    Mirrors hydrogel_mm._profit_take_orders.
    """
    if position > 0 and snapshot.best_bid is not None:
        return [Order(_VEV4000_PRODUCT, snapshot.best_bid.price, -position)]
    if position < 0 and snapshot.best_ask is not None:
        return [Order(_VEV4000_PRODUCT, snapshot.best_ask.price, -position)]
    return []

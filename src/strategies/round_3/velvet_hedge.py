"""VELVETFRUIT_EXTRACT hedge infrastructure — Plan D.

VELVET is NOT a P&L bucket. Its role: delta-hedge the options complex.
Tight inventory band ±60 (not ±200), aggressive skew toward delta target.

Hedge bands:
    |net_delta| < 40       → passive MM only, no directional intent
    40 ≤ |net_delta| ≤ 120 → skew quotes toward target
    |net_delta| > 120      → cross (take) to restore delta budget
"""

from __future__ import annotations

import math

from src.core.primitives.sst import SSTParams, take_clear_make
from src.core.primitives.terminal_ramp import scaled_cap
from src.core.r3_products import VELVETFRUIT_EXTRACT
from src.core.types import NormalizedSnapshot
from src.datamodel import Order

_PRODUCT: str = VELVETFRUIT_EXTRACT
_POSITION_LIMIT: int = 200
_TIGHT_BAND: int = 60  # VELVET is infrastructure; don't warehouse

_PARAMS_PASSIVE: SSTParams = SSTParams(
    take_width=1.0,
    clear_threshold=0.5,
    clear_width=2.0,
    default_edge=2.0,
    disregard_edge=1.0,
    join_edge=2.0,
    default_quote_size=5,
    max_taker_size=10,
    prevent_adverse=False,
)

_PARAMS_CROSS: SSTParams = SSTParams(
    take_width=8.0,   # wide take to cross aggressively
    clear_threshold=0.3,
    clear_width=2.0,
    default_edge=1.0,
    disregard_edge=1.0,
    join_edge=1.0,
    default_quote_size=5,
    max_taker_size=20,
    prevent_adverse=False,
)


def velvet_hedge_orders(
    snapshot: NormalizedSnapshot,
    velvet_position: int,
    net_delta: float,
    timestamp: int,
) -> list[Order]:
    """Generate VELVET orders for one tick.

    ``net_delta`` is the aggregate delta across all option positions
    (from R3DeltaBudget.net_delta). We want to drive this toward 0.

    The target VELVET position is ``−net_delta`` (excluding VELVET itself):
        target_velvet = −Σ(voucher_pos[K] × delta[K]) − vev_4000_pos
    """
    if snapshot.mid is None:
        return []

    cap = min(scaled_cap(_POSITION_LIMIT, timestamp), _TIGHT_BAND)

    # Decide hedge mode from net_delta magnitude.
    abs_delta = abs(net_delta)

    if abs_delta > 120:
        # Cross aggressively to restore budget
        params = _PARAMS_CROSS
    else:
        params = _PARAMS_PASSIVE

    # Fair value: skew toward reducing net delta
    mid = snapshot.mid
    if mid is None:
        return []

    # Skew: if net_delta > 0 we want to sell VELVET (lower fair)
    #       if net_delta < 0 we want to buy VELVET (raise fair)
    if abs_delta >= 40:
        # Skew strength grows from 0 at |delta|=40 to 3.0 ticks at |delta|=120
        skew_magnitude = min(3.0, (abs_delta - 40) / 80.0 * 3.0)
        # net_delta > 0 → too long → lower fair (sell bias)
        direction = -math.copysign(1.0, net_delta)
        fair_value = mid + direction * skew_magnitude
    else:
        fair_value = mid

    if fair_value <= 0:
        return []

    decision = take_clear_make(
        product=_PRODUCT,
        fair_value=fair_value,
        snapshot=snapshot,
        position=velvet_position,
        position_limit=cap,
        params=params,
    )
    return decision.orders

"""Voucher tiny-liquidity provider — Plan C.

Only K=5400 and K=5500. Join best bid (do not improve). Recycle
inventory by improving ask when long. Guard against corruption and
delta-budget exhaustion.

Expected contribution: ~+150 shells (K=5400 + K=5500 combined).
NOT a P&L engine — inventory absorption at a small acceptable delta cost.

K=5300 is explicitly NOT quoted here (hedge cost > spread capture).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.primitives.terminal_ramp import scaled_cap
from src.datamodel import Order


@dataclass(frozen=True)
class VoucherSpec:
    strike: int
    soft_cap: int
    hard_cap: int


_VOUCHER_SPECS: tuple[VoucherSpec, ...] = (
    VoucherSpec(strike=5400, soft_cap=50, hard_cap=100),
    VoucherSpec(strike=5500, soft_cap=100, hard_cap=150),
)

_POSITION_LIMIT: int = 300


def voucher_liquidity_orders(
    snapshots: dict[int, "NormalizedSnapshot"],
    positions: dict[int, int],
    timestamp: int,
    delta_remaining: int = 999,
    corrupted: set[int] | None = None,
) -> list[Order]:
    """Generate tiny-liquidity orders for K=5400 and K=5500.

    ``snapshots``   maps strike → NormalizedSnapshot
    ``positions``   maps strike → current position
    ``delta_remaining`` from R3DeltaBudget (suppress bidding when tight)
    ``corrupted``   set of strikes whose smile is corrupt (from SmileCache)
    """
    from src.core.types import NormalizedSnapshot  # local to avoid cycle

    corrupted = corrupted or set()
    orders: list[Order] = []

    for spec in _VOUCHER_SPECS:
        k = spec.strike
        symbol = f"VEV_{k}"
        snap: NormalizedSnapshot | None = snapshots.get(k)
        if snap is None:
            continue

        pos = positions.get(k, 0)
        soft_cap = scaled_cap(spec.soft_cap, timestamp)
        hard_cap = scaled_cap(spec.hard_cap, timestamp)

        # Quoting rules
        no_bid = (
            pos >= soft_cap
            or k in corrupted
            or delta_remaining < 10
            or snap.best_bid is None
        )
        no_ask = snap.best_ask is None

        # Bid: join best bid (do not improve)
        if not no_bid:
            bid_price = snap.best_bid.price  # type: ignore[union-attr]
            bid_qty = min(5, hard_cap - pos) if pos < hard_cap else 0
            if bid_qty > 0:
                orders.append(Order(symbol, bid_price, bid_qty))

        # Ask: join or improve (recycle mode when pos >= soft_cap)
        if not no_ask and pos > 0:
            ask_price = snap.best_ask.price  # type: ignore[union-attr]
            if pos >= soft_cap:
                # Improve ask by 1 tick to encourage recycling
                ask_price = max(ask_price - 1, (snap.best_bid.price + 1) if snap.best_bid else ask_price)
            ask_qty = min(5, pos)
            if ask_qty > 0:
                orders.append(Order(symbol, ask_price, -ask_qty))

    return orders

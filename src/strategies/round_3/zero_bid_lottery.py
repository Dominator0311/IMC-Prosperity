"""Zero-bid lottery for VEV_6000 and VEV_6500 — Plan E.

Place BUY @ 0 on both deep-OTM strikes for full capacity (300 each).
First 10 ticks: probe whether price-0 orders are accepted.
If rejected, disable self. 0-cost fills are exempt from TerminalRamp.

Expected: 0–300 shells if platform accepts and end-of-round FV > 0.
"""

from __future__ import annotations

from src.datamodel import Order

# Disabled — the short-premium strategy shorts these strikes for much
# higher EV. Keep module in place (no-op) so other wiring still works.
_ZERO_BID_STRIKES: tuple[int, ...] = ()
_ZERO_BID_POS_LIMIT: int = 300
_ZERO_BID_PROBE_TICKS: int = 10


def zero_bid_orders(
    tick_count: int,
    positions: dict[str, int],
    accepted: bool | None,
) -> list[Order]:
    """Generate 0-price buy orders for VEV_6000 and VEV_6500.

    ``tick_count`` — number of ticks elapsed since start (0-indexed).
    ``positions``  — current positions by product symbol.
    ``accepted``   — None = unknown, True = accept confirmed,
                     False = rejected (disable strategy).

    Returns empty list if platform rejected 0-price orders.
    """
    if accepted is False:
        return []

    orders: list[Order] = []
    for k in _ZERO_BID_STRIKES:
        symbol = f"VEV_{k}"
        pos = positions.get(symbol, 0)
        remaining = _ZERO_BID_POS_LIMIT - pos
        if remaining > 0:
            orders.append(Order(symbol, 0, remaining))

    return orders


def detect_acceptance(
    tick_count: int,
    order_results: dict[str, list[Order]],
    positions_before: dict[str, int],
    positions_after: dict[str, int],
) -> bool | None:
    """Infer whether 0-price orders were accepted.

    Returns:
        None  — too early / inconclusive
        True  — at least one VEV_6000/6500 position changed (accepted)
        False — probe window elapsed, no change (rejected or no fills)
    """
    if tick_count < _ZERO_BID_PROBE_TICKS:
        for k in _ZERO_BID_STRIKES:
            symbol = f"VEV_{k}"
            if positions_after.get(symbol, 0) > positions_before.get(symbol, 0):
                return True
        return None  # still probing
    # Probe window elapsed with no fills
    for k in _ZERO_BID_STRIKES:
        symbol = f"VEV_{k}"
        if positions_after.get(symbol, 0) > 0:
            return True
    return False

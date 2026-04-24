"""Aggregate delta/gamma budget for R3 (Plan H).

Coordinates VELVETFRUIT_EXTRACT, VEV_4000, and OTM voucher positions so
their combined net delta never exceeds the session cap. Called by the
R3Engine before order submission.

Priority when multiple engines compete for the remaining capacity:
    HYDROGEL (no delta) > VEV_4000 (delta=1.0) > OTM vouchers (delta<1)

Cap schedule:
    t <  850_000  →  soft ±80,  hard ±130
    t >= 850_000  →  terminal ±40  (ramp in sync with TerminalRamp)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.core.r3_products import (
    PRODUCT_TO_STRIKE,
    VELVETFRUIT_EXTRACT,
    VOUCHER_STRIKES,
)
from src.datamodel import Order

# ------------------------------------------------------------------ caps

TERMINAL_START: int = 850_000


@dataclass(frozen=True)
class DeltaCaps:
    soft: int = 80
    hard: int = 130
    terminal: int = 40


DEFAULT_CAPS: DeltaCaps = DeltaCaps()


# ----------------------------------------------------------------- deltas

def _voucher_delta(strike: int, spot: float | None) -> float:
    """Approximate BSM delta for deep-ITM/ATM/OTM vouchers.

    VEV_4000 is always treated as delta=1.0 (see EXECUTION_GUIDE pitfall #8).
    ATM/OTM strikes use a linear approximation based on moneyness.
    The SmileCache provides more accurate deltas when available; this
    is the fallback used when SmileCache has not warmed up yet.
    """
    if strike == 4000:
        return 1.0
    if spot is None or spot <= 0:
        return 0.5  # unknown; conservative
    moneyness = spot / strike
    # Rough approximation: delta ≈ N(d1) ≈ sigmoid-like on moneyness
    if moneyness >= 1.10:
        return 0.85
    if moneyness >= 1.02:
        return 0.70
    if moneyness >= 0.98:
        return 0.50
    if moneyness >= 0.90:
        return 0.25
    return 0.10


# ----------------------------------------------------------------- class

class R3DeltaBudget:
    """Tracks and enforces net-delta cap across all R3 products.

    Usage per tick:
        budget = R3DeltaBudget()
        budget.update_positions(positions, spot)
        remaining = budget.remaining_capacity(timestamp)
        safe_orders = budget.enforce(intended_orders, timestamp, positions, spot)
    """

    def __init__(self, caps: DeltaCaps = DEFAULT_CAPS) -> None:
        self._caps = caps
        # Cached delta estimates per voucher strike (updated by SmileCache
        # if available; falls back to _voucher_delta otherwise).
        self._strike_deltas: dict[int, float] = {
            k: 0.5 for k in VOUCHER_STRIKES
        }
        self._strike_deltas[4000] = 1.0  # invariant

    def set_strike_delta(self, strike: int, delta: float) -> None:
        """Update delta estimate from SmileCache (called once per tick)."""
        if strike == 4000:
            return  # VEV_4000 delta is always exactly 1.0
        self._strike_deltas[strike] = max(0.0, min(1.0, delta))

    def net_delta(
        self,
        positions: dict[str, int],
        spot: float | None = None,
    ) -> float:
        """Compute current net delta across all R3 products.

        net_delta = VELVET_pos
                  + VEV_4000_pos × 1.0
                  + Σ(voucher_pos[K] × delta[K])
        """
        nd: float = float(positions.get(VELVETFRUIT_EXTRACT, 0))
        for k in VOUCHER_STRIKES:
            product = f"VEV_{k}"
            pos = positions.get(product, 0)
            if pos != 0:
                delta = self._strike_deltas.get(k, _voucher_delta(k, spot))
                nd += pos * delta
        return nd

    def _cap_for(self, timestamp: int) -> int:
        if timestamp >= TERMINAL_START:
            return self._caps.terminal
        return self._caps.hard

    def remaining_capacity(
        self,
        timestamp: int,
        positions: dict[str, int],
        spot: float | None = None,
    ) -> int:
        """Signed remaining delta budget (positive = can add long delta)."""
        cap = self._cap_for(timestamp)
        nd = self.net_delta(positions, spot)
        # How far we are from the cap in each direction.
        long_room = cap - nd
        short_room = cap + nd
        return int(min(long_room, short_room))

    def enforce(
        self,
        intended_orders: list[Order],
        timestamp: int,
        positions: dict[str, int],
        spot: float | None = None,
    ) -> list[Order]:
        """Filter orders that would push net delta beyond the hard cap.

        Returns orders that are allowed. Orders that would cause a
        cap breach are dropped (not clipped — the strategy re-quotes
        next tick with the correct cap in mind).

        HYDROGEL orders pass through unchanged (no delta).
        VELVET orders are treated as delta-1 for cap purposes.
        VEV_4000 delta = 1.0. Other vouchers use cached deltas.
        """
        cap = self._cap_for(timestamp)
        nd = self.net_delta(positions, spot)

        safe: list[Order] = []
        for order in intended_orders:
            symbol = order.symbol
            qty = order.quantity  # positive = buy, negative = sell

            # HYDROGEL never contributes delta.
            if symbol == "HYDROGEL_PACK":
                safe.append(order)
                continue

            # Determine how much delta this order would add.
            strike = PRODUCT_TO_STRIKE.get(symbol)
            if symbol == VELVETFRUIT_EXTRACT:
                delta_per_unit = 1.0
            elif strike is not None:
                delta_per_unit = self._strike_deltas.get(
                    strike, _voucher_delta(strike, spot)
                )
            else:
                safe.append(order)
                continue

            order_delta = qty * delta_per_unit
            new_nd = nd + order_delta

            if abs(new_nd) <= cap:
                safe.append(order)
                nd = new_nd  # update running tally
            # else: drop this order — cap would be breached

        return safe

    def to_state(self) -> dict:
        return {"strike_deltas": dict(self._strike_deltas)}

    def from_state(self, blob: dict) -> None:
        saved = blob.get("strike_deltas", {})
        for k_str, v in saved.items():
            try:
                k = int(k_str)
                if k in self._strike_deltas and k != 4000:
                    self._strike_deltas[k] = float(v)
            except (ValueError, TypeError):
                pass

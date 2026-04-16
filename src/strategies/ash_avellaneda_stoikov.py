"""Avellaneda-Stoikov (2008) market-maker — research-only.

PLAN.md §4.1. Not part of the shipped submission bundle; only wired
at runtime by the Phase-C runner under
``outputs/round_1/ash_deep_dive/``. Live configs never reference it;
``STRATEGY_REGISTRY`` does not list it.

Formulas (per Avellaneda & Stoikov 2008, "High-frequency trading in
a limit order book"):

- Reservation price:        r(t, q) = s(t) - q * gamma * sigma^2 * (T - t)
- Optimal half-spread:      delta*(t) = gamma * sigma^2 * (T - t) / 2
                                       + (1 / gamma) * ln(1 + gamma / k)
- Maker quotes:             bid = r - delta*, ask = r + delta*

Where:
- s(t) is the current fair value (mid or an alternative estimator)
- q is the signed inventory in shares
- gamma is the risk-aversion parameter (> 0)
- sigma is the mid-price diffusion (ticks / sqrt(tick))
- k is the Poisson fill-intensity decay (lambda(delta) = A * exp(-k*delta))
- T - t is the time remaining in the episode (ticks)

Calibration (Phase A + Phase B):
- sigma ~ 2.0 ticks/sqrt(tick) (OU fit across 3 days)
- k ~ 0.4 (prior; trade-tape touch-only behavior makes empirical k
  unreliable)
- T = 100_000
- gamma sweep: {1e-7, 5e-7, 2e-6} — the corrected dimensionally-
  consistent range where gamma*sigma^2*T is O(1) tick per share.

Taker thresholds and flatten/recovery logic reuse the same
conventions as ``MarketMakingStrategy``; only the maker quote
prices and reservation-price shift are AS-specific.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    ExecutionMode,
    FairValueEstimate,
    NormalizedSnapshot,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class AvellanedaStoikovParams:
    """Parameters for the Avellaneda-Stoikov market-maker."""

    gamma: float                # risk aversion (> 0)
    sigma: float = 2.0          # OU diffusion per-tick (ticks / sqrt(tick))
    k: float = 0.4              # fill-intensity exponent (1/ticks)
    horizon: int = 100_000      # full-episode horizon T (ticks)
    taker_edge: float = 0.5     # reuse shipped taker edge
    min_half_spread: float = 0.5  # safety clip — never post below this
    flatten_threshold: float = 0.7

    def __post_init__(self) -> None:
        if self.gamma <= 0:
            raise ValueError("gamma must be > 0")
        if self.sigma <= 0:
            raise ValueError("sigma must be > 0")
        if self.k <= 0:
            raise ValueError("k must be > 0")
        if self.horizon <= 0:
            raise ValueError("horizon must be > 0")
        if self.taker_edge < 0:
            raise ValueError("taker_edge must be >= 0")
        if self.min_half_spread < 0:
            raise ValueError("min_half_spread must be >= 0")
        if not 0.0 <= self.flatten_threshold <= 1.0:
            raise ValueError("flatten_threshold must be in [0, 1]")


def reservation_price(
    fair: float, position: int, timestamp: int, params: AvellanedaStoikovParams,
) -> float:
    """Compute r(t, q) = s - q * gamma * sigma^2 * (T - t)."""
    time_remaining = max(0.0, float(params.horizon - timestamp))
    return fair - float(position) * params.gamma * (params.sigma ** 2) * time_remaining


def half_spread(timestamp: int, params: AvellanedaStoikovParams) -> float:
    """Compute delta*(t) per the AS closed-form."""
    time_remaining = max(0.0, float(params.horizon - timestamp))
    term1 = params.gamma * (params.sigma ** 2) * time_remaining / 2.0
    term2 = math.log(1.0 + params.gamma / params.k) / params.gamma
    return max(params.min_half_spread, term1 + term2)


class AshAvellanedaStoikovStrategy(BaseStrategy):
    """Market-maker with AS reservation-price + AS half-spread quotes."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: AvellanedaStoikovParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        params = self.params

        fair_value = self.fair_value_engine.estimate(
            product, snapshot, context.memory, config
        )
        return self._build_intent(product, snapshot, fair_value, config, params)

    def _build_intent(
        self,
        product: str,
        snapshot: NormalizedSnapshot,
        fair_value: FairValueEstimate,
        config: ProductConfig,
        params: AvellanedaStoikovParams,
    ) -> SignalIntent:
        r = reservation_price(
            fair=float(fair_value.price),
            position=snapshot.position,
            timestamp=snapshot.timestamp,
            params=params,
        )
        delta = half_spread(snapshot.timestamp, params)

        raw_bid = math.floor(r - delta)
        raw_ask = math.ceil(r + delta)
        if snapshot.best_ask is not None:
            raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
        if snapshot.best_bid is not None:
            raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

        buy_below: float | None = r - params.taker_edge
        sell_above: float | None = r + params.taker_edge

        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        flattening = abs(position_ratio) >= params.flatten_threshold
        mode: ExecutionMode = "hybrid"
        rationale = "ash_avellaneda_stoikov"
        bid_size = config.quote_size
        ask_size = config.quote_size
        if flattening:
            mode = "recovery"
            rationale = "ash_as_recovery"
            if snapshot.position > 0:
                bid_size = 0
                buy_below = None
                raw_ask = min(raw_ask, math.floor(float(fair_value.price)))
            elif snapshot.position < 0:
                ask_size = 0
                sell_above = None
                raw_bid = max(raw_bid, math.ceil(float(fair_value.price)))

        quote = QuoteIntent(
            bid_price=raw_bid if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=raw_ask if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "reservation_price": round(r, 4),
            "half_spread": round(delta, 4),
            "position_ratio": round(position_ratio, 4),
            "flattening": flattening,
            "gamma": params.gamma,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode=mode,
            buy_below=buy_below,
            sell_above=sell_above,
            quote=quote,
            rationale=rationale,
            metadata=MappingProxyType(metadata),
        )

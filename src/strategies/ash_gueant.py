"""Guéant-Lehalle-Fernandez-Tapia (2013) mean-reversion extension — research-only.

PLAN.md §4.2. Not part of shipped bundle; registered only at runtime
by the Phase-C runner.

Key result: under exponential utility + OU mean-reverting mid-price,
the Avellaneda-Stoikov inventory-adjustment term changes from

    gamma * sigma^2 * (T - t)                   (AS 2008, arithmetic Brownian)

to

    gamma * sigma^2 * (1 - exp(-2 theta (T - t))) / (2 theta)   (GLF-T, OU)

The half-spread formula has an analogous replacement. Intuition: fast
mean reversion (theta large) dissipates inventory risk — the MM should
not pay the full AS inventory-aversion term because the price tends
to return to mean within the episode.

At theta = 0 the GLF-T term collapses back to the AS term
(L'Hopital: lim (1 - exp(-2 theta tau))/(2 theta) = tau).

Calibration (Phase A):
- theta ~ 0.10 per tick (3-day mean of 0.085 / 0.135 / 0.073)
- sigma ~ 2.0 (same as AS)
- k ~ 0.4 (same as AS)
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
from src.strategies.ash_avellaneda_stoikov import AvellanedaStoikovParams
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class GueantParams(AvellanedaStoikovParams):
    """AS params extended with the OU mean-reversion speed theta."""

    theta: float = 0.10

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.theta < 0:
            raise ValueError("theta must be >= 0")


def mean_reverting_factor(timestamp: int, params: GueantParams) -> float:
    """Return (1 - exp(-2 theta (T - t))) / (2 theta).

    At theta = 0 returns (T - t) exactly (limit). At large theta*(T-t)
    saturates to 1 / (2 theta).
    """
    time_remaining = max(0.0, float(params.horizon - timestamp))
    if params.theta <= 0.0:
        return time_remaining
    return (1.0 - math.exp(-2.0 * params.theta * time_remaining)) / (2.0 * params.theta)


def gueant_reservation_price(
    fair: float, position: int, timestamp: int, params: GueantParams,
) -> float:
    factor = mean_reverting_factor(timestamp, params)
    return fair - float(position) * params.gamma * (params.sigma ** 2) * factor


def gueant_half_spread(timestamp: int, params: GueantParams) -> float:
    factor = mean_reverting_factor(timestamp, params)
    term1 = params.gamma * (params.sigma ** 2) * factor / 2.0
    term2 = math.log(1.0 + params.gamma / params.k) / params.gamma
    return max(params.min_half_spread, term1 + term2)


class AshGueantStrategy(BaseStrategy):
    """Mean-reverting-aware market-maker.

    Same structural skeleton as ``AshAvellanedaStoikovStrategy``; the
    only change is that ``reservation_price`` and ``half_spread`` use
    the GLF-T mean-reverting factor instead of the naive (T - t).
    """

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: GueantParams,
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
        params: GueantParams,
    ) -> SignalIntent:
        r = gueant_reservation_price(
            fair=float(fair_value.price),
            position=snapshot.position,
            timestamp=snapshot.timestamp,
            params=params,
        )
        delta = gueant_half_spread(snapshot.timestamp, params)

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
        rationale = "ash_gueant"
        bid_size = config.quote_size
        ask_size = config.quote_size
        if flattening:
            mode = "recovery"
            rationale = "ash_gueant_recovery"
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
            "mr_factor": round(mean_reverting_factor(snapshot.timestamp, params), 4),
            "theta": params.theta,
            "gamma": params.gamma,
            "position_ratio": round(position_ratio, 4),
            "flattening": flattening,
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

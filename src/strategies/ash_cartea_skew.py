"""Cartea-Jaimungal residual-alpha-skewed market-maker — research-only.

PLAN.md §4.3. Not part of shipped bundle; registered only at runtime
by the Phase-C runner.

Mechanism: on top of a symmetric base maker + taker edge, apply an
asymmetric quote shift driven by the z-scored residual of a
short-horizon fair-value estimator.

    alpha(t) = (mid(t) - fair_alpha(t)) / sigma_residual

    delta_bid  = maker_edge + beta * alpha(t)
    delta_ask  = maker_edge - beta * alpha(t)

    maker_bid  = fair_quote - delta_bid
    maker_ask  = fair_quote + delta_ask

Intuition (with our sign convention ``residual = mid - fair``):
- alpha > 0: mid is above fair → forward mid drops (Phase-A corr =
  -0.6). We should make it easier to sell (narrower ask, smaller
  ``delta_ask``) and harder to buy (wider bid, larger ``delta_bid``).
  Equivalent: the whole bid-ask center shifts down by ``beta * alpha``
  ticks.
- alpha < 0: mid below fair → mid rises. Center shifts up.

``fair_quote`` is the primary FV used for quoting (from the product
config, typically ``wall_mid``). ``fair_alpha`` is the secondary FV
used only to build the alpha signal — Phase A showed ``ewma_mid`` has
the tightest residual sigma (~1.06) and strongest correlation
(~-0.62), so that is the Cartea-alpha default.

Phase-A priors:
- sigma_residual_prior = 1.06 (ewma_mid)
- corr(residual, fwd_return, h=1) = -0.62
- beta grid: {0.3, 0.6, 1.0, 1.5} ticks
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import ESTIMATORS, FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    ExecutionMode,
    FairValueEstimate,
    NormalizedSnapshot,
    ProductMemory,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class CarteaSkewParams:
    """Parameters for the Cartea-Jaimungal alpha-skewed MM."""

    beta: float                                 # tick-skew per unit-z alpha
    fv_for_alpha: str = "ewma_mid"              # short-horizon FV for the alpha signal
    sigma_residual_prior: float = 1.06          # Phase-A measurement for ewma_mid
    alpha_clip: float = 3.0                     # clip |alpha| to this (robustness)
    flatten_threshold: float = 0.7

    def __post_init__(self) -> None:
        if self.beta < 0:
            raise ValueError("beta must be >= 0")
        if self.sigma_residual_prior <= 0:
            raise ValueError("sigma_residual_prior must be > 0")
        if self.alpha_clip <= 0:
            raise ValueError("alpha_clip must be > 0")
        if self.fv_for_alpha not in ESTIMATORS:
            raise ValueError(
                f"fv_for_alpha must be a registered estimator; got {self.fv_for_alpha!r}"
            )
        if not 0.0 <= self.flatten_threshold <= 1.0:
            raise ValueError("flatten_threshold must be in [0, 1]")


def compute_alpha(
    snapshot: NormalizedSnapshot,
    memory: ProductMemory,
    config: ProductConfig,
    params: CarteaSkewParams,
) -> float:
    """Return the clipped z-scored residual used as the short-term alpha."""
    if snapshot.mid is None:
        return 0.0
    estimator = ESTIMATORS.get(params.fv_for_alpha)
    if estimator is None:
        return 0.0
    est = estimator.estimate(snapshot, memory, config)
    if est is None:
        return 0.0
    residual = float(snapshot.mid) - float(est.price)
    z = residual / params.sigma_residual_prior
    return max(-params.alpha_clip, min(params.alpha_clip, z))


class AshCarteaSkewStrategy(BaseStrategy):
    """Market-maker with asymmetric quote skew on a short-horizon alpha.

    Quote prices = C_h1_alt-style symmetric base, then shifted by
    ``beta * alpha`` ticks. Sizes / flatten logic mirror the shipped
    ``MarketMakingStrategy`` for comparability.
    """

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: CarteaSkewParams,
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
        alpha = compute_alpha(snapshot, context.memory, config, params)
        return self._build_intent(product, snapshot, fair_value, config, params, alpha)

    def _build_intent(
        self,
        product: str,
        snapshot: NormalizedSnapshot,
        fair_value: FairValueEstimate,
        config: ProductConfig,
        params: CarteaSkewParams,
        alpha: float,
    ) -> SignalIntent:
        # Standard inventory skew (reuse shipped linear behavior).
        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        inv_skew = position_ratio * config.inventory_skew

        # Cartea asymmetric quote shift: center shifts by -beta*alpha
        # (alpha > 0 predicts mid drop → shift center DOWN so ask is
        # closer to mid, bid further away).
        alpha_shift = params.beta * alpha

        base_fair = float(fair_value.price)
        buy_below: float | None = base_fair - config.taker_edge - inv_skew - alpha_shift
        sell_above: float | None = base_fair + config.taker_edge - inv_skew - alpha_shift

        raw_bid = math.floor(base_fair - config.maker_edge - inv_skew - alpha_shift)
        raw_ask = math.ceil(base_fair + config.maker_edge - inv_skew - alpha_shift)

        if snapshot.best_ask is not None:
            raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
        if snapshot.best_bid is not None:
            raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

        bid_size = config.quote_size
        ask_size = config.quote_size
        mode: ExecutionMode = "hybrid"
        rationale = "ash_cartea_skew"
        flattening = abs(position_ratio) >= params.flatten_threshold
        if flattening:
            mode = "recovery"
            rationale = "ash_cartea_recovery"
            if snapshot.position > 0:
                bid_size = 0
                buy_below = None
                raw_ask = min(raw_ask, math.floor(base_fair))
            elif snapshot.position < 0:
                ask_size = 0
                sell_above = None
                raw_bid = max(raw_bid, math.ceil(base_fair))

        quote = QuoteIntent(
            bid_price=raw_bid if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=raw_ask if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "alpha": round(alpha, 4),
            "alpha_shift": round(alpha_shift, 4),
            "beta": params.beta,
            "fv_for_alpha": params.fv_for_alpha,
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

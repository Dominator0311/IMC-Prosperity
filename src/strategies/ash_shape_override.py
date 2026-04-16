"""Research-only ASH strategy with overridable skew / flatten / size shapes.

This module is **not** part of the shipped submission bundle. It is
registered only at runtime by the Phase-B / Phase-D runners in
``outputs/round_1/ash_deep_dive/``. Live configs never reference it;
``STRATEGY_REGISTRY`` does not list it.

Purpose: exercise the three shape-levers from PLAN.md §3.3-§3.5 (B3
inventory-skew shape, B4 flatten mechanism, B5 quote-size skew)
independently and in combination, while keeping the fair-value /
edge-width / history path identical to the shipped
``MarketMakingStrategy``.

Defaults reproduce the current best leg (C_h1_alt) exactly: linear
skew with coefficient 4.0, hard flatten at |position/limit| >= 0.7,
constant per-side quote size = config.quote_size. Changing any
``ShapeParams`` field is a pure *override* of the SignalEngine
behavior at that axis; the other two axes stay at their C_h1_alt
defaults so single-lever isolation is meaningful.
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

SKEW_MODES: tuple[str, ...] = ("linear", "as", "tanh", "quadratic")
FLATTEN_MODES: tuple[str, ...] = ("hard", "soft_target", "as_continuous")
SIZE_MODES: tuple[str, ...] = ("constant", "linear", "as_optimal", "stepwise")


@dataclass(frozen=True)
class ShapeParams:
    """All tunable shape knobs for the Phase-B override strategy.

    Defaults reproduce C_h1_alt. Changing any single field isolates
    one lever.
    """

    # B3 — inventory-skew shape
    skew_mode: str = "linear"
    skew_coef: float = 4.0          # linear / tanh / quadratic multiplier
    as_gamma: float = 0.10          # AS risk-aversion (used by "as" skew AND flatten)
    as_sigma: float = 2.0           # OU sigma from Phase A (ticks / sqrt(tick))
    as_horizon: int = 100_000       # total-episode tick horizon (T in AS)

    # B4 — flatten mechanism
    flatten_mode: str = "hard"
    flatten_threshold: float = 0.7  # hard threshold on |position_ratio|
    flatten_k: float = 0.5          # soft-target pull coefficient

    # B5 — quote-size skew
    size_mode: str = "constant"
    size_min: int = 1
    size_max: int = 10
    size_step_ratio: float = 0.5    # for stepwise mode

    def __post_init__(self) -> None:
        if self.skew_mode not in SKEW_MODES:
            raise ValueError(f"skew_mode must be one of {SKEW_MODES!r}")
        if self.flatten_mode not in FLATTEN_MODES:
            raise ValueError(f"flatten_mode must be one of {FLATTEN_MODES!r}")
        if self.size_mode not in SIZE_MODES:
            raise ValueError(f"size_mode must be one of {SIZE_MODES!r}")
        if self.as_gamma <= 0:
            raise ValueError("as_gamma must be > 0")
        if self.as_sigma <= 0:
            raise ValueError("as_sigma must be > 0")
        if self.as_horizon <= 0:
            raise ValueError("as_horizon must be > 0")
        if not 0.0 <= self.flatten_threshold <= 1.0:
            raise ValueError("flatten_threshold must be in [0, 1]")
        if self.flatten_k < 0:
            raise ValueError("flatten_k must be >= 0")
        if self.size_min < 0 or self.size_max < self.size_min:
            raise ValueError("size bounds must satisfy 0 <= size_min <= size_max")
        if not 0.0 <= self.size_step_ratio <= 1.0:
            raise ValueError("size_step_ratio must be in [0, 1]")


def compute_skew(
    *,
    position_ratio: float,
    config: ProductConfig,
    params: ShapeParams,
    time_remaining: float,
) -> float:
    """Return the price-side skew term (ticks).

    Conventions:
    - Positive position_ratio (long) -> positive skew -> quotes shift
      down (bid pulled lower, ask pulled lower) to discourage more
      buying and encourage selling. This matches the shipped
      ``SignalEngine`` sign convention.
    """
    coef = params.skew_coef if params.skew_coef > 0 else config.inventory_skew
    if params.skew_mode == "linear":
        return coef * position_ratio
    if params.skew_mode == "as":
        # Avellaneda-Stoikov reservation price term: q * gamma * sigma^2 * (T - t).
        # position_ratio is normalized, so rescale back to shares.
        q = position_ratio * float(config.position_limit)
        return q * params.as_gamma * (params.as_sigma ** 2) * max(time_remaining, 0.0)
    if params.skew_mode == "tanh":
        return coef * math.tanh(2.0 * position_ratio)
    if params.skew_mode == "quadratic":
        return coef * math.copysign(position_ratio * position_ratio, position_ratio)
    raise ValueError(f"unhandled skew_mode: {params.skew_mode!r}")


def compute_sizes(
    *,
    position_ratio: float,
    config: ProductConfig,
    params: ShapeParams,
) -> tuple[int, int]:
    """Return per-side ``(bid_size, ask_size)``.

    position_ratio > 0 -> long -> shrink bid_size (don't want more
    longs), grow ask_size (want to offload). Mirrored for short.
    """
    base = config.quote_size
    lo, hi = params.size_min, params.size_max
    if params.size_mode == "constant":
        return base, base
    if params.size_mode == "linear":
        bid = round(base * (1.0 - position_ratio))
        ask = round(base * (1.0 + position_ratio))
        return max(lo, min(hi, bid)), max(lo, min(hi, ask))
    if params.size_mode == "as_optimal":
        # AS marginal size scales with 1/(gamma * sigma^2 * (T - t)).
        # Normalize to be close to `base` when gamma*sigma^2*T ~ 1.
        denom = max(1e-9, params.as_gamma * (params.as_sigma ** 2))
        raw = base / denom
        size = round(raw)
        size = max(lo, min(hi, size))
        # Keep a small asymmetry proportional to inventory (signed).
        shift = round(size * position_ratio)
        return max(lo, size - shift), max(lo, size + shift)
    if params.size_mode == "stepwise":
        # If |position_ratio| > size_step_ratio, shrink "adding" side
        # to size_min and grow "unwinding" side to size_max.
        if position_ratio > params.size_step_ratio:
            return lo, hi
        if position_ratio < -params.size_step_ratio:
            return hi, lo
        return base, base
    raise ValueError(f"unhandled size_mode: {params.size_mode!r}")


def compute_flatten(
    *,
    position_ratio: float,
    config: ProductConfig,
    params: ShapeParams,
) -> tuple[bool, float]:
    """Return ``(is_flattening, extra_skew_from_flatten)``.

    Shapes:
    - ``hard``: boolean threshold identical to SignalEngine.
    - ``soft_target``: continuous pull; extra_skew grows with
      ``flatten_k * position_ratio`` — the strategy never enters
      "recovery" mode, but the continuous pull guides inventory back
      to zero smoothly.
    - ``as_continuous``: the AS reservation-price term in ``compute_skew``
      already accounts for inventory risk via ``q*gamma*sigma^2*(T-t)``.
      We disable the hard threshold entirely.
    """
    if params.flatten_mode == "hard":
        return abs(position_ratio) >= params.flatten_threshold, 0.0
    if params.flatten_mode == "soft_target":
        # No hard flatten; continuous pull via extra_skew.
        extra = params.flatten_k * params.skew_coef * position_ratio
        return False, extra
    if params.flatten_mode == "as_continuous":
        # Disable hard flatten; AS term in skew handles it.
        return False, 0.0
    raise ValueError(f"unhandled flatten_mode: {params.flatten_mode!r}")


class AshShapeOverrideStrategy(BaseStrategy):
    """ASH market-maker with overridable skew / flatten / size shapes.

    Replicates the intent-building logic of
    ``SignalEngine.build_market_making_intent`` but routes the three
    shape-lever computations through the ``ShapeParams``-driven
    primitives above.
    """

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: ShapeParams,
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
        params: ShapeParams,
    ) -> SignalIntent:
        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        time_remaining = max(0.0, float(params.as_horizon) - float(snapshot.timestamp))
        skew = compute_skew(
            position_ratio=position_ratio,
            config=config,
            params=params,
            time_remaining=time_remaining,
        )
        flattening, extra_skew = compute_flatten(
            position_ratio=position_ratio, config=config, params=params,
        )
        skew += extra_skew

        buy_below: float | None = fair_value.price - config.taker_edge - skew
        sell_above: float | None = fair_value.price + config.taker_edge - skew

        raw_bid = math.floor(fair_value.price - config.maker_edge - skew)
        raw_ask = math.ceil(fair_value.price + config.maker_edge - skew)

        if snapshot.best_ask is not None:
            raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
        if snapshot.best_bid is not None:
            raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

        bid_size, ask_size = compute_sizes(
            position_ratio=position_ratio, config=config, params=params,
        )

        mode: ExecutionMode = "hybrid"
        rationale = "ash_shape_override"
        if flattening:
            mode = "recovery"
            rationale = "ash_shape_override_recovery"
            if snapshot.position > 0:
                bid_size = 0
                buy_below = None
                raw_ask = min(raw_ask, math.floor(fair_value.price))
            elif snapshot.position < 0:
                ask_size = 0
                sell_above = None
                raw_bid = max(raw_bid, math.ceil(fair_value.price))

        quote = QuoteIntent(
            bid_price=raw_bid if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=raw_ask if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "position_ratio": round(position_ratio, 4),
            "skew": round(skew, 4),
            "flattening": flattening,
            "skew_mode": params.skew_mode,
            "flatten_mode": params.flatten_mode,
            "size_mode": params.size_mode,
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

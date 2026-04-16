"""Target-position mean-reversion strategy for ASH (research only).

This module is **not** part of the live submission bundle. It lives
under ``src/strategies/`` so it can reuse ``BaseStrategy`` /
``FairValueEngine`` / ``SignalEngine``, but it is registered only at
runtime by the Phase-10 research runner in
``outputs/round_1/ash_target/run_ash_target.py``. Live configs never
reference it; ``STRATEGY_REGISTRY`` does not list it.

Core idea: given ``r = price - mean`` pick a signed target position
``q*(r)`` (linear, dead-zone linear, or convex) and emit quotes /
taker thresholds that move current position toward the target.

Params are passed via :class:`TargetPositionParams` on the
strategy constructor — deliberately **not** added to ``ProductConfig``
to keep the live engine surface untouched.
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
    ProductMemory,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext

MODES: tuple[str, ...] = ("linear", "dead_zone", "convex")
STYLES: tuple[str, ...] = ("maker", "taker", "hybrid")
# Phase-10 used ("anchor", "fair"); Phase-C C5 adds "ewma" for the
# EWMA-of-mid anchor (PLAN.md §4.5 fix #1).
MEAN_SOURCES: tuple[str, ...] = ("anchor", "fair", "ewma")


@dataclass(frozen=True)
class TargetPositionParams:
    """All tunable knobs for the target-position strategy.

    Any ``None``/zero-like value leaves the corresponding feature
    inactive. Validated on construction so bad values fail the runner,
    not mid-replay.

    Phase-C C5 additions (default values reproduce Phase-10 behavior):
    - ``ewma_tau``: lookback for ``mean_source="ewma"`` (in snapshot
      steps). With the engine's 100-tick cadence, ``tau=2000`` means a
      2000-tick half-life. Only consulted when ``mean_source="ewma"``.
    - ``sigma_ref``: divides ``alpha`` to make the effective pull
      invariant to typical residual magnitude. Phase-A measured
      ``ewma_mid`` residual sigma ~ 1.06; ``sigma_ref=1.0`` keeps the
      Phase-10 behavior when untouched.
    - ``clip_to_flatten``: when True, the target-position is clipped to
      ``floor(flatten_threshold * position_limit)`` so the shipped
      flatten valve engages *before* any single-step overshoot.
      Addresses Phase-10 saturation failure mode #4.
    """

    mode: str = "dead_zone"
    mean_source: str = "anchor"
    alpha: float = 0.0
    dead_zone: float = 0.0
    gamma: float = 1.0
    cap: int | None = None
    exec_style: str = "hybrid"
    hybrid_threshold: float = 2.0
    maker_edge_offset: float = 0.0
    # Phase-C C5 additions
    ewma_tau: float = 2000.0
    sigma_ref: float = 1.0
    clip_to_flatten: bool = False

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES!r}")
        if self.mean_source not in MEAN_SOURCES:
            raise ValueError(f"mean_source must be one of {MEAN_SOURCES!r}")
        if self.exec_style not in STYLES:
            raise ValueError(f"exec_style must be one of {STYLES!r}")
        if self.alpha < 0:
            raise ValueError("alpha must be >= 0")
        if self.dead_zone < 0:
            raise ValueError("dead_zone must be >= 0")
        if self.gamma <= 0:
            raise ValueError("gamma must be > 0")
        if self.cap is not None and self.cap < 0:
            raise ValueError("cap must be >= 0 when set")
        if self.hybrid_threshold < 0:
            raise ValueError("hybrid_threshold must be >= 0")
        if self.ewma_tau <= 0:
            raise ValueError("ewma_tau must be > 0")
        if self.sigma_ref <= 0:
            raise ValueError("sigma_ref must be > 0")


def compute_target_position(
    residual: float,
    *,
    mode: str,
    alpha: float,
    dead_zone: float,
    gamma: float,
    cap: int,
) -> int:
    """Return the signed integer target position for a given residual.

    ``residual = price - mean``. Positive residual -> negative target
    (we want to be short when price is above the mean).
    """
    if cap <= 0 or alpha <= 0:
        return 0
    if mode == "linear":
        raw = -alpha * residual
    elif mode == "dead_zone":
        abs_r = abs(residual)
        if abs_r <= dead_zone:
            return 0
        raw = -alpha * math.copysign(abs_r - dead_zone, residual)
    elif mode == "convex":
        abs_r = abs(residual)
        if abs_r < 1e-9:
            return 0
        raw = -math.copysign(alpha * (abs_r**gamma), residual)
    else:  # pragma: no cover — validated by TargetPositionParams
        return 0
    if raw > cap:
        raw = cap
    elif raw < -cap:
        raw = -cap
    return round(raw)


def _resolve_mean(
    fair_value: FairValueEstimate,
    config: ProductConfig,
    params: TargetPositionParams,
    memory: ProductMemory | None = None,
) -> float:
    if params.mean_source == "anchor" and config.anchor_price is not None:
        return float(config.anchor_price)
    if params.mean_source == "ewma" and memory is not None:
        ewma = _ewma_of_recent_mids(memory.recent_mids, tau=params.ewma_tau)
        if ewma is not None:
            return ewma
    return float(fair_value.price)


def _ewma_of_recent_mids(recent_mids: list[float], tau: float) -> float | None:
    """Exponential moving average of ``recent_mids`` with discrete tau.

    Uses alpha = 1 - exp(-1/tau). tau is expressed in snapshot steps.
    Recent-most sample is last in the list. Returns None for empty
    history.
    """
    if not recent_mids:
        return None
    alpha = 1.0 - math.exp(-1.0 / max(tau, 1.0))
    ewma = float(recent_mids[0])
    for m in recent_mids[1:]:
        ewma = alpha * float(m) + (1.0 - alpha) * ewma
    return ewma


def _resolve_cap(config: ProductConfig, params: TargetPositionParams) -> int:
    """Resolve the absolute target-position cap.

    When ``clip_to_flatten`` is True (Phase-C C5 fix #3), the target is
    additionally clipped to ``floor(flatten_threshold * position_limit)``
    so the flatten valve engages *before* a single-step overshoot can
    drive position above the limit. This is the fix for Phase-10's
    saturation failure mode (~334/1000 near-limit on high-alpha cells).
    """
    hard_cap = params.cap if params.cap is not None else config.position_limit
    hard_cap = min(hard_cap, config.position_limit)
    if params.clip_to_flatten:
        flatten_cap = math.floor(config.flatten_threshold * config.position_limit)
        hard_cap = min(hard_cap, flatten_cap)
    return max(0, hard_cap)


class AshTargetPositionStrategy(BaseStrategy):
    """Target-position mean-reversion strategy."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: TargetPositionParams,
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

        if params.alpha <= 0:
            # Zero-alpha means "no target pull". Fall back to the
            # legacy MM intent so the product keeps trading.
            return self.signal_engine.build_market_making_intent(
                product, snapshot, fair_value, config
            )

        mean = _resolve_mean(fair_value, config, params, memory=context.memory)
        cap = _resolve_cap(config, params)
        price = float(snapshot.mid) if snapshot.mid is not None else float(fair_value.price)
        residual = price - mean
        # Phase-C C5 fix #2: sigma-aware alpha. Divide by the prior
        # sigma-of-residual so the effective pull is invariant to the
        # typical residual magnitude. Default sigma_ref=1.0 reproduces
        # Phase-10 behavior exactly.
        effective_alpha = params.alpha / params.sigma_ref
        target = compute_target_position(
            residual,
            mode=params.mode,
            alpha=effective_alpha,
            dead_zone=params.dead_zone,
            gamma=params.gamma,
            cap=cap,
        )
        gap = target - snapshot.position

        style = params.exec_style
        taker_eligible = style == "taker" or (
            style == "hybrid" and abs(residual) >= params.hybrid_threshold
        )
        maker_eligible = style in ("maker", "hybrid", "taker")

        buy_below: float | None = None
        sell_above: float | None = None
        if taker_eligible:
            if gap > 0:
                buy_below = mean - config.taker_edge
            elif gap < 0:
                sell_above = mean + config.taker_edge

        bid_price: int | None = None
        ask_price: int | None = None
        bid_size = 0
        ask_size = 0
        if maker_eligible:
            maker_edge = max(0.0, config.maker_edge + params.maker_edge_offset)
            raw_bid = math.floor(mean - maker_edge)
            raw_ask = math.ceil(mean + maker_edge)
            if snapshot.best_ask is not None:
                raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
            if snapshot.best_bid is not None:
                raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

            if gap > 0:
                bid_price = raw_bid
                bid_size = min(config.quote_size, max(1, gap))
            elif gap < 0:
                ask_price = raw_ask
                ask_size = min(config.quote_size, max(1, -gap))
            else:
                bid_price = raw_bid
                ask_price = raw_ask
                bid_size = max(1, config.quote_size // 2)
                ask_size = max(1, config.quote_size // 2)

        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        flattening = abs(position_ratio) >= config.flatten_threshold
        mode: ExecutionMode = "hybrid"
        rationale = "ash_target_position"
        if flattening:
            mode = "recovery"
            rationale = "ash_target_flatten"
            if snapshot.position > 0:
                bid_size = 0
                bid_price = None
                buy_below = None
            elif snapshot.position < 0:
                ask_size = 0
                ask_price = None
                sell_above = None

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "mean": round(mean, 4),
            "residual": round(residual, 4),
            "target_position": target,
            "position_gap": gap,
            "position_ratio": round(position_ratio, 4),
            "taker_eligible": taker_eligible,
            "style": style,
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

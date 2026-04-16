"""PEPPER core-long + residual-overlay strategy (research-only).

This module is **not** part of the live submission bundle. It lives
under ``src/strategies/`` so it can reuse ``BaseStrategy`` /
``FairValueEngine`` / ``SignalEngine``, but it is wired in only at
runtime by the research runner in
``outputs/round_1/pepper_corelong/run_search.py``. Live configs never
reference it; ``STRATEGY_REGISTRY`` does not list it.

Core idea (see
``outputs/round_1/pepper_corelong/pepper_corelong_memo.md`` for the
full rationale):

    target_position(t) = base_long + overlay(residual(t))

where ``residual(t) = mid(t) - drift_fair(t)`` and ``overlay`` is
deliberately asymmetric:

- residual < -add_thresh → open above base_long (add_gain × excess)
- residual > +trim_thresh → trim below base_long (trim_gain × excess)
- otherwise overlay = 0

The final target is clipped to ``[floor, ceiling]`` with ``floor ≥ 0``
so the strategy never flips net short on a mild positive residual.
Adjustment toward the target is rate-limited by ``step`` units per
tick.

Params are passed via ``CoreLongParams`` on the strategy constructor —
deliberately NOT added to ``ProductConfig`` to keep the live engine
surface untouched, following the same pattern as
``src.strategies.ash_target_position``.
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
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext

EXEC_STYLES: tuple[str, ...] = ("maker", "hybrid", "taker")
OPEN_TAKE_MODES: tuple[str, ...] = ("all_asks", "level1_only")

# Opening-phase crossing threshold: high enough to cross any ask
# inside the book, matching ``BuyAndHoldStrategy``'s _TAKE_ANY_ASK
# pattern. Without this, the opening seed would use the default
# ``fair_price - config.taker_edge`` crossing gate, which stays well
# below the best ask and produces zero opening fills.
_OPENING_TAKE_ANY_ASK: float = 1e9


@dataclass(frozen=True)
class CoreLongParams:
    """All tunable knobs for the PEPPER core-long + overlay strategy.

    Defaults correspond to a mild, centered nominal (base_long=30,
    asymmetric bands add<trim, moderate step, hybrid execution).

    Opening acquisition (v2): ``open_seed_size`` > 0 activates an
    explicit tick-0 / early-session acquisition phase that overrides
    the persistent_core + overlay target while
    ``snapshot.timestamp <= open_window``. This is the v1 gap-closer —
    v1 showed all market-making variants leave ~+19 k of first-25k PnL
    on the table because the ``linear_drift`` estimator hasn't warmed
    up enough to trigger a residual-driven buy. Setting
    ``open_seed_size=30`` with ``open_window=0`` forces a taker
    acquisition toward +30 on the first snapshot of each day
    regardless of the estimator's confidence. ``open_no_short=True``
    additionally suppresses sell quotes for the duration of the
    opening window so the bot cannot accidentally trim during the
    seed.

    Validation happens at construction time so bad candidates fail
    the runner, not mid-replay.
    """

    base_long: int = 30
    # Residual threshold magnitudes (always non-negative).
    add_thresh: float = 3.0
    trim_thresh: float = 5.0
    # Linear gains applied to the excess beyond each threshold.
    add_gain: float = 2.0
    trim_gain: float = 1.0
    # Position clipping. floor >= 0 prevents net shorts.
    floor: int = 0
    ceiling: int = 80
    # Max |position change| per tick.
    step: int = 8
    # Execution policy.
    exec_style: str = "hybrid"
    # For hybrid: only cross the spread when |residual| >= this many ticks.
    hybrid_threshold: float = 2.0
    # Maker-side edge tightening (-offset = tighter). Keep at 0 for default.
    maker_edge_offset: float = 0.0
    # ---- v2: opening acquisition ----
    # Target inventory to acquire during the opening window.
    # 0 disables the opening branch (backward compatible with v1).
    open_seed_size: int = 0
    # Opening window: while ``snapshot.timestamp <= open_window`` the
    # target is ``open_seed_size`` (clipped to ceiling) instead of
    # ``base_long + overlay``. open_window=0 means only t=0.
    open_window: int = 0
    # If True, the strategy never emits sell-side intents while in
    # the opening window — forces net-long acquisition.
    open_no_short: bool = True
    # Opening taker mode: either cross every visible ask up to
    # ``max_aggressive_size`` or only take the current best ask level.
    open_take_mode: str = "all_asks"
    # ---- v4: negative-drift protection ----
    # If > 0, fit a rolling OLS line over the most recent mids (plus
    # current mid) and cap the target at ``guard_target`` whenever the
    # fitted slope is <= -guard_negative_slope and the fit quality
    # exceeds ``guard_r2_min``.
    guard_window: int = 0
    guard_negative_slope: float = 0.0
    guard_r2_min: float = 0.0
    guard_target: int = 0
    # ---- v4: residual + imbalance micro-timer ----
    # Small, additive target bias when residual and book imbalance agree.
    micro_residual_threshold: float = 0.0
    micro_imbalance_threshold: float = 1.0
    micro_add_size: int = 0
    micro_trim_size: int = 0
    # ---- v5: adaptive long-cap tiers ----
    # Optional regime-dependent cap on maximum long inventory.
    adaptive_caps_enabled: bool = False
    adaptive_r2_min: float = 0.0
    adaptive_mid_slope: float = 0.0
    adaptive_high_slope: float = 0.0
    adaptive_low_cap: int = 0
    adaptive_mid_cap: int = 0
    adaptive_high_cap: int = 0

    def __post_init__(self) -> None:
        if self.base_long < 0:
            raise ValueError(f"base_long must be >= 0 (got {self.base_long})")
        if self.add_thresh < 0:
            raise ValueError(f"add_thresh must be >= 0 (got {self.add_thresh})")
        if self.trim_thresh < 0:
            raise ValueError(f"trim_thresh must be >= 0 (got {self.trim_thresh})")
        if self.add_gain < 0:
            raise ValueError(f"add_gain must be >= 0 (got {self.add_gain})")
        if self.trim_gain < 0:
            raise ValueError(f"trim_gain must be >= 0 (got {self.trim_gain})")
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if self.step <= 0:
            raise ValueError(f"step must be > 0 (got {self.step})")
        if self.exec_style not in EXEC_STYLES:
            raise ValueError(
                f"exec_style must be one of {EXEC_STYLES!r} (got {self.exec_style!r})"
            )
        if self.hybrid_threshold < 0:
            raise ValueError(
                f"hybrid_threshold must be >= 0 (got {self.hybrid_threshold})"
            )
        if self.open_seed_size < 0:
            raise ValueError(
                f"open_seed_size must be >= 0 (got {self.open_seed_size})"
            )
        if self.open_seed_size > self.ceiling:
            raise ValueError(
                f"open_seed_size ({self.open_seed_size}) must be <= "
                f"ceiling ({self.ceiling})"
            )
        if self.open_window < 0:
            raise ValueError(f"open_window must be >= 0 (got {self.open_window})")
        if self.open_take_mode not in OPEN_TAKE_MODES:
            raise ValueError(
                f"open_take_mode must be one of {OPEN_TAKE_MODES!r} "
                f"(got {self.open_take_mode!r})"
            )
        if self.guard_window < 0:
            raise ValueError(f"guard_window must be >= 0 (got {self.guard_window})")
        if self.guard_negative_slope < 0:
            raise ValueError(
                "guard_negative_slope must be >= 0 "
                f"(got {self.guard_negative_slope})"
            )
        if not 0.0 <= self.guard_r2_min <= 1.0:
            raise ValueError(
                f"guard_r2_min must be in [0, 1] (got {self.guard_r2_min})"
            )
        guard_enabled = (
            self.guard_window > 0
            or self.guard_negative_slope > 0
            or self.guard_r2_min > 0
        )
        if guard_enabled and not self.floor <= self.guard_target <= self.ceiling:
            raise ValueError(
                "guard_target must lie inside [floor, ceiling] "
                f"(got floor={self.floor}, guard_target={self.guard_target}, "
                f"ceiling={self.ceiling})"
            )
        if self.micro_residual_threshold < 0:
            raise ValueError(
                "micro_residual_threshold must be >= 0 "
                f"(got {self.micro_residual_threshold})"
            )
        if not 0.0 <= self.micro_imbalance_threshold <= 1.0:
            raise ValueError(
                "micro_imbalance_threshold must be in [0, 1] "
                f"(got {self.micro_imbalance_threshold})"
            )
        if self.micro_add_size < 0:
            raise ValueError(
                f"micro_add_size must be >= 0 (got {self.micro_add_size})"
            )
        if self.micro_trim_size < 0:
            raise ValueError(
                f"micro_trim_size must be >= 0 (got {self.micro_trim_size})"
            )
        if not 0.0 <= self.adaptive_r2_min <= 1.0:
            raise ValueError(
                f"adaptive_r2_min must be in [0, 1] (got {self.adaptive_r2_min})"
            )
        if self.adaptive_mid_slope < 0:
            raise ValueError(
                f"adaptive_mid_slope must be >= 0 (got {self.adaptive_mid_slope})"
            )
        if self.adaptive_high_slope < 0:
            raise ValueError(
                f"adaptive_high_slope must be >= 0 (got {self.adaptive_high_slope})"
            )
        if self.adaptive_high_slope < self.adaptive_mid_slope:
            raise ValueError(
                "adaptive_high_slope must be >= adaptive_mid_slope "
                f"(got mid={self.adaptive_mid_slope}, high={self.adaptive_high_slope})"
            )
        adaptive_caps = (
            self.adaptive_low_cap,
            self.adaptive_mid_cap,
            self.adaptive_high_cap,
        )
        if any(cap < 0 for cap in adaptive_caps):
            raise ValueError(
                "adaptive_*_cap must be >= 0 "
                f"(got low={self.adaptive_low_cap}, mid={self.adaptive_mid_cap}, "
                f"high={self.adaptive_high_cap})"
            )
        if self.adaptive_caps_enabled:
            if self.guard_window <= 0:
                raise ValueError(
                    "adaptive_caps_enabled requires guard_window > 0 "
                    f"(got {self.guard_window})"
                )
            if not self.floor <= self.adaptive_low_cap <= self.adaptive_mid_cap <= self.adaptive_high_cap:
                raise ValueError(
                    "adaptive caps must be ordered inside [floor, ceiling] "
                    f"(got floor={self.floor}, low={self.adaptive_low_cap}, "
                    f"mid={self.adaptive_mid_cap}, high={self.adaptive_high_cap}, "
                    f"ceiling={self.ceiling})"
                )
            if self.adaptive_high_cap > self.ceiling:
                raise ValueError(
                    "adaptive_high_cap must be <= ceiling "
                    f"(got high={self.adaptive_high_cap}, ceiling={self.ceiling})"
                )


def _ols_fit_recent_mids(
    history: list[float],
    current_mid: float | None,
    *,
    window: int,
) -> tuple[float, float, int] | None:
    """Return (slope, r2, sample_count) for recent mids, or None."""
    if window <= 0:
        return None
    ys = list(history[-window:])
    if current_mid is not None:
        ys.append(float(current_mid))
    n = len(ys)
    if n < 3:
        return None

    xs = list(range(n))
    mean_x = (n - 1) / 2.0
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        return None

    cov_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = cov_xy / var_x
    intercept = mean_y - slope * mean_x
    fit = [slope * x + intercept for x in xs]
    ss_res = sum((y - yhat) ** 2 for y, yhat in zip(ys, fit, strict=True))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    if ss_tot <= 0:
        r2 = 1.0
    else:
        r2 = max(0.0, 1.0 - (ss_res / ss_tot))
    return float(slope), float(r2), n


def _micro_target_bias(
    residual: float,
    imbalance: float | None,
    *,
    residual_threshold: float,
    imbalance_threshold: float,
    add_size: int,
    trim_size: int,
) -> int:
    """Small additive target nudge when residual and imbalance agree."""
    if imbalance is None:
        return 0
    if residual <= -residual_threshold and imbalance >= imbalance_threshold:
        return add_size
    if residual >= residual_threshold and imbalance <= -imbalance_threshold:
        return -trim_size
    return 0


def _adaptive_long_cap(
    *,
    enabled: bool,
    static_ceiling: int,
    slope: float | None,
    r2: float | None,
    r2_min: float,
    mid_slope: float,
    high_slope: float,
    low_cap: int,
    mid_cap: int,
    high_cap: int,
) -> tuple[int, str]:
    """Return (effective_long_cap, regime_band)."""
    if not enabled:
        return static_ceiling, "disabled"
    if slope is None or r2 is None:
        return static_ceiling, "unavailable"
    if r2 < r2_min:
        return static_ceiling, "low_confidence"
    if slope >= high_slope:
        return min(static_ceiling, high_cap), "high"
    if slope >= mid_slope:
        return min(static_ceiling, mid_cap), "mid"
    return min(static_ceiling, low_cap), "low"


def compute_target_position(
    residual: float,
    *,
    base_long: int,
    add_thresh: float,
    trim_thresh: float,
    add_gain: float,
    trim_gain: float,
    floor: int,
    ceiling: int,
) -> int:
    """Return the signed integer target position for a given residual.

    ``residual = price - drift_fair``. Negative residual (price below
    fair) → target ABOVE base_long. Positive residual → target BELOW
    base_long, clipped at ``floor``.
    """
    if residual < -add_thresh:
        excess = -residual - add_thresh  # > 0
        overlay = add_gain * excess
    elif residual > trim_thresh:
        excess = residual - trim_thresh  # > 0
        overlay = -trim_gain * excess
    else:
        overlay = 0.0

    target = base_long + overlay
    if target < floor:
        target = floor
    elif target > ceiling:
        target = ceiling
    return int(round(target))


def _maker_prices(
    fair_value: float,
    config: ProductConfig,
    snapshot_best_bid_price: int | None,
    snapshot_best_ask_price: int | None,
    maker_edge_offset: float,
) -> tuple[int, int]:
    """Resolve (bid, ask) maker prices: fair ± maker_edge, pulled inside the book."""
    maker_edge = max(0.0, config.maker_edge + maker_edge_offset)
    raw_bid = math.floor(fair_value - maker_edge)
    raw_ask = math.ceil(fair_value + maker_edge)
    if snapshot_best_ask_price is not None:
        raw_bid = min(raw_bid, snapshot_best_ask_price - config.tick_size)
    if snapshot_best_bid_price is not None:
        raw_ask = max(raw_ask, snapshot_best_bid_price + config.tick_size)
    return raw_bid, raw_ask


class PepperCoreLongStrategy(BaseStrategy):
    """Core-long + asymmetric residual-overlay strategy for PEPPER."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: CoreLongParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        params = self.params

        fair_value: FairValueEstimate = self.fair_value_engine.estimate(
            product, snapshot, context.memory, config
        )
        fair_price = float(fair_value.price)

        # Effective ceiling never exceeds the hard position limit.
        static_ceiling = min(params.ceiling, config.position_limit)

        price: float
        if snapshot.mid is not None:
            price = float(snapshot.mid)
        else:
            price = fair_price
        residual = price - fair_price
        imbalance = snapshot.book_imbalance

        drift_fit = _ols_fit_recent_mids(
            context.memory.recent_mids,
            snapshot.mid,
            window=params.guard_window,
        )
        guard_active = False
        guard_slope: float | None = None
        guard_r2: float | None = None
        guard_samples = 0
        if drift_fit is not None:
            guard_slope, guard_r2, guard_samples = drift_fit
            guard_active = (
                params.guard_window > 0
                and guard_slope <= -params.guard_negative_slope
                and guard_r2 >= params.guard_r2_min
            )
        adaptive_ceiling, adaptive_band = _adaptive_long_cap(
            enabled=params.adaptive_caps_enabled,
            static_ceiling=static_ceiling,
            slope=guard_slope,
            r2=guard_r2,
            r2_min=params.adaptive_r2_min,
            mid_slope=params.adaptive_mid_slope,
            high_slope=params.adaptive_high_slope,
            low_cap=params.adaptive_low_cap,
            mid_cap=params.adaptive_mid_cap,
            high_cap=params.adaptive_high_cap,
        )
        effective_ceiling = adaptive_ceiling

        # ---- Opening acquisition phase (v2) ----
        # snapshot.timestamp resets at the start of every simulated
        # day, so this branch fires once per day. On the local
        # multi-day replay the opening fires on each day; on the
        # official single-day environment it fires once.
        in_opening = (
            params.open_seed_size > 0 and snapshot.timestamp <= params.open_window
        )
        if in_opening:
            raw_target = min(params.open_seed_size, effective_ceiling)
        else:
            raw_target = compute_target_position(
                residual,
                base_long=params.base_long,
                add_thresh=params.add_thresh,
                trim_thresh=params.trim_thresh,
                add_gain=params.add_gain,
                trim_gain=params.trim_gain,
                floor=params.floor,
                ceiling=effective_ceiling,
            )
            micro_bias = _micro_target_bias(
                residual,
                imbalance,
                residual_threshold=params.micro_residual_threshold,
                imbalance_threshold=params.micro_imbalance_threshold,
                add_size=params.micro_add_size,
                trim_size=params.micro_trim_size,
            )
            raw_target += micro_bias
            raw_target = max(params.floor, min(effective_ceiling, raw_target))
        if in_opening:
            micro_bias = 0

        if guard_active:
            raw_target = min(raw_target, params.guard_target)

        # Step-rate-limit the adjustment toward the target.
        raw_gap = raw_target - snapshot.position
        step_clipped_gap = max(-params.step, min(params.step, raw_gap))
        effective_target = snapshot.position + step_clipped_gap
        # Never cross the hard floor/ceiling after the step.
        effective_target = max(params.floor, min(effective_ceiling, effective_target))
        effective_gap = effective_target - snapshot.position

        # ---- Execution eligibility ----
        # Opening phase forces taker to acquire quickly regardless of
        # exec_style / residual magnitude. This is the entire point of
        # the opening seed — acquire at tick 0 without waiting for the
        # drift estimator to warm up.
        taker_eligible = (
            in_opening
            or params.exec_style == "taker"
            or (
                params.exec_style == "hybrid"
                and abs(residual) >= params.hybrid_threshold
            )
        )
        maker_eligible = params.exec_style in ("maker", "hybrid")

        # ---- Taker thresholds ----
        # For a drift asset we cross at `drift_fair ± taker_edge` so the
        # crossing price is anchored to the drift line, not the raw mid.
        # EXCEPTION: during the opening phase we cross aggressively
        # (any ask inside the book) so the seed fills immediately —
        # this is the entire point of the opening knob. Without this
        # exception the default threshold sits ~config.taker_edge
        # below fair while the best ask typically sits ~half-spread
        # above fair, so zero opening fills occur.
        buy_below: float | None = None
        sell_above: float | None = None
        if taker_eligible:
            if effective_gap > 0:
                if in_opening:
                    if (
                        params.open_take_mode == "level1_only"
                        and snapshot.best_ask is not None
                    ):
                        buy_below = float(snapshot.best_ask.price)
                    else:
                        buy_below = _OPENING_TAKE_ANY_ASK
                else:
                    buy_below = fair_price - config.taker_edge
            elif effective_gap < 0:
                # Sells during opening are gated separately below by
                # ``open_no_short``; if overlaid trim still qualifies
                # here (i.e. open_no_short=False), use the normal
                # drift-anchored crossing threshold.
                sell_above = fair_price + config.taker_edge

        # ---- Maker quotes ----
        bid_price: int | None = None
        ask_price: int | None = None
        bid_size = 0
        ask_size = 0

        if maker_eligible:
            raw_bid, raw_ask = _maker_prices(
                fair_value=fair_price,
                config=config,
                snapshot_best_bid_price=(
                    snapshot.best_bid.price if snapshot.best_bid else None
                ),
                snapshot_best_ask_price=(
                    snapshot.best_ask.price if snapshot.best_ask else None
                ),
                maker_edge_offset=params.maker_edge_offset,
            )
            if effective_gap > 0:
                bid_price = raw_bid
                bid_size = min(max(1, effective_gap), config.quote_size or params.step)
            elif effective_gap < 0:
                ask_price = raw_ask
                ask_size = min(max(1, -effective_gap), config.quote_size or params.step)
            else:
                # At target: harvest residual oscillation with small
                # symmetric maker quotes, but only up to remaining
                # capacity on each side.
                buy_capacity = effective_ceiling - snapshot.position
                sell_capacity = snapshot.position - params.floor
                small_size = max(1, (config.quote_size or params.step) // 2)
                if buy_capacity > 0:
                    bid_price = raw_bid
                    bid_size = min(small_size, buy_capacity)
                if sell_capacity > 0:
                    ask_price = raw_ask
                    ask_size = min(small_size, sell_capacity)

        # ---- Hard floor/ceiling gate on the emitted sides ----
        # Never emit buys when at or above the ceiling.
        if snapshot.position >= effective_ceiling:
            buy_below = None
            bid_size = 0
            bid_price = None
        # Never emit sells when at or below the floor.
        if snapshot.position <= params.floor:
            sell_above = None
            ask_size = 0
            ask_price = None

        # ---- Opening-phase sell suppression (v2) ----
        # If ``open_no_short`` is True during the opening window, the
        # strategy must not emit any sell-side intent even if the
        # residual overlay thinks we should trim. This protects the
        # seed from being drained by a transient positive residual
        # while the drift estimator is still warming up.
        if in_opening and params.open_no_short:
            sell_above = None
            ask_size = 0
            ask_price = None

        mode: ExecutionMode = "hybrid"
        rationale = "pepper_core_long"

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "base_long": params.base_long,
            "residual": round(residual, 4),
            "fair_value": round(fair_price, 4),
            "target_position": raw_target,
            "effective_target": effective_target,
            "position_gap": effective_gap,
            "taker_eligible": taker_eligible,
            "exec_style": params.exec_style,
            "floor": params.floor,
            "ceiling": effective_ceiling,
            "static_ceiling": static_ceiling,
            "in_opening": in_opening,
            "open_seed_size": params.open_seed_size,
            "open_window": params.open_window,
            "open_take_mode": params.open_take_mode,
            "imbalance": round(imbalance, 4) if imbalance is not None else "none",
            "micro_bias": micro_bias,
            "guard_active": guard_active,
            "guard_target": params.guard_target,
            "guard_window": params.guard_window,
            "guard_slope": round(guard_slope, 6) if guard_slope is not None else "none",
            "guard_r2": round(guard_r2, 4) if guard_r2 is not None else "none",
            "guard_samples": guard_samples,
            "adaptive_caps_enabled": params.adaptive_caps_enabled,
            "adaptive_band": adaptive_band,
            "adaptive_ceiling": adaptive_ceiling,
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

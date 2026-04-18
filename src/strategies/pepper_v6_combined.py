"""PEPPER v6 combined strategy (research-only).

Merges four proven mechanisms into one strategy:

1. **Passive-first opening** (from ``pepper_passive_opener``): post
   passive bid at ``best_bid + 1`` for the first N ticks, then fall
   back to taker if seed not met. Saves ~200-400 PnL vs pure taker
   opening by avoiding the bid-ask spread cost.

2. **Core-long overlay** (from ``pepper_core_long`` v5_micro): target
   position = ``base_long + overlay(residual)`` with asymmetric
   add/trim bands. Step-rate-limited adjustment.

3. **Inside-spread maker cycling** (from ``pepper_passive_maker``):
   after opening, post asymmetric maker quotes inside the spread.
   Drift-biased edges (tight bid, wide ask) favour long accumulation.

4. **Drift asymmetry** (from ``pepper_drift_asymmetric``): Fodra-
   Labadie slope-scaled edge scaling. Positive slope tightens bid,
   widens ask. Negative slope (reversal) flips direction.

Phase lifecycle:
    passive_opening  →  taker_fallback  →  steady_state
    (tick < N, pos      (tick >= N, pos     (pos >= seed)
     < seed)             < seed)

NOT part of the live submission bundle. Registered at bundle tail
by the export script.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    FairValueEstimate,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext

_TAKE_ANY_ASK: float = 1e9


# --- Inlined from pepper_core_long.py (bundler can't resolve cross-module) ---


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
    """Return the signed integer target position for a given residual."""
    if residual < -add_thresh:
        excess = -residual - add_thresh
        overlay = add_gain * excess
    elif residual > trim_thresh:
        excess = residual - trim_thresh
        overlay = -trim_gain * excess
    else:
        overlay = 0.0

    target = base_long + overlay
    if target < floor:
        target = floor
    elif target > ceiling:
        target = ceiling
    return int(round(target))


@dataclass(frozen=True)
class V6CombinedParams:
    """All tunable knobs for the PEPPER v6 combined strategy.

    Defaults are the v6b full-combo config (base_long=65, maker
    cycling on, drift asymmetry on). Set ``maker_quote_size=0`` and
    ``base_long=80`` for the v6a conservative variant.
    """

    # ---- Position targeting (from core-long) ----
    base_long: int = 65
    floor: int = 0
    ceiling: int = 80
    step: int = 8

    # ---- Opening phase (from passive_opener) ----
    opening_passive_window: int = 3
    opening_seed_size: int = 50
    opening_taker_fallback_tick: int = 3
    opening_no_short: bool = True
    opening_max_size_per_tick: int = 20
    passive_bid_improve: int = 1

    # ---- Core-long overlay (from v5_micro) ----
    add_thresh: float = 3.0
    trim_thresh: float = 8.0
    add_gain: float = 5.0
    trim_gain: float = 2.0

    # ---- OLS guard (from v5_micro) ----
    guard_window: int = 32
    guard_negative_slope: float = 0.01
    guard_r2_min: float = 0.0
    guard_target: int = 0

    # ---- Micro overlay (from v5_micro) ----
    micro_residual_threshold: float = 3.0
    micro_imbalance_threshold: float = 0.30
    micro_add_size: int = 2
    micro_trim_size: int = 2

    # ---- Maker cycling (from passive_maker) ----
    maker_base_bid_edge: float = 3.0
    maker_base_ask_edge: float = 5.0
    maker_quote_size: int = 5
    maker_inventory_skew_coef: float = 0.04
    min_spread_for_maker: int = 4

    # ---- Drift asymmetry (from drift_asymmetric) ----
    drift_slope_skew_factor: float = 10.0
    drift_max_asymmetry: float = 3.0
    drift_slope_r2_min: float = 0.30

    # ---- Reversal guard (from drift_asymmetric) ----
    drift_reversal_slope_threshold: float = 0.02
    drift_reversal_r2_min: float = 0.30
    drift_reversal_target: int = 0

    # ---- Execution ----
    exec_style: str = "hybrid"
    hybrid_threshold: float = 2.0

    def __post_init__(self) -> None:
        if self.base_long < 0:
            raise ValueError(f"base_long must be >= 0 (got {self.base_long})")
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if not self.floor <= self.base_long <= self.ceiling:
            raise ValueError(
                f"base_long must be in [floor={self.floor}, "
                f"ceiling={self.ceiling}] (got {self.base_long})"
            )
        if self.step <= 0:
            raise ValueError(f"step must be > 0 (got {self.step})")
        if self.opening_passive_window < 0:
            raise ValueError(
                "opening_passive_window must be >= 0 "
                f"(got {self.opening_passive_window})"
            )
        if self.opening_seed_size < 0:
            raise ValueError(
                f"opening_seed_size must be >= 0 (got {self.opening_seed_size})"
            )
        if self.opening_seed_size > self.ceiling:
            raise ValueError(
                f"opening_seed_size ({self.opening_seed_size}) must be <= "
                f"ceiling ({self.ceiling})"
            )
        if self.opening_taker_fallback_tick < 0:
            raise ValueError(
                "opening_taker_fallback_tick must be >= 0 "
                f"(got {self.opening_taker_fallback_tick})"
            )
        if self.opening_max_size_per_tick < 0:
            raise ValueError(
                "opening_max_size_per_tick must be >= 0 "
                f"(got {self.opening_max_size_per_tick})"
            )
        if self.passive_bid_improve < 0:
            raise ValueError(
                f"passive_bid_improve must be >= 0 "
                f"(got {self.passive_bid_improve})"
            )
        if self.add_thresh < 0:
            raise ValueError(f"add_thresh must be >= 0 (got {self.add_thresh})")
        if self.trim_thresh < 0:
            raise ValueError(f"trim_thresh must be >= 0 (got {self.trim_thresh})")
        if self.add_gain < 0:
            raise ValueError(f"add_gain must be >= 0 (got {self.add_gain})")
        if self.trim_gain < 0:
            raise ValueError(f"trim_gain must be >= 0 (got {self.trim_gain})")
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
        if self.maker_base_bid_edge < 0 or self.maker_base_ask_edge < 0:
            raise ValueError("maker_base_*_edge must be >= 0")
        if self.maker_quote_size < 0:
            raise ValueError(
                f"maker_quote_size must be >= 0 (got {self.maker_quote_size})"
            )
        if self.maker_inventory_skew_coef < 0:
            raise ValueError(
                "maker_inventory_skew_coef must be >= 0 "
                f"(got {self.maker_inventory_skew_coef})"
            )
        if self.min_spread_for_maker < 0:
            raise ValueError(
                f"min_spread_for_maker must be >= 0 "
                f"(got {self.min_spread_for_maker})"
            )
        if self.drift_slope_skew_factor < 0:
            raise ValueError(
                "drift_slope_skew_factor must be >= 0 "
                f"(got {self.drift_slope_skew_factor})"
            )
        if self.drift_max_asymmetry < 0:
            raise ValueError(
                f"drift_max_asymmetry must be >= 0 "
                f"(got {self.drift_max_asymmetry})"
            )
        if not 0.0 <= self.drift_slope_r2_min <= 1.0:
            raise ValueError(
                "drift_slope_r2_min must be in [0, 1] "
                f"(got {self.drift_slope_r2_min})"
            )
        if self.drift_reversal_slope_threshold < 0:
            raise ValueError(
                "drift_reversal_slope_threshold must be >= 0 "
                f"(got {self.drift_reversal_slope_threshold})"
            )
        if not 0.0 <= self.drift_reversal_r2_min <= 1.0:
            raise ValueError(
                "drift_reversal_r2_min must be in [0, 1] "
                f"(got {self.drift_reversal_r2_min})"
            )
        if not self.floor <= self.drift_reversal_target <= self.ceiling:
            raise ValueError(
                "drift_reversal_target must be in [floor, ceiling] "
                f"(got {self.drift_reversal_target})"
            )
        if self.exec_style not in ("maker", "taker", "hybrid"):
            raise ValueError(
                f"exec_style must be one of ('maker', 'taker', 'hybrid') "
                f"(got {self.exec_style!r})"
            )
        if self.hybrid_threshold < 0:
            raise ValueError(
                f"hybrid_threshold must be >= 0 (got {self.hybrid_threshold})"
            )


class PepperV6CombinedStrategy(BaseStrategy):
    """Passive opening + core-long + maker cycling + drift asymmetry."""

    _TICK_KEY = "v6_tick_count"

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: V6CombinedParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        memory = context.memory
        config = context.config
        params = self.params

        fair_value: FairValueEstimate = self.fair_value_engine.estimate(
            product, snapshot, memory, config
        )
        fair_price = float(fair_value.price)
        effective_ceiling = min(params.ceiling, config.position_limit)

        # --- Tick counter (simulator-agnostic phase tracking) ---
        tick_count = memory.counters.get(self._TICK_KEY, 0)
        memory.counters[self._TICK_KEY] = tick_count + 1

        # --- Phase detection ---
        below_seed = (
            snapshot.position < params.opening_seed_size
            and params.opening_seed_size > 0
        )
        in_passive_open = (
            tick_count < params.opening_passive_window and below_seed
        )
        in_taker_fallback = (
            tick_count >= params.opening_taker_fallback_tick and below_seed
        )

        # --- Market data ---
        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        spread = snapshot.spread
        mid = float(snapshot.mid) if snapshot.mid is not None else fair_price
        residual = mid - fair_price
        imbalance = snapshot.book_imbalance

        # --- OLS slope fit (shared by guard + drift asymmetry) ---
        drift_fit = _ols_fit_recent_mids(
            memory.recent_mids, snapshot.mid, window=params.guard_window
        )
        slope: float = 0.0
        fit_r2: float = 0.0
        fit_samples: int = 0
        if drift_fit is not None:
            slope, fit_r2, fit_samples = drift_fit

        guard_active = (
            params.guard_window > 0
            and slope <= -params.guard_negative_slope
            and fit_r2 >= params.guard_r2_min
        )
        reversal_active = (
            slope <= -params.drift_reversal_slope_threshold
            and fit_r2 >= params.drift_reversal_r2_min
        )

        # --- Drift asymmetry magnitude ---
        asymmetry: float = 0.0
        if fit_r2 >= params.drift_slope_r2_min:
            asymmetry = min(
                params.drift_max_asymmetry,
                params.drift_slope_skew_factor * abs(slope),
            )

        # --- Intent outputs ---
        bid_price: int | None = None
        ask_price: int | None = None
        bid_size: int = 0
        ask_size: int = 0
        taker_buy: float | None = None
        taker_sell: float | None = None
        raw_target: int = params.opening_seed_size
        effective_target: int = snapshot.position
        micro_bias: int = 0

        # ============================================================
        # PHASE 1: PASSIVE OPENING
        # ============================================================
        if in_passive_open and best_bid is not None:
            passive_px = best_bid.price + params.passive_bid_improve
            if best_ask is not None:
                passive_px = min(passive_px, best_ask.price - config.tick_size)
            buy_capacity = min(
                effective_ceiling - snapshot.position,
                params.opening_seed_size - snapshot.position,
                params.opening_max_size_per_tick,
            )
            if buy_capacity > 0:
                bid_price = int(passive_px)
                bid_size = int(buy_capacity)

        # ============================================================
        # PHASE 2: TAKER FALLBACK
        # ============================================================
        if in_taker_fallback:
            taker_buy = _TAKE_ANY_ASK

        # ============================================================
        # PHASE 3: STEADY-STATE
        # ============================================================
        past_opening = not below_seed or tick_count >= max(
            params.opening_passive_window,
            params.opening_taker_fallback_tick + 2,
        )

        if past_opening:
            # --- Core-long target with overlay ---
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

            # --- Guard caps ---
            if guard_active:
                raw_target = min(raw_target, params.guard_target)
            if reversal_active:
                raw_target = min(raw_target, params.drift_reversal_target)

            # --- Step-rate limiting ---
            raw_gap = raw_target - snapshot.position
            step_clipped = max(-params.step, min(params.step, raw_gap))
            effective_target = snapshot.position + step_clipped
            effective_target = max(params.floor, min(effective_ceiling, effective_target))
            effective_gap = effective_target - snapshot.position

            # --- Maker cycling (inside-spread quotes) ---
            maker_enabled = (
                params.maker_quote_size > 0
                and (spread is None or spread >= params.min_spread_for_maker)
            )
            if maker_enabled and bid_price is None:
                # Compute asymmetric edges
                inventory_dev = snapshot.position - params.base_long
                inv_skew = params.maker_inventory_skew_coef * inventory_dev

                bid_edge = params.maker_base_bid_edge
                ask_edge = params.maker_base_ask_edge

                # Drift asymmetry: positive slope → tighten bid, widen ask
                if reversal_active:
                    bid_edge += asymmetry
                    ask_edge -= asymmetry
                else:
                    bid_edge -= asymmetry
                    ask_edge += asymmetry

                # Inventory skew on top
                bid_edge = max(0.0, bid_edge + inv_skew)
                ask_edge = max(0.0, ask_edge - inv_skew)

                raw_bid_px = math.floor(fair_price - bid_edge)
                raw_ask_px = math.ceil(fair_price + ask_edge)

                # Pull inside the touch
                if best_ask is not None:
                    raw_bid_px = min(raw_bid_px, best_ask.price - config.tick_size)
                if best_bid is not None:
                    raw_ask_px = max(raw_ask_px, best_bid.price + config.tick_size)
                # Improve touch
                if best_bid is not None:
                    raw_bid_px = max(raw_bid_px, best_bid.price + config.tick_size)
                if best_ask is not None:
                    raw_ask_px = min(raw_ask_px, best_ask.price - config.tick_size)
                # Guard crossing
                if raw_ask_px <= raw_bid_px:
                    raw_bid_px = raw_ask_px - config.tick_size

                qs = params.maker_quote_size
                buy_capacity = effective_ceiling - snapshot.position
                sell_capacity = snapshot.position - params.floor

                if effective_gap > 0:
                    if buy_capacity > 0:
                        bid_price = raw_bid_px
                        bid_size = min(qs, buy_capacity)
                elif effective_gap < 0:
                    if sell_capacity > 0:
                        ask_price = raw_ask_px
                        ask_size = min(qs, sell_capacity)
                else:
                    # At target: cycle both sides
                    half_qs = max(1, qs // 2)
                    if buy_capacity > 0:
                        bid_price = raw_bid_px
                        bid_size = min(half_qs, buy_capacity)
                    if sell_capacity > 0:
                        ask_price = raw_ask_px
                        ask_size = min(half_qs, sell_capacity)

            # --- Taker crosses (hybrid mode) ---
            taker_eligible = (
                params.exec_style == "taker"
                or (
                    params.exec_style == "hybrid"
                    and abs(residual) >= params.hybrid_threshold
                )
            )
            if taker_eligible and not below_seed:
                if effective_gap > 0:
                    taker_buy = fair_price - config.taker_edge
                elif effective_gap < 0:
                    taker_sell = fair_price + config.taker_edge

        # ============================================================
        # HARD GATES
        # ============================================================
        if snapshot.position >= effective_ceiling:
            bid_price = None
            bid_size = 0
            taker_buy = None
        if snapshot.position <= params.floor:
            ask_price = None
            ask_size = 0
            taker_sell = None
        # Never sell during opening
        if below_seed and params.opening_no_short:
            ask_price = None
            ask_size = 0
            taker_sell = None

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "fair_value": round(fair_price, 4),
            "residual": round(residual, 4),
            "imbalance": round(imbalance, 4) if imbalance is not None else "none",
            "slope": round(slope, 6),
            "fit_r2": round(fit_r2, 4),
            "fit_samples": fit_samples,
            "asymmetry": round(asymmetry, 4),
            "guard_active": guard_active,
            "reversal_active": reversal_active,
            "tick_count": tick_count,
            "below_seed": below_seed,
            "in_passive_open": in_passive_open,
            "in_taker_fallback": in_taker_fallback,
            "past_opening": past_opening,
            "position": snapshot.position,
            "base_long": params.base_long,
            "raw_target": raw_target,
            "effective_target": effective_target,
            "micro_bias": micro_bias,
            "floor": params.floor,
            "ceiling": effective_ceiling,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=taker_buy,
            sell_above=taker_sell,
            quote=quote,
            rationale="pepper_v6_combined",
            metadata=MappingProxyType(metadata),
        )

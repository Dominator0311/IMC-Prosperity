"""PEPPER Fodra-Labadie asymmetric drift-quoting (research-only).

Fodra & Labadie (2012): the optimal market-making response to a
non-martingale, directional price process is *asymmetric* quoting
that favors fills on the side aligned with the expected trend.

Translated to PEPPER's drift:

- Positive slope (observed +~0.1/tick) → price is pulled up →
  the favorable side to be filled on is the BUY side (we want to
  acquire in front of the drift). So bid aggressively (tighter),
  ask conservatively (wider).
- Magnitude of asymmetry scales with slope magnitude and slope
  confidence — NOT hardcoded.
- Safety: inventory skew retains responsibility for preventing
  unbounded accumulation.

Key differences from ``PepperPassiveMaker``:
- Asymmetry is dynamic (slope-driven), not a fixed bid/ask edge gap.
- Adds slope-confidence r² gate: when drift is weak/noisy, collapse
  to symmetric quoting.
- Supports a ``reversal_guard`` that flips the asymmetry direction if
  slope turns meaningfully negative (robustness for unseen tapes).

Parameters are all expressed in microstructure units (ticks, slope
per tick) so they transfer to unseen tapes if the drift/spread
dynamics are in the same order of magnitude.
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


def _ols_fit_recent_mids(
    history: list[float],
    current_mid: float | None,
    *,
    window: int,
) -> tuple[float, float, int] | None:
    """Return (slope, r2, sample_count) for recent mids, or None.

    Duplicated here (rather than imported from pepper_core_long) so this
    module is bundle-self-contained — the export inliner pulls one
    module per slot and would otherwise need pepper_core_long inlined
    too.
    """
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
    r2 = 1.0 if ss_tot <= 0 else max(0.0, 1.0 - (ss_res / ss_tot))
    return float(slope), float(r2), n


@dataclass(frozen=True)
class DriftAsymmetricParams:
    """Tunable knobs for PepperDriftAsymmetric.

    Defaults chosen so:

    - ``base_edge=3`` is inside the modal 13-tick spread on all 3 real
      days (not fit to day-0 specifically).
    - ``slope_skew_factor=10.0`` translates the observed +0.1/tick
      slope into +1-tick edge asymmetry. That is ~30% of the base edge
      — meaningful but not overwhelming.
    - ``max_asymmetry=3`` caps the skew at 3 ticks so the strategy
      can't degenerate into one-sided quoting on extreme slope noise.
    - ``slope_window=32`` matches the existing ``linear_drift``
      estimator's default history_length (ProductConfig.history_length).
    - ``slope_r2_min=0.30`` is a loose confidence filter — we only
      require the slope to explain 30% of the variance. Tighter filters
      (0.5+) make the strategy inert on the real tape because short-
      window fits have noisy r².
    - ``core_target=50``: middle of [0, 100] inventory range; balances
      drift-carry against maker cycling.
    """

    # --- Symmetric base ---
    base_edge: float = 3.0
    # Quote size per side (maker).
    quote_size: int = 5
    # --- Asymmetry ---
    # Slope-to-edge translation. For slope s, the favorable side (bid
    # under positive s) tightens by slope_skew_factor * |s|; the
    # unfavorable side widens by the same amount.
    slope_skew_factor: float = 10.0
    max_asymmetry: float = 3.0
    slope_window: int = 32
    slope_r2_min: float = 0.30
    # --- Inventory skew ---
    inventory_skew_coef: float = 0.05
    # --- Position targeting ---
    core_target: int = 50
    floor: int = 0
    ceiling: int = 80
    # --- Seed ---
    seed_size: int = 40
    seed_window: int = 500
    # --- Reversal guard (unseen-data robustness) ---
    # If slope <= -reversal_slope_threshold with r² >= reversal_r2_min,
    # flip asymmetry direction AND reduce target to reversal_target.
    reversal_slope_threshold: float = 0.02
    reversal_r2_min: float = 0.30
    reversal_target: int = 0
    # --- Safety ---
    min_spread_for_maker: int = 4

    def __post_init__(self) -> None:
        non_neg = {
            "base_edge": self.base_edge,
            "quote_size": self.quote_size,
            "slope_skew_factor": self.slope_skew_factor,
            "max_asymmetry": self.max_asymmetry,
            "inventory_skew_coef": self.inventory_skew_coef,
            "floor": self.floor,
            "seed_size": self.seed_size,
            "seed_window": self.seed_window,
            "reversal_slope_threshold": self.reversal_slope_threshold,
            "min_spread_for_maker": self.min_spread_for_maker,
        }
        for name, value in non_neg.items():
            if value < 0:
                raise ValueError(f"{name} must be >= 0 (got {value})")
        if self.slope_window < 3:
            raise ValueError(f"slope_window must be >= 3 (got {self.slope_window})")
        for name, value in {
            "slope_r2_min": self.slope_r2_min,
            "reversal_r2_min": self.reversal_r2_min,
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1] (got {value})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got {self.floor}, {self.ceiling})"
            )
        if not self.floor <= self.core_target <= self.ceiling:
            raise ValueError(f"core_target out of [floor, ceiling]: {self.core_target}")
        if self.seed_size > self.ceiling:
            raise ValueError(f"seed_size > ceiling: {self.seed_size}")
        if not self.floor <= self.reversal_target <= self.ceiling:
            raise ValueError(
                f"reversal_target out of [floor, ceiling]: {self.reversal_target}"
            )


class PepperDriftAsymmetricStrategy(BaseStrategy):
    """Asymmetric maker whose skew magnitude scales with drift slope."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: DriftAsymmetricParams,
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
        effective_ceiling = min(params.ceiling, config.position_limit)

        # --- Slope estimate (separate window from linear_drift config) ---
        slope_fit = _ols_fit_recent_mids(
            context.memory.recent_mids,
            snapshot.mid,
            window=params.slope_window,
        )
        slope: float = 0.0
        r2: float = 0.0
        samples: int = 0
        if slope_fit is not None:
            slope, r2, samples = slope_fit

        # --- Reversal guard ---
        reversal_active = (
            slope <= -params.reversal_slope_threshold
            and r2 >= params.reversal_r2_min
        )
        effective_target = (
            params.reversal_target if reversal_active else params.core_target
        )

        # --- Asymmetry computation ---
        asymmetry_magnitude: float = 0.0
        if r2 >= params.slope_r2_min:
            asymmetry_magnitude = min(
                params.max_asymmetry, params.slope_skew_factor * abs(slope)
            )

        # Direction of favorable side (where we want to get filled).
        # Positive slope → favor BUY side (tight bid).
        # Negative slope (reversal) → favor SELL side (tight ask).
        favor_buy = slope >= 0

        bid_edge = params.base_edge
        ask_edge = params.base_edge
        if favor_buy:
            bid_edge -= asymmetry_magnitude
            ask_edge += asymmetry_magnitude
        else:
            bid_edge += asymmetry_magnitude
            ask_edge -= asymmetry_magnitude

        # --- Inventory skew ---
        inventory_dev = snapshot.position - effective_target
        inv_skew = params.inventory_skew_coef * inventory_dev
        # Over-long → widen bid (buy harder), tighten ask (sell easier).
        bid_edge += inv_skew
        ask_edge -= inv_skew
        bid_edge = max(0.0, bid_edge)
        ask_edge = max(0.0, ask_edge)

        # --- Raw prices anchored to drift_fair ---
        raw_bid_px = math.floor(fair_price - bid_edge)
        raw_ask_px = math.ceil(fair_price + ask_edge)

        # --- Pull inside the touch (same guard as passive_maker) ---
        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        if best_ask is not None:
            raw_bid_px = min(raw_bid_px, best_ask.price - config.tick_size)
        if best_bid is not None:
            raw_ask_px = max(raw_ask_px, best_bid.price + config.tick_size)
        if best_bid is not None:
            raw_bid_px = max(raw_bid_px, best_bid.price + config.tick_size)
        if best_ask is not None:
            raw_ask_px = min(raw_ask_px, best_ask.price - config.tick_size)
        if raw_ask_px <= raw_bid_px:
            raw_bid_px = raw_ask_px - config.tick_size

        spread = snapshot.spread
        maker_enabled = spread is None or spread >= params.min_spread_for_maker

        # --- Seed ---
        in_opening = (
            params.seed_size > 0 and snapshot.timestamp <= params.seed_window
        )
        below_seed = snapshot.position < params.seed_size

        # --- Quote emission ---
        bid_price: int | None = None
        ask_price: int | None = None
        bid_size = 0
        ask_size = 0

        taker_buy_px: float | None = None
        taker_sell_px: float | None = None

        if maker_enabled:
            buy_capacity = effective_ceiling - snapshot.position
            sell_capacity = snapshot.position - params.floor
            qs = max(0, params.quote_size)

            # Reversal: actively de-risk with aggressive taker sell.
            if reversal_active and snapshot.position > effective_target:
                taker_sell_px = fair_price + params.base_edge

            if in_opening and below_seed:
                # Bias toward buy-side during seed: taker cross.
                taker_buy_px = 1e9
                if buy_capacity > 0 and qs > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
            else:
                if buy_capacity > 0 and qs > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
                if (
                    sell_capacity > 0
                    and qs > 0
                    and snapshot.position > params.floor
                ):
                    ask_price = raw_ask_px
                    ask_size = min(qs, sell_capacity)

        # --- Hard gates ---
        if snapshot.position >= effective_ceiling:
            bid_price = None
            bid_size = 0
            taker_buy_px = None
        if snapshot.position <= params.floor:
            ask_price = None
            ask_size = 0
            taker_sell_px = None
        if in_opening and below_seed and not reversal_active:
            ask_price = None
            ask_size = 0
            taker_sell_px = None

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "fair_value": round(fair_price, 4),
            "slope": round(slope, 6),
            "slope_r2": round(r2, 4),
            "slope_samples": samples,
            "asymmetry": round(asymmetry_magnitude, 4),
            "bid_edge": round(bid_edge, 3),
            "ask_edge": round(ask_edge, 3),
            "inv_skew": round(inv_skew, 3),
            "reversal_active": reversal_active,
            "effective_target": effective_target,
            "in_opening": in_opening,
            "below_seed": below_seed,
            "maker_enabled": maker_enabled,
            "position": snapshot.position,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=taker_buy_px,
            sell_above=taker_sell_px,
            quote=quote,
            rationale="pepper_drift_asymmetric",
            metadata=MappingProxyType(metadata),
        )

"""PEPPER imbalance-timer strategy (research-only).

Uses the Cont-Kukanov-Stoikov result: short-horizon mid-price moves
are driven primarily by top-of-book order-flow imbalance (OFI), with
a roughly linear relationship modulated by top-of-book depth.

In the repo's own 3-day scan, top-of-book imbalance had ~0.56
correlation with next-tick mid change on PEPPER. That is a strong
micro signal, currently unused.

Strategy:

1. Maintain a drift-aware core long position (``core_target``).
2. Gate *additions* on imbalance >= threshold (bid-heavy → buy now,
   before the move up).
3. Gate *trims* on imbalance <= -threshold (ask-heavy → sell now,
   before the move down).
4. Quote defensively when imbalance is ambiguous — small maker bid/ask
   at wide edges, minimal exposure.

Crucial: the imbalance signal is used for TIMING, not as standalone
alpha. The drift remains the primary. A buy gated by imbalance still
requires mid <= drift_fair + small_edge (we don't chase).

Distinct from ``PepperCoreLongStrategy`` overlay which gates on
residual only. Residual events are rare (|>=8|: 3 per day); imbalance
events are frequent (most ticks have |imb| > 0.3).
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


@dataclass(frozen=True)
class ImbalanceTimerParams:
    """Tunable knobs for PepperImbalanceTimer.

    Defaults chosen from first-principles observations:

    - ``add_imbalance_threshold=0.30``: above this, top-of-book is
      ~2:1 bid-heavy. Meaningful signal, not noise. The repo's own
      scan showed 0.56 correlation — a 0.3 threshold captures most
      signal while excluding ticks where imbalance is ambiguous.
    - ``trim_imbalance_threshold=0.30``: symmetric trigger the other way.
    - ``add_size=4`` / ``trim_size=4``: ~5% of position limit. Small
      enough that many triggers don't flip us; big enough that
      cumulative impact over a day (50-100 events) is meaningful.
    - ``max_mid_above_fair=2.0`` / ``min_mid_below_fair=-2.0``: price
      filter. Imbalance is a timing signal, not a free-money signal —
      only buy if price is reasonable, only sell if price is rich.
    - ``core_target=60``: mid-range between full-carry (80) and
      balanced (40). Leaves 20 units of cycling headroom.
    """

    # --- Imbalance triggers ---
    add_imbalance_threshold: float = 0.30
    trim_imbalance_threshold: float = 0.30
    add_size: int = 4
    trim_size: int = 4
    # --- Price filters (unit: ticks from drift_fair) ---
    # Only add if mid <= drift_fair + max_add_mid_above_fair.
    max_add_mid_above_fair: float = 2.0
    # Only trim if mid >= drift_fair + min_trim_mid_above_fair.
    min_trim_mid_above_fair: float = 2.0
    # --- Position targeting ---
    core_target: int = 60
    floor: int = 0
    ceiling: int = 80
    # --- Background maker quoting ---
    background_bid_edge: float = 3.0
    background_ask_edge: float = 5.0
    background_quote_size: int = 3
    # --- Seed ---
    seed_size: int = 50
    seed_window: int = 500
    # --- Safety ---
    # Minimum top-of-book depth (summed) to trust the imbalance signal.
    # Below this, skip the trigger (too thin to be meaningful).
    min_top_depth: int = 8

    def __post_init__(self) -> None:
        if not 0.0 <= self.add_imbalance_threshold <= 1.0:
            raise ValueError(
                "add_imbalance_threshold must be in [0, 1] "
                f"(got {self.add_imbalance_threshold})"
            )
        if not 0.0 <= self.trim_imbalance_threshold <= 1.0:
            raise ValueError(
                "trim_imbalance_threshold must be in [0, 1] "
                f"(got {self.trim_imbalance_threshold})"
            )
        if self.add_size < 0:
            raise ValueError(f"add_size must be >= 0 (got {self.add_size})")
        if self.trim_size < 0:
            raise ValueError(f"trim_size must be >= 0 (got {self.trim_size})")
        if self.core_target < 0:
            raise ValueError(f"core_target must be >= 0 (got {self.core_target})")
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if not self.floor <= self.core_target <= self.ceiling:
            raise ValueError(
                "core_target must lie in [floor, ceiling] "
                f"(got {self.core_target})"
            )
        if self.background_bid_edge < 0 or self.background_ask_edge < 0:
            raise ValueError("background_*_edge must be >= 0")
        if self.background_quote_size < 0:
            raise ValueError(
                f"background_quote_size must be >= 0 "
                f"(got {self.background_quote_size})"
            )
        if self.seed_size < 0 or self.seed_size > self.ceiling:
            raise ValueError(
                f"seed_size must be in [0, ceiling] (got {self.seed_size})"
            )
        if self.seed_window < 0:
            raise ValueError(f"seed_window must be >= 0 (got {self.seed_window})")
        if self.min_top_depth < 0:
            raise ValueError(
                f"min_top_depth must be >= 0 (got {self.min_top_depth})"
            )


class PepperImbalanceTimerStrategy(BaseStrategy):
    """Drift-aware core with imbalance-gated tactical adds/trims."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: ImbalanceTimerParams,
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

        mid = snapshot.mid if snapshot.mid is not None else fair_price
        imbalance = snapshot.book_imbalance
        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        top_depth = 0
        if best_bid is not None:
            top_depth += best_bid.volume
        if best_ask is not None:
            top_depth += best_ask.volume

        residual = mid - fair_price

        # --- Seed ---
        in_opening = (
            params.seed_size > 0 and snapshot.timestamp <= params.seed_window
        )
        below_seed = snapshot.position < params.seed_size

        # --- Imbalance gating ---
        signal_trusted = top_depth >= params.min_top_depth and imbalance is not None
        add_triggered = (
            signal_trusted
            and imbalance is not None
            and imbalance >= params.add_imbalance_threshold
            and residual <= params.max_add_mid_above_fair
            and snapshot.position < effective_ceiling
        )
        trim_triggered = (
            signal_trusted
            and imbalance is not None
            and imbalance <= -params.trim_imbalance_threshold
            and residual >= params.min_trim_mid_above_fair
            and snapshot.position > max(params.floor, params.core_target // 2)
        )

        # --- Taker thresholds ---
        taker_buy_px: float | None = None
        taker_sell_px: float | None = None

        if in_opening and below_seed:
            # Seed aggressively.
            taker_buy_px = 1e9
        elif add_triggered and best_ask is not None:
            # Take the ask (best_ask) up to add_size via max_aggressive_size.
            taker_buy_px = float(best_ask.price)
        elif trim_triggered and best_bid is not None:
            taker_sell_px = float(best_bid.price)

        # --- Background maker quotes ---
        # These run continuously, harvesting spread outside of imbalance
        # events.
        raw_bid_px = math.floor(fair_price - params.background_bid_edge)
        raw_ask_px = math.ceil(fair_price + params.background_ask_edge)
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

        bid_size = 0
        ask_size = 0
        bid_price: int | None = None
        ask_price: int | None = None

        qs = max(0, params.background_quote_size)
        buy_capacity = effective_ceiling - snapshot.position
        sell_capacity = snapshot.position - params.floor

        if qs > 0:
            if buy_capacity > 0:
                bid_price = raw_bid_px
                bid_size = min(qs, buy_capacity)
            if sell_capacity > 0 and snapshot.position > params.floor:
                ask_price = raw_ask_px
                ask_size = min(qs, sell_capacity)

        # Active-add tick: bump maker bid size to capture more if
        # additional passive fill also arrives in the same tick.
        if add_triggered:
            ask_price = None
            ask_size = 0
            if buy_capacity > 0:
                bid_size = min(buy_capacity, max(bid_size, params.add_size))
        if trim_triggered:
            bid_price = None
            bid_size = 0
            if sell_capacity > 0:
                ask_size = min(sell_capacity, max(ask_size, params.trim_size))

        # --- Hard gates ---
        if snapshot.position >= effective_ceiling:
            bid_price = None
            bid_size = 0
            taker_buy_px = None
        if snapshot.position <= params.floor:
            ask_price = None
            ask_size = 0
            taker_sell_px = None
        if in_opening and below_seed:
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
            "mid": round(mid, 4),
            "residual": round(residual, 4),
            "imbalance": round(imbalance, 4) if imbalance is not None else "none",
            "top_depth": top_depth,
            "signal_trusted": signal_trusted,
            "add_triggered": add_triggered,
            "trim_triggered": trim_triggered,
            "in_opening": in_opening,
            "below_seed": below_seed,
            "position": snapshot.position,
            "core_target": params.core_target,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=taker_buy_px,
            sell_above=taker_sell_px,
            quote=quote,
            rationale="pepper_imbalance_timer",
            metadata=MappingProxyType(metadata),
        )

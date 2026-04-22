"""PEPPER flow-overlay strategy (research-only).

Reads ``snapshot.trades`` (market trades since last snapshot) to infer
aggressor flow. When market bots are buying more than selling, there
is upward pressure; when the flow reverses, price is more likely to
retrace. This signal is orthogonal to ``linear_drift`` (slow) and
``book_imbalance`` (instantaneous).

Approach:

1. Estimate aggressor side for each trade by comparing price to
   prior mid:
     trade_price > prior_mid  → buyer-aggressor (+qty)
     trade_price < prior_mid  → seller-aggressor (-qty)
     trade_price == prior_mid → ambiguous, skip
   (Same convention as ``src.core.utils._tick_net_flow``.)
2. Maintain an EWMA of net flow in ``ProductMemory.values``, decaying
   by ``flow_decay`` per tick.
3. Convert flow EWMA to a target-position bias in [-flow_bias_size,
   +flow_bias_size].
4. Combine with the drift-carry core: ``target = core_long + bias``,
   clipped to [floor, ceiling].
5. Rate-limit adjustment (``step``) and execute via a drift-anchored
   taker + defensive maker overlay.

This is the first PEPPER strategy that reads the trade tape as a
decision input — none of V2-V4 or any Phase-J config reads
``snapshot.trades``.
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
class FlowOverlayParams:
    """Tunable knobs for PepperFlowOverlay.

    Defaults chosen from first principles:

    - ``flow_decay=0.85``: EWMA half-life ≈ 4.3 ticks. Matches
      observed PEPPER momentum horizon without being too reactive.
    - ``flow_bias_size=20``: 25% of position limit. Meaningful but
      doesn't dominate the core-long anchor.
    - ``flow_scale=0.5``: each unit of net flow (decayed) adds 0.5
      units of target position. Conservative — requires sustained
      flow for a full bias swing.
    - ``core_long=50``: mid-range between carry-heavy (80) and
      balanced (40). Leaves meaningful cycling capacity on both sides.
    - ``step=8``: matches V3 default.
    - ``flow_scale`` × typical flow magnitude × (1 / (1 - flow_decay))
      should not exceed ``flow_bias_size`` — clamp hard to prevent
      over-reaction to a single large trade.
    """

    # --- Core ---
    core_long: int = 50
    floor: int = 0
    ceiling: int = 80
    step: int = 8
    # --- Flow estimation ---
    flow_decay: float = 0.85
    flow_scale: float = 0.5
    flow_bias_size: int = 20
    # Minimum |flow_ewma| to bother acting (noise floor).
    flow_min_magnitude: float = 2.0
    # --- Execution ---
    taker_edge: float = 1.5
    # Background maker quoting.
    maker_bid_edge: float = 3.0
    maker_ask_edge: float = 5.0
    maker_quote_size: int = 3
    # --- Seed ---
    seed_size: int = 40
    seed_window: int = 500
    # --- Safety ---
    min_spread_for_maker: int = 4

    # Memory keys for EWMA state.
    flow_ewma_key: str = "pepper_flow_ewma"
    prior_mid_key: str = "pepper_flow_prior_mid"

    def __post_init__(self) -> None:
        if self.core_long < 0:
            raise ValueError(f"core_long must be >= 0 (got {self.core_long})")
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if not self.floor <= self.core_long <= self.ceiling:
            raise ValueError(
                "core_long must lie in [floor, ceiling] "
                f"(got {self.core_long})"
            )
        if self.step <= 0:
            raise ValueError(f"step must be > 0 (got {self.step})")
        if not 0.0 <= self.flow_decay <= 1.0:
            raise ValueError(
                f"flow_decay must be in [0, 1] (got {self.flow_decay})"
            )
        if self.flow_scale < 0:
            raise ValueError(f"flow_scale must be >= 0 (got {self.flow_scale})")
        if self.flow_bias_size < 0:
            raise ValueError(
                f"flow_bias_size must be >= 0 (got {self.flow_bias_size})"
            )
        if self.flow_min_magnitude < 0:
            raise ValueError(
                f"flow_min_magnitude must be >= 0 "
                f"(got {self.flow_min_magnitude})"
            )
        if self.taker_edge < 0:
            raise ValueError(f"taker_edge must be >= 0 (got {self.taker_edge})")
        if self.maker_bid_edge < 0 or self.maker_ask_edge < 0:
            raise ValueError("maker_*_edge must be >= 0")
        if self.maker_quote_size < 0:
            raise ValueError(
                f"maker_quote_size must be >= 0 (got {self.maker_quote_size})"
            )
        if self.seed_size < 0 or self.seed_size > self.ceiling:
            raise ValueError(
                f"seed_size must be in [0, ceiling] (got {self.seed_size})"
            )
        if self.seed_window < 0:
            raise ValueError(f"seed_window must be >= 0 (got {self.seed_window})")
        if self.min_spread_for_maker < 0:
            raise ValueError(
                f"min_spread_for_maker must be >= 0 "
                f"(got {self.min_spread_for_maker})"
            )


def _estimate_net_flow(
    trades: tuple,  # tuple[TradePrint, ...]
    prior_mid: float | None,
) -> int:
    """Sum aggressor-side quantities.

    Buyer-aggressor (trade above prior mid) = +qty.
    Seller-aggressor (trade below prior mid) = -qty.
    At-mid or ambiguous = 0.
    """
    if prior_mid is None:
        return 0
    net = 0
    for trade in trades:
        price = trade.price
        qty = trade.quantity
        if price > prior_mid:
            net += qty
        elif price < prior_mid:
            net -= qty
    return net


class PepperFlowOverlayStrategy(BaseStrategy):
    """Drift-carry core with EWMA trade-flow bias on target position."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: FlowOverlayParams,
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

        # --- Flow EWMA update ---
        prior_mid = memory.values.get(params.prior_mid_key)
        this_tick_flow = _estimate_net_flow(snapshot.trades, prior_mid)
        flow_ewma = memory.values.get(params.flow_ewma_key, 0.0)
        flow_ewma = params.flow_decay * flow_ewma + float(this_tick_flow)
        memory.values[params.flow_ewma_key] = flow_ewma
        if snapshot.mid is not None:
            memory.values[params.prior_mid_key] = float(snapshot.mid)

        # --- Flow → target bias ---
        bias: int = 0
        if abs(flow_ewma) >= params.flow_min_magnitude:
            bias = int(round(params.flow_scale * flow_ewma))
            bias = max(-params.flow_bias_size, min(params.flow_bias_size, bias))

        # --- Seed ---
        in_opening = (
            params.seed_size > 0 and snapshot.timestamp <= params.seed_window
        )
        below_seed = snapshot.position < params.seed_size

        if in_opening:
            target = params.seed_size
        else:
            target = params.core_long + bias
            target = max(params.floor, min(effective_ceiling, target))

        # --- Rate-limit ---
        gap = target - snapshot.position
        clipped_gap = max(-params.step, min(params.step, gap))
        effective_target = snapshot.position + clipped_gap
        effective_gap = effective_target - snapshot.position

        # --- Execution ---
        mid = snapshot.mid if snapshot.mid is not None else fair_price
        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        spread = snapshot.spread

        taker_buy_px: float | None = None
        taker_sell_px: float | None = None

        if in_opening and below_seed:
            taker_buy_px = 1e9
        elif effective_gap > 0:
            taker_buy_px = fair_price - params.taker_edge
        elif effective_gap < 0:
            taker_sell_px = fair_price + params.taker_edge

        # --- Background maker ---
        maker_enabled = spread is None or spread >= params.min_spread_for_maker
        bid_price: int | None = None
        ask_price: int | None = None
        bid_size = 0
        ask_size = 0
        if maker_enabled:
            raw_bid_px = math.floor(fair_price - params.maker_bid_edge)
            raw_ask_px = math.ceil(fair_price + params.maker_ask_edge)
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

            qs = max(0, params.maker_quote_size)
            buy_capacity = effective_ceiling - snapshot.position
            sell_capacity = snapshot.position - params.floor
            if qs > 0:
                if buy_capacity > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
                if sell_capacity > 0 and snapshot.position > params.floor:
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
            "tick_flow": this_tick_flow,
            "flow_ewma": round(flow_ewma, 4),
            "bias": bias,
            "target": target,
            "effective_target": effective_target,
            "effective_gap": effective_gap,
            "core_long": params.core_long,
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
            rationale="pepper_flow_overlay",
            metadata=MappingProxyType(metadata),
        )

"""ASH inside-wall market-maker — faithful reproduction of F2 pattern.

Implements the convergent mechanism observed across 8 top-team P1/P2/P3
repos on stable products (AMETHYSTS, PEARLS, RAINFOREST_RESIN):

1. Fair value = wall-mid (midpoint of the largest-volume bid/ask levels).
2. Bid placement = max_amt_bid + 1 (one tick INSIDE the deep bid).
3. Ask placement = max_amt_ask - 1 (one tick INSIDE the deep ask).
4. Take crossing orders first (take).
5. Flatten excess inventory at fair (clear).
6. Place maker quotes at inside-wall prices (make).

References:
- pe049395 round5.py:782-786, 822-826
- timo FrankfurtHedgehogs_polished.py:303-304
- linear_utility round1/round_1_v6.py:285

NOT yet in STRATEGY_REGISTRY — diagnostic-only until IMC simulator
validates.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    BookLevel,
    ExecutionMode,
    NormalizedSnapshot,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class InsideWallParams:
    """F2 pattern parameters."""

    # Quote size per side.
    bid_size: int = 20
    ask_size: int = 20

    # Take-ticks: crossing orders at mid ± take_threshold get taken.
    take_threshold: float = 1.0

    # Clear threshold: when |position| / limit >= this, flatten-at-fair.
    clear_threshold: float = 0.5

    # Minimum volume to qualify as a "wall" level. Filters out penny-jumpers.
    min_wall_volume: int = 10

    # Maker quote tick-offset from wall (F2 convention: +1 / -1).
    inside_wall_offset: int = 1


class AshInsideWallStrategy(BaseStrategy):
    """Wall-mid fair value + quote-inside-wall placement + take/clear/make."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: InsideWallParams,
    ) -> None:
        # We don't actually use the fair_value_engine — we compute wall-mid
        # directly from snapshot for faithful F2 reproduction.
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    @staticmethod
    def _pick_wall(levels: tuple[BookLevel, ...], min_vol: int) -> BookLevel | None:
        """Largest-volume level at or above min_vol."""
        qualifying = [l for l in levels if l.volume >= min_vol]
        if not qualifying:
            # Fall back to best non-empty.
            return max(levels, key=lambda l: l.volume) if levels else None
        return max(qualifying, key=lambda l: l.volume)

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        params = self.params

        # Handle empty book — fall back to anchor or mid.
        if not snapshot.bids or not snapshot.asks:
            fair = self.fair_value_engine.estimate(
                product, snapshot, context.memory, config
            )
            return SignalIntent(
                product=product,
                fair_value=fair,
                mode="idle",
                rationale="ash_inside_wall_empty_book",
            )

        # F2 mechanics.
        wall_bid = self._pick_wall(snapshot.bids, params.min_wall_volume)
        wall_ask = self._pick_wall(snapshot.asks, params.min_wall_volume)

        if wall_bid is None or wall_ask is None:
            fair = self.fair_value_engine.estimate(
                product, snapshot, context.memory, config
            )
            return SignalIntent(
                product=product,
                fair_value=fair,
                mode="idle",
                rationale="ash_inside_wall_no_wall",
            )

        wall_mid = (wall_bid.price + wall_ask.price) / 2.0

        # Build a FairValueEstimate object for the return payload (required).
        from src.core.types import FairValueEstimate

        fair_estimate = FairValueEstimate(
            price=wall_mid,
            method="wall_mid_inline",
            confidence=0.8,
        )

        # Quote-inside-wall placement.
        off = params.inside_wall_offset
        bid_price = wall_bid.price + off
        ask_price = wall_ask.price - off

        # Safety clamp: never cross the spread.
        if bid_price >= ask_price:
            # Wall_bid and wall_ask too close — fall back to BBO-1 / BBO+1.
            bid_price = snapshot.best_bid.price
            ask_price = snapshot.best_ask.price

        # Take: cross the spread if opponent quote is below wall_mid - take_threshold.
        buy_below = wall_mid - params.take_threshold
        sell_above = wall_mid + params.take_threshold

        # Clear: flatten when near position limit.
        position_ratio = (
            snapshot.position / config.position_limit
            if config.position_limit
            else 0.0
        )
        flattening = abs(position_ratio) >= params.clear_threshold

        bid_size = params.bid_size
        ask_size = params.ask_size

        mode: ExecutionMode = "hybrid"
        rationale = f"inside_wall(wb={wall_bid.price},wa={wall_ask.price})"

        if flattening:
            mode = "recovery"
            rationale = "inside_wall_recovery"
            if snapshot.position > 0:
                # Reduce long inventory: suppress bid, tighten ask to fair.
                bid_size = 0
                ask_price = int(math.floor(wall_mid))
            elif snapshot.position < 0:
                ask_size = 0
                bid_price = int(math.ceil(wall_mid))

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "wall_bid_price": wall_bid.price,
            "wall_bid_vol": wall_bid.volume,
            "wall_ask_price": wall_ask.price,
            "wall_ask_vol": wall_ask.volume,
            "wall_mid": round(wall_mid, 2),
            "position_ratio": round(position_ratio, 4),
            "flattening": flattening,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_estimate,
            mode=mode,
            buy_below=buy_below,
            sell_above=sell_above,
            quote=quote,
            rationale=rationale,
            metadata=MappingProxyType(metadata),
        )

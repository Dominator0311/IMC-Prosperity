"""Single market-making strategy shared across products.

This is the only strategy in the engine today. It combines:

1. a fair-value estimate from ``FairValueEngine`` (which may be an
   anchor, mid, microprice, rolling or weighted mid depending on the
   product's config), and
2. a market-making intent from ``SignalEngine`` built around that
   fair value.

Different products tune *how* this strategy behaves via
``ProductConfig`` (edge widths, quote sizes, flatten thresholds) and
*which* fair-value estimator runs (``fair_value_method`` +
``fair_value_fallbacks``). A second strategy module only exists once
there is a genuinely different decision rule that cannot be reduced to
config.
"""

from __future__ import annotations

from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import SignalIntent
from src.strategies.base import BaseStrategy, StrategyContext


class MarketMakingStrategy(BaseStrategy):
    def __init__(self, fair_value_engine: FairValueEngine, signal_engine: SignalEngine) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        fair_value = self.fair_value_engine.estimate(
            context.product, context.snapshot, context.memory, context.config
        )
        return self.signal_engine.build_market_making_intent(
            context.product, context.snapshot, fair_value, context.config
        )

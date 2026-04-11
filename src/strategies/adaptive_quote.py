from __future__ import annotations

from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import SignalIntent
from src.strategies.base import BaseStrategy, StrategyContext


class AdaptiveQuoteStrategy(BaseStrategy):
    def __init__(
        self, fair_value_engine: FairValueEngine, signal_engine: SignalEngine
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        fair_value = self.fair_value_engine.estimate(
            context.product, context.snapshot, context.memory, context.config
        )
        return self.signal_engine.build_market_making_intent(
            context.product, context.snapshot, fair_value, context.config
        )


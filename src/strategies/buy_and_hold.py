"""Buy-and-hold: take any ask up to the position limit, never sell.

Used by ``round1_test_engine_config`` only. RiskManager caps buys at
``position_limit - position`` so the bot holds once full.
"""

from __future__ import annotations

from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import FairValueEstimate, QuoteIntent, SignalIntent
from src.strategies.base import BaseStrategy, StrategyContext

_TAKE_ANY_ASK: float = 1e9


class BuyAndHoldStrategy(BaseStrategy):
    def __init__(
        self,
        fair_value_engine: FairValueEngine | None = None,
        signal_engine: SignalEngine | None = None,
    ) -> None:
        del fair_value_engine, signal_engine

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        mid = context.snapshot.mid if context.snapshot.mid is not None else 0.0
        return SignalIntent(
            product=context.product,
            fair_value=FairValueEstimate(price=mid, method="buy_and_hold"),
            mode="taker",
            buy_below=_TAKE_ANY_ASK,
            sell_above=None,
            quote=QuoteIntent(bid_price=None, bid_size=0, ask_price=None, ask_size=0),
            rationale="buy_and_hold",
        )

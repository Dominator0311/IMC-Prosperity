from src.core.config import ProductConfig
from src.core.execution import ExecutionEngine
from src.core.types import (
    BookLevel,
    FairValueEstimate,
    NormalizedSnapshot,
    QuoteIntent,
    SignalIntent,
)


def test_execution_engine_generates_aggressive_and_passive_orders() -> None:
    engine = ExecutionEngine()
    snapshot = NormalizedSnapshot(
        product="EMERALDS",
        timestamp=0,
        bids=(BookLevel(9998, 4),),
        asks=(BookLevel(10002, 3),),
        position=0,
    )
    intent = SignalIntent(
        product="EMERALDS",
        fair_value=FairValueEstimate(price=10_000.0, method="anchor"),
        mode="hybrid",
        buy_below=10002,
        sell_above=10001,
        quote=QuoteIntent(bid_price=9997, bid_size=2, ask_price=10003, ask_size=2),
    )
    config = ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="anchor",
        anchor_price=10_000.0,
    )

    orders = engine.generate_orders(snapshot, intent, config)

    assert [(order.price, order.quantity) for order in orders] == [
        (10002, 3),
        (9997, 2),
        (10003, -2),
    ]

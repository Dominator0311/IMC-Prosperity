from src.core.market_data import MarketDataAdapter
from src.datamodel import Observation, OrderDepth, TradingState


def test_market_data_normalizes_sell_volumes_to_positive() -> None:
    adapter = MarketDataAdapter()
    state = TradingState(
        traderData="",
        timestamp=100,
        listings={},
        order_depths={
            "EMERALDS": OrderDepth(
                buy_orders={9998: 3, 9997: 2},
                sell_orders={10002: -4, 10003: -6},
            )
        },
        own_trades={},
        market_trades={},
        position={"EMERALDS": 1},
        observations=Observation(),
    )

    snapshots = adapter.normalize_state(state)
    snapshot = snapshots["EMERALDS"]

    assert snapshot.best_bid is not None and snapshot.best_bid.price == 9998
    assert snapshot.best_ask is not None and snapshot.best_ask.price == 10002
    assert snapshot.best_ask.volume == 4


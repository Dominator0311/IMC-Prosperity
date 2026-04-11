from src.datamodel import Observation, OrderDepth, TradingState
from src.trader import Trader


def test_trader_runs_smoke_path() -> None:
    trader = Trader()
    state = TradingState(
        traderData="",
        timestamp=0,
        listings={},
        order_depths={
            "EMERALDS": OrderDepth(
                buy_orders={9998: 5},
                sell_orders={10002: -5},
            )
        },
        own_trades={"EMERALDS": []},
        market_trades={"EMERALDS": []},
        position={"EMERALDS": 0},
        observations=Observation(),
    )

    orders, conversions, trader_data = trader.run(state)

    assert "EMERALDS" in orders
    assert conversions == 0
    assert isinstance(trader_data, str)

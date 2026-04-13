"""End-to-end integration tests for ``Trader.run``.

These exercise the full Phase 1 data path: state load -> normalize ->
strategy -> execution -> risk clip -> state save. They are intentionally
smoke-ish and focus on invariants rather than PnL numbers.
"""

from __future__ import annotations

import json

import pytest

from src.datamodel import Observation, Order, OrderDepth, TradingState
from src.trader import Trader


def _state(
    order_depths: dict[str, OrderDepth],
    *,
    position: dict[str, int] | None = None,
    trader_data: str = "",
    timestamp: int = 0,
) -> TradingState:
    return TradingState(
        traderData=trader_data,
        timestamp=timestamp,
        listings={},
        order_depths=order_depths,
        own_trades={product: [] for product in order_depths},
        market_trades={product: [] for product in order_depths},
        position=position or {},
        observations=Observation(),
    )


@pytest.mark.integration
def test_trader_runs_smoke_path_for_emeralds() -> None:
    trader = Trader()
    state = _state(
        {"EMERALDS": OrderDepth(buy_orders={9998: 5}, sell_orders={10002: -5})},
        position={"EMERALDS": 0},
    )

    orders, conversions, trader_data = trader.run(state)

    assert "EMERALDS" in orders
    assert conversions == 0
    assert isinstance(trader_data, str)
    json.loads(trader_data)  # must be valid JSON


@pytest.mark.integration
def test_trader_respects_position_limit_for_aggressive_buys() -> None:
    trader = Trader()
    # EMERALDS limit is 80 in default config; current position is 78.
    # Strategy will want to buy below 10000 anchor; risk must clip the buy
    # side aggregate to 2.
    state = _state(
        {
            "EMERALDS": OrderDepth(
                buy_orders={9998: 10},
                sell_orders={9995: -5, 9996: -5},
            )
        },
        position={"EMERALDS": 78},
    )

    orders, _, _ = trader.run(state)

    net_buy = sum(o.quantity for o in orders["EMERALDS"] if o.quantity > 0)
    assert net_buy <= 2


@pytest.mark.integration
def test_trader_ignores_unknown_products_without_crashing() -> None:
    trader = Trader()
    state = _state({"PEARLS": OrderDepth(buy_orders={100: 1}, sell_orders={101: -1})})

    orders, conversions, trader_data = trader.run(state)

    assert orders == {"PEARLS": []}
    assert conversions == 0
    assert isinstance(trader_data, str)


@pytest.mark.integration
def test_trader_persists_rolling_mids_across_iterations() -> None:
    trader = Trader()
    first = _state(
        {"EMERALDS": OrderDepth(buy_orders={9998: 1}, sell_orders={10002: -1})},
        position={"EMERALDS": 0},
    )
    _, _, trader_data_1 = trader.run(first)

    second = _state(
        {"EMERALDS": OrderDepth(buy_orders={9999: 1}, sell_orders={10001: -1})},
        position={"EMERALDS": 0},
        trader_data=trader_data_1,
        timestamp=1,
    )
    _, _, trader_data_2 = trader.run(second)

    state_after = trader.engine_state_from(trader_data_2)
    mids = state_after.products["EMERALDS"].recent_mids
    assert mids == [10_000.0, 10_000.0]


@pytest.mark.integration
def test_trader_handles_empty_order_depths() -> None:
    trader = Trader()
    state = _state({})
    orders, conversions, trader_data = trader.run(state)
    assert orders == {}
    assert conversions == 0
    assert isinstance(trader_data, str)


@pytest.mark.integration
def test_trader_returns_only_orders_for_the_product_symbol() -> None:
    trader = Trader()
    state = _state(
        {"EMERALDS": OrderDepth(buy_orders={9998: 5}, sell_orders={10002: -5})},
        position={"EMERALDS": 0},
    )
    orders, _, _ = trader.run(state)
    for order in orders["EMERALDS"]:
        assert isinstance(order, Order)
        assert order.symbol == "EMERALDS"


@pytest.mark.integration
def test_trader_crash_barrier_returns_empty_orders_on_strategy_exception() -> None:
    """A broken strategy must never crash Trader.run in production mode."""
    trader = Trader()

    class _Boom:
        def generate_intent(self, context: object) -> object:
            raise RuntimeError("intentional explosion")

    trader.strategies["market_making"] = _Boom()  # type: ignore[assignment]

    state = _state(
        {"EMERALDS": OrderDepth(buy_orders={9998: 5}, sell_orders={10002: -5})},
        position={"EMERALDS": 0},
        trader_data="previous_state_blob",
    )
    orders, conversions, trader_data = trader.run(state)

    assert orders == {}
    assert conversions == 0
    # On crash we preserve the previous trader_data so no state is lost.
    assert trader_data == "previous_state_blob"


@pytest.mark.integration
def test_trader_crash_barrier_reraises_in_test_mode() -> None:
    trader = Trader(reraise_exceptions=True)

    class _Boom:
        def generate_intent(self, context: object) -> object:
            raise RuntimeError("intentional explosion")

    trader.strategies["market_making"] = _Boom()  # type: ignore[assignment]

    state = _state(
        {"EMERALDS": OrderDepth(buy_orders={9998: 5}, sell_orders={10002: -5})},
        position={"EMERALDS": 0},
    )
    with pytest.raises(RuntimeError, match="intentional explosion"):
        trader.run(state)

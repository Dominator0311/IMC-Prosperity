"""Datamodel compatibility tests.

These are guards against accidental drift from the Prosperity platform
datamodel. They check field names, defaults, and JSON serialization
shape rather than behavior.
"""

from __future__ import annotations

import json

import pytest

from src.datamodel import (
    ConversionObservation,
    Listing,
    Observation,
    Order,
    OrderDepth,
    ProsperityEncoder,
    Trade,
    TradingState,
)


@pytest.mark.unit
def test_order_depth_defaults_are_independent_instances() -> None:
    a = OrderDepth()
    b = OrderDepth()
    a.buy_orders[100] = 1
    assert b.buy_orders == {}


@pytest.mark.unit
def test_trading_state_serializes_via_prosperity_encoder() -> None:
    state = TradingState(
        traderData="",
        timestamp=0,
        listings={"P": Listing(symbol="P", product="P", denomination="SEASHELLS")},
        order_depths={"P": OrderDepth(buy_orders={100: 1}, sell_orders={101: -1})},
        own_trades={"P": [Trade("P", 100, 1, timestamp=0)]},
        market_trades={},
        position={"P": 0},
        observations=Observation(),
    )
    payload = json.loads(json.dumps(state, cls=ProsperityEncoder, sort_keys=True))
    assert payload["timestamp"] == 0
    assert payload["order_depths"]["P"]["buy_orders"] == {"100": 1}
    assert payload["listings"]["P"]["denomination"] == "SEASHELLS"


@pytest.mark.unit
def test_order_is_shaped_like_platform_expects() -> None:
    order = Order(symbol="P", price=100, quantity=5)
    assert order.symbol == "P"
    assert order.price == 100
    assert order.quantity == 5


@pytest.mark.unit
def test_observation_defaults_are_empty_dicts() -> None:
    obs = Observation()
    assert obs.plainValueObservations == {}
    assert obs.conversionObservations == {}


@pytest.mark.unit
def test_conversion_observation_round_trips() -> None:
    obs = ConversionObservation(
        bidPrice=100.0,
        askPrice=101.0,
        transportFees=0.5,
        exportTariff=1.0,
        importTariff=0.25,
        sunlight=2.0,
        humidity=3.0,
    )
    payload = json.loads(json.dumps(obs, cls=ProsperityEncoder))
    assert payload["bidPrice"] == 100.0
    assert payload["transportFees"] == 0.5

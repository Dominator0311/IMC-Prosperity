"""Unit tests for ``src.core.market_data``.

The market data adapter is the only place where the Prosperity raw
``OrderDepth`` convention (negative sell volumes, unordered dicts) is
translated into canonical ``NormalizedSnapshot``s. Every downstream
engine module depends on this being correct.
"""

from __future__ import annotations

import pytest

from src.core.market_data import MarketDataAdapter
from src.core.types import BookLevel
from src.datamodel import Observation, OrderDepth, Trade, TradingState


def _state(
    order_depths: dict[str, OrderDepth], position: dict[str, int] | None = None
) -> TradingState:
    return TradingState(
        traderData="",
        timestamp=100,
        listings={},
        order_depths=order_depths,
        own_trades={},
        market_trades={},
        position=position or {},
        observations=Observation(),
    )


@pytest.mark.unit
def test_sell_orders_are_normalized_to_positive_volumes_and_sorted_ascending() -> None:
    adapter = MarketDataAdapter()
    state = _state(
        {
            "EMERALDS": OrderDepth(
                buy_orders={9998: 3, 9997: 2},
                sell_orders={10003: -6, 10002: -4},
            )
        },
        position={"EMERALDS": 1},
    )

    snapshot = adapter.normalize_state(state)["EMERALDS"]

    assert snapshot.best_bid == BookLevel(9998, 3)
    assert snapshot.best_ask == BookLevel(10002, 4)
    assert snapshot.asks[1] == BookLevel(10003, 6)
    assert snapshot.position == 1


@pytest.mark.unit
def test_market_data_tolerates_positive_sell_volume_convention() -> None:
    adapter = MarketDataAdapter()
    state = _state(
        {
            "X": OrderDepth(
                buy_orders={100: 5},
                sell_orders={101: 4, 102: 6},  # adversarial positive asks
            )
        }
    )
    snapshot = adapter.normalize_state(state)["X"]
    assert snapshot.best_ask == BookLevel(101, 4)
    assert snapshot.asks[1] == BookLevel(102, 6)


@pytest.mark.unit
def test_market_data_drops_zero_volume_levels() -> None:
    adapter = MarketDataAdapter()
    state = _state(
        {
            "X": OrderDepth(
                buy_orders={100: 5, 99: 0},
                sell_orders={101: -4, 102: 0},
            )
        }
    )
    snapshot = adapter.normalize_state(state)["X"]
    assert [level.price for level in snapshot.bids] == [100]
    assert [level.price for level in snapshot.asks] == [101]


@pytest.mark.unit
def test_mid_spread_microprice_and_imbalance_are_correct() -> None:
    adapter = MarketDataAdapter()
    state = _state(
        {
            "P": OrderDepth(
                buy_orders={100: 3},
                sell_orders={102: -1},
            )
        }
    )
    snapshot = adapter.normalize_state(state)["P"]
    assert snapshot.mid == pytest.approx(101.0)
    assert snapshot.spread == pytest.approx(2.0)
    # total = 4, (3 - 1) / 4 = 0.5
    assert snapshot.book_imbalance == pytest.approx(0.5)
    # microprice = (100 * 1 + 102 * 3) / 4 = 101.5
    assert snapshot.microprice == pytest.approx(101.5)


@pytest.mark.unit
def test_snapshot_returns_none_when_one_side_is_missing() -> None:
    adapter = MarketDataAdapter()
    state = _state({"P": OrderDepth(buy_orders={100: 2}, sell_orders={})})
    snapshot = adapter.normalize_state(state)["P"]
    assert snapshot.best_ask is None
    assert snapshot.mid is None
    assert snapshot.spread is None
    assert snapshot.book_imbalance is None
    assert snapshot.microprice is None


@pytest.mark.unit
def test_trades_are_merged_tagged_and_sorted() -> None:
    adapter = MarketDataAdapter()
    state = TradingState(
        traderData="",
        timestamp=200,
        listings={},
        order_depths={"P": OrderDepth(buy_orders={100: 1}, sell_orders={101: -1})},
        own_trades={"P": [Trade("P", 100, 1, timestamp=150)]},
        market_trades={
            "P": [
                Trade("P", 101, 2, timestamp=100),
                Trade("P", 102, 1, timestamp=175),
            ]
        },
        position={},
        observations=Observation(),
    )

    snapshot = adapter.normalize_state(state)["P"]
    assert [trade.timestamp for trade in snapshot.trades] == [100, 150, 175]
    assert [trade.source for trade in snapshot.trades] == ["market", "own", "market"]


@pytest.mark.unit
def test_missing_position_dict_defaults_to_zero() -> None:
    adapter = MarketDataAdapter()
    state = TradingState(
        traderData="",
        timestamp=0,
        listings={},
        order_depths={"P": OrderDepth(buy_orders={100: 1}, sell_orders={101: -1})},
        own_trades={},
        market_trades={},
        position={},
        observations=Observation(),
    )
    snapshot = adapter.normalize_state(state)["P"]
    assert snapshot.position == 0


@pytest.mark.unit
def test_top_bids_and_top_asks_helpers_return_prefix() -> None:
    adapter = MarketDataAdapter()
    state = _state(
        {
            "P": OrderDepth(
                buy_orders={100: 5, 99: 4, 98: 3},
                sell_orders={101: -5, 102: -4, 103: -3},
            )
        }
    )
    snapshot = adapter.normalize_state(state)["P"]
    assert snapshot.top_bids(2) == (BookLevel(100, 5), BookLevel(99, 4))
    assert snapshot.top_asks(2) == (BookLevel(101, 5), BookLevel(102, 4))
    assert snapshot.top_bids(0) == ()
    assert snapshot.total_bid_volume() == 12
    assert snapshot.total_ask_volume(depth=2) == 9

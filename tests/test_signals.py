"""Unit tests for ``src.core.signals.SignalEngine``."""

from __future__ import annotations

import pytest

from src.core.config import ProductConfig
from src.core.signals import SignalEngine
from src.core.types import BookLevel, FairValueEstimate, NormalizedSnapshot


def _config(position_limit: int = 20, flatten_threshold: float = 0.75) -> ProductConfig:
    return ProductConfig(
        position_limit=position_limit,
        strategy_name="market_making",
        fair_value_method="anchor",
        anchor_price=10_000.0,
        taker_edge=1.0,
        maker_edge=2.0,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=2.0,
        flatten_threshold=flatten_threshold,
    )


def _snapshot(position: int) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="P",
        timestamp=0,
        bids=(BookLevel(9992, 15),),
        asks=(BookLevel(10008, 15),),
        position=position,
    )


def _fair() -> FairValueEstimate:
    return FairValueEstimate(price=10_000.0, method="anchor")


@pytest.mark.unit
def test_neutral_position_produces_hybrid_mode_with_buy_and_sell_intents() -> None:
    engine = SignalEngine()
    intent = engine.build_market_making_intent("P", _snapshot(0), _fair(), _config())
    assert intent.mode == "hybrid"
    assert intent.buy_below is not None
    assert intent.sell_above is not None
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.ask_size > 0


@pytest.mark.unit
def test_long_at_flatten_threshold_disables_buy_side_entirely() -> None:
    engine = SignalEngine()
    # 0.75 * 20 = 15 -> position 15 hits the threshold.
    intent = engine.build_market_making_intent("P", _snapshot(15), _fair(), _config())
    assert intent.mode == "recovery"
    assert intent.buy_below is None
    assert intent.quote is not None
    assert intent.quote.bid_size == 0
    assert intent.quote.bid_price is None
    # Ask should still be alive and pulled in toward fair value.
    assert intent.quote.ask_size > 0
    assert intent.quote.ask_price is not None
    assert intent.quote.ask_price <= 10_000


@pytest.mark.unit
def test_short_at_flatten_threshold_disables_sell_side_entirely() -> None:
    engine = SignalEngine()
    intent = engine.build_market_making_intent("P", _snapshot(-15), _fair(), _config())
    assert intent.mode == "recovery"
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size == 0
    assert intent.quote.ask_price is None
    assert intent.quote.bid_size > 0
    assert intent.quote.bid_price is not None
    assert intent.quote.bid_price >= 10_000


@pytest.mark.unit
def test_mild_position_still_skews_but_does_not_flatten() -> None:
    engine = SignalEngine()
    intent = engine.build_market_making_intent(
        "P", _snapshot(5), _fair(), _config(flatten_threshold=0.9)
    )
    assert intent.mode == "hybrid"
    assert intent.buy_below is not None
    assert intent.sell_above is not None


@pytest.mark.unit
def test_skew_makes_both_taker_thresholds_less_permissive_when_long() -> None:
    """When long, skew>0 shifts both taker thresholds DOWN.

    Regression guard against the claim that skew could *increase* taker
    buying into a long position. Lower ``buy_below`` means we require
    a cheaper ask to cross, i.e. we are *less* eager to buy. The math
    is correct; this test locks it in.
    """
    engine = SignalEngine()
    neutral = engine.build_market_making_intent("P", _snapshot(0), _fair(), _config())
    long_pos = engine.build_market_making_intent("P", _snapshot(5), _fair(), _config())
    assert neutral.buy_below is not None
    assert long_pos.buy_below is not None
    assert long_pos.buy_below < neutral.buy_below  # less permissive for buys
    assert neutral.sell_above is not None
    assert long_pos.sell_above is not None
    assert long_pos.sell_above < neutral.sell_above  # more permissive for sells


@pytest.mark.unit
def test_skew_makes_both_taker_thresholds_more_permissive_when_short() -> None:
    engine = SignalEngine()
    neutral = engine.build_market_making_intent("P", _snapshot(0), _fair(), _config())
    short_pos = engine.build_market_making_intent("P", _snapshot(-5), _fair(), _config())
    assert neutral.buy_below is not None
    assert short_pos.buy_below is not None
    assert short_pos.buy_below > neutral.buy_below  # more permissive for buys
    assert neutral.sell_above is not None
    assert short_pos.sell_above is not None
    assert short_pos.sell_above > neutral.sell_above  # less permissive for sells

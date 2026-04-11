"""Unit tests for ``src.core.fair_value``."""

from __future__ import annotations

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import (
    AnchorEstimator,
    FairValueEngine,
    MicropriceEstimator,
    MidEstimator,
    RollingMidEstimator,
    WeightedMidEstimator,
)
from src.core.types import BookLevel, NormalizedSnapshot, ProductMemory


def _anchor_config(price: float = 10_000.0) -> ProductConfig:
    return ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="anchor",
        fair_value_fallbacks=("microprice", "mid"),
        anchor_price=price,
    )


def _mid_config() -> ProductConfig:
    return ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="mid",
        fair_value_fallbacks=(),
    )


def _snapshot(
    *, bid: int = 9998, bid_vol: int = 5, ask: int = 10002, ask_vol: int = 5
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="P",
        timestamp=0,
        bids=(BookLevel(bid, bid_vol),),
        asks=(BookLevel(ask, ask_vol),),
        position=0,
    )


@pytest.mark.unit
def test_anchor_estimator_returns_anchor_price() -> None:
    result = AnchorEstimator().estimate(_snapshot(), ProductMemory(), _anchor_config())
    assert result is not None
    assert result.price == 10_000.0
    assert result.method == "anchor"
    assert result.components["anchor_price"] == 10_000.0


@pytest.mark.unit
def test_anchor_estimator_returns_none_without_anchor_price() -> None:
    config = _mid_config()  # no anchor_price set
    result = AnchorEstimator().estimate(_snapshot(), ProductMemory(), config)
    assert result is None


@pytest.mark.unit
def test_mid_microprice_estimators_return_expected_values() -> None:
    memory = ProductMemory()
    config = _mid_config()
    snap = _snapshot(bid=100, bid_vol=3, ask=102, ask_vol=1)
    mid = MidEstimator().estimate(snap, memory, config)
    micro = MicropriceEstimator().estimate(snap, memory, config)
    assert mid is not None
    assert mid.price == 101.0
    assert micro is not None
    # (100 * 1 + 102 * 3) / 4 = 101.5
    assert micro.price == pytest.approx(101.5)


@pytest.mark.unit
def test_rolling_mid_averages_history_and_current_mid() -> None:
    memory = ProductMemory(recent_mids=[99.0, 100.0, 101.0])
    snap = _snapshot(bid=100, bid_vol=1, ask=102, ask_vol=1)  # mid 101
    result = RollingMidEstimator().estimate(snap, memory, _mid_config())
    assert result is not None
    # Mean of [99, 100, 101, 101] = 100.25
    assert result.price == pytest.approx(100.25)


@pytest.mark.unit
def test_weighted_mid_puts_more_weight_on_recent_mids() -> None:
    memory = ProductMemory(recent_mids=[100.0, 100.0, 100.0, 100.0])
    snap = _snapshot(bid=110, bid_vol=1, ask=110, ask_vol=1)  # mid 110
    result = WeightedMidEstimator().estimate(snap, memory, _mid_config())
    assert result is not None
    # Weights 1..5; values [100, 100, 100, 100, 110]; total_w = 15
    # num = 100*1 + 100*2 + 100*3 + 100*4 + 110*5 = 1000 + 550 = 1550? no
    # = 100+200+300+400+550 = 1550 → 1550/15 = 103.333
    assert result.price == pytest.approx(103.3333, rel=1e-3)


@pytest.mark.unit
def test_engine_primary_falls_through_to_next_when_returning_none() -> None:
    """If weighted_mid has no mid and no history, fall through to anchor."""
    config = ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="weighted_mid",
        fair_value_fallbacks=("anchor",),
        anchor_price=10_000.0,
    )
    # Snapshot with no bids (so mid is None) and empty memory.
    snap = NormalizedSnapshot(product="P", timestamp=0, bids=(), asks=())
    engine = FairValueEngine()
    result = engine.estimate("P", snap, ProductMemory(), config)
    assert result.method == "anchor"
    assert result.price == 10_000.0


@pytest.mark.unit
def test_engine_returns_anchor_fallback_when_all_estimators_decline() -> None:
    """No primary, no fallback, no mid -> anchor_fallback."""
    config = ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="mid",
        fair_value_fallbacks=(),
        anchor_price=50.0,
    )
    snap = NormalizedSnapshot(product="P", timestamp=0, bids=(), asks=())
    result = FairValueEngine().estimate("P", snap, ProductMemory(), config)
    assert result.method == "anchor_fallback"
    assert result.price == 50.0


@pytest.mark.unit
def test_estimate_all_returns_every_non_none_estimator() -> None:
    engine = FairValueEngine()
    snap = _snapshot(bid=99, bid_vol=2, ask=101, ask_vol=2)
    results = engine.estimate_all(snap, ProductMemory(), _anchor_config())
    assert "anchor" in results
    assert "mid" in results
    assert "microprice" in results
    # rolling_mid and weighted_mid work too because snap has a mid
    assert "rolling_mid" in results
    assert "weighted_mid" in results
    assert results["anchor"].price == 10_000.0
    assert results["mid"].price == 100.0


@pytest.mark.unit
def test_fair_value_estimate_components_is_immutable() -> None:
    """Regression guard: frozen + MappingProxyType should reject mutation."""
    result = AnchorEstimator().estimate(_snapshot(), ProductMemory(), _anchor_config())
    assert result is not None
    with pytest.raises(TypeError):
        result.components["x"] = 1  # type: ignore[index]

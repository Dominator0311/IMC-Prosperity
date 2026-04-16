"""Unit tests for ``src.strategies.ash_target_position``.

Covers the pure target math, the ``TargetPositionParams`` validation,
and the intent building.
"""

from __future__ import annotations

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import BookLevel, NormalizedSnapshot, ProductMemory
from src.strategies.ash_target_position import (
    AshTargetPositionStrategy,
    TargetPositionParams,
    compute_target_position,
)
from src.strategies.base import StrategyContext


# ------------------------------------------------------------ pure target math


@pytest.mark.unit
def test_linear_target_clipped_and_signed() -> None:
    assert compute_target_position(
        4.0, mode="linear", alpha=5, dead_zone=0, gamma=1.0, cap=40
    ) == -20
    assert compute_target_position(
        -4.0, mode="linear", alpha=5, dead_zone=0, gamma=1.0, cap=40
    ) == 20
    assert compute_target_position(
        100.0, mode="linear", alpha=5, dead_zone=0, gamma=1.0, cap=40
    ) == -40
    assert compute_target_position(
        0.0, mode="linear", alpha=5, dead_zone=0, gamma=1.0, cap=40
    ) == 0


@pytest.mark.unit
def test_dead_zone_returns_zero_inside_band() -> None:
    for r in (-1.0, -0.5, 0.0, 0.5, 1.0):
        assert (
            compute_target_position(
                r, mode="dead_zone", alpha=8, dead_zone=1.0, gamma=1.0, cap=40
            )
            == 0
        )
    assert (
        compute_target_position(
            2.0, mode="dead_zone", alpha=8, dead_zone=1.0, gamma=1.0, cap=40
        )
        == -8
    )


@pytest.mark.unit
def test_convex_grows_faster_than_linear() -> None:
    linear = compute_target_position(
        3.0, mode="linear", alpha=2, dead_zone=0, gamma=1.0, cap=40
    )
    convex = compute_target_position(
        3.0, mode="convex", alpha=2, dead_zone=0, gamma=2.0, cap=40
    )
    assert abs(convex) > abs(linear)
    assert convex < 0
    assert (
        abs(
            compute_target_position(
                10.0, mode="convex", alpha=2, dead_zone=0, gamma=2.0, cap=40
            )
        )
        == 40
    )


@pytest.mark.unit
def test_zero_cap_or_alpha_forces_zero_target() -> None:
    assert (
        compute_target_position(
            5.0, mode="linear", alpha=10, dead_zone=0, gamma=1.0, cap=0
        )
        == 0
    )
    assert (
        compute_target_position(
            5.0, mode="linear", alpha=0, dead_zone=0, gamma=1.0, cap=40
        )
        == 0
    )


# ------------------------------------------------------------ params validation


@pytest.mark.unit
def test_params_reject_bad_mode() -> None:
    with pytest.raises(ValueError):
        TargetPositionParams(mode="bogus", alpha=1.0)  # type: ignore[arg-type]


@pytest.mark.unit
def test_params_reject_bad_style() -> None:
    with pytest.raises(ValueError):
        TargetPositionParams(exec_style="weird", alpha=1.0)  # type: ignore[arg-type]


@pytest.mark.unit
def test_params_reject_negative_alpha() -> None:
    with pytest.raises(ValueError):
        TargetPositionParams(alpha=-1.0)


# ------------------------------------------------------------ intent building


def _base_cfg(**overrides: object) -> ProductConfig:
    defaults: dict[str, object] = dict(
        position_limit=50,
        strategy_name="market_making",
        fair_value_method="anchor",
        anchor_price=10_000.0,
        taker_edge=0.5,
        maker_edge=1.5,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=4.0,
        flatten_threshold=0.7,
        history_length=48,
    )
    defaults.update(overrides)
    return ProductConfig(**defaults)  # type: ignore[arg-type]


def _snapshot(mid_price: int, position: int = 0) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(mid_price - 8, 20),),
        asks=(BookLevel(mid_price + 8, 20),),
        position=position,
    )


def _context(config: ProductConfig, snapshot: NormalizedSnapshot) -> StrategyContext:
    return StrategyContext(
        product="ASH_COATED_OSMIUM",
        snapshot=snapshot,
        memory=ProductMemory(),
        config=config,
    )


def _strategy(params: TargetPositionParams) -> AshTargetPositionStrategy:
    return AshTargetPositionStrategy(FairValueEngine(), SignalEngine(), params)


@pytest.mark.unit
def test_price_at_mean_inside_dead_zone_quotes_thinly_no_taker() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40,
        exec_style="hybrid", hybrid_threshold=2.0,
    )
    strat = _strategy(params)
    intent = strat.generate_intent(_context(_base_cfg(), _snapshot(10_000)))
    assert intent.buy_below is None
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.ask_size > 0


@pytest.mark.unit
def test_price_above_mean_targets_short_gaps_ask_side() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40,
        exec_style="hybrid", hybrid_threshold=2.0,
    )
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(10_003, position=0))
    )
    assert intent.quote is not None
    assert intent.quote.ask_size > 0
    assert intent.quote.bid_size == 0
    assert intent.sell_above is not None
    assert intent.buy_below is None


@pytest.mark.unit
def test_price_below_mean_targets_long_gaps_bid_side() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40,
        exec_style="hybrid", hybrid_threshold=2.0,
    )
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(9_997, position=0))
    )
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.ask_size == 0
    assert intent.buy_below is not None


@pytest.mark.unit
def test_maker_only_never_sets_taker_thresholds() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40, exec_style="maker",
    )
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(10_005, position=0))
    )
    assert intent.buy_below is None
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size > 0


@pytest.mark.unit
def test_taker_style_always_sets_thresholds_when_gap_nonzero() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40,
        exec_style="taker", hybrid_threshold=100.0,
    )
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(10_002, position=0))
    )
    assert intent.sell_above is not None


@pytest.mark.unit
def test_hybrid_threshold_suppresses_taker_when_residual_small() -> None:
    params = TargetPositionParams(
        mode="dead_zone", alpha=8, dead_zone=1.0, cap=40,
        exec_style="hybrid", hybrid_threshold=5.0,
    )
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(10_003, position=0))
    )
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size > 0


@pytest.mark.unit
def test_flatten_threshold_suppresses_adding_side_when_near_limit() -> None:
    params = TargetPositionParams(
        mode="linear", alpha=5, dead_zone=0.0, cap=50,
        exec_style="hybrid", hybrid_threshold=2.0,
    )
    cfg = _base_cfg(flatten_threshold=0.4)
    # Large positive residual -> target deeply short; but we are already
    # short to -25 (|ratio|=0.5 >= 0.4) -> flatten must kill the sell side.
    intent = _strategy(params).generate_intent(
        _context(cfg, _snapshot(10_010, position=-25))
    )
    assert intent.mode == "recovery"
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size == 0


@pytest.mark.unit
def test_zero_alpha_falls_back_to_legacy_mm_intent() -> None:
    params = TargetPositionParams(mode="linear", alpha=0.0, cap=40)
    intent = _strategy(params).generate_intent(
        _context(_base_cfg(), _snapshot(10_002))
    )
    # MM intent sets both buy_below and sell_above at neutral position.
    assert intent.buy_below is not None
    assert intent.sell_above is not None
    assert "target_position" not in intent.metadata

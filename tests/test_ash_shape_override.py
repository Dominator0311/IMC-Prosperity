"""Unit tests for ``src.strategies.ash_shape_override``.

These tests pin the behavior of each shape-lever to known values so
Phase-B isolation is meaningful. All tests use a single-snapshot
fixture — the downstream integration tests in Phase B exercise full
replay sweeps.
"""

from __future__ import annotations

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import BookLevel, FairValueEstimate, NormalizedSnapshot, ProductMemory
from src.strategies.ash_shape_override import (
    AshShapeOverrideStrategy,
    ShapeParams,
    compute_flatten,
    compute_sizes,
    compute_skew,
)
from src.strategies.base import StrategyContext

# ---------------------------------------------------------------- fixtures


def _config(**overrides: object) -> ProductConfig:
    defaults: dict[str, object] = {
        "position_limit": 80,
        "strategy_name": "market_making",
        "fair_value_method": "wall_mid",
        "fair_value_fallbacks": ("mid", "microprice"),
        "anchor_price": 10_000.0,
        "taker_edge": 0.5,
        "maker_edge": 1.5,
        "quote_size": 5,
        "max_aggressive_size": 10,
        "inventory_skew": 4.0,
        "flatten_threshold": 0.7,
        "history_length": 48,
    }
    defaults.update(overrides)
    return ProductConfig(**defaults)  # type: ignore[arg-type]


def _snapshot(position: int = 0, timestamp: int = 0) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=timestamp,
        bids=(
            BookLevel(price=9_992, volume=10),
            BookLevel(price=9_989, volume=20),
        ),
        asks=(
            BookLevel(price=10_008, volume=10),
            BookLevel(price=10_011, volume=20),
        ),
        position=position,
    )


def _fair_value(price: float = 10_000.0) -> FairValueEstimate:
    return FairValueEstimate(price=price, method="wall_mid", confidence=0.75)


# -------------------------------------------------------- skew primitives


def test_compute_skew_linear_matches_signal_engine() -> None:
    cfg = _config(inventory_skew=4.0)
    p = ShapeParams(skew_mode="linear", skew_coef=4.0)
    skew = compute_skew(position_ratio=0.5, config=cfg, params=p, time_remaining=50_000)
    assert skew == pytest.approx(2.0)


def test_compute_skew_tanh_saturates() -> None:
    p = ShapeParams(skew_mode="tanh", skew_coef=4.0)
    cfg = _config()
    # |position_ratio| approaching 1 saturates near ±skew_coef · tanh(2) ≈ ±3.86.
    high = compute_skew(position_ratio=0.95, config=cfg, params=p, time_remaining=0)
    low = compute_skew(position_ratio=0.5, config=cfg, params=p, time_remaining=0)
    assert high > low  # monotone in inventory
    assert abs(high) < 4.0 * 1.01  # saturated near but below coef


def test_compute_skew_quadratic_preserves_sign() -> None:
    p = ShapeParams(skew_mode="quadratic", skew_coef=4.0)
    cfg = _config()
    assert compute_skew(position_ratio=0.5, config=cfg, params=p, time_remaining=0) == pytest.approx(1.0)
    assert compute_skew(position_ratio=-0.5, config=cfg, params=p, time_remaining=0) == pytest.approx(-1.0)


def test_compute_skew_as_scales_with_time_remaining() -> None:
    p = ShapeParams(skew_mode="as", as_gamma=0.1, as_sigma=2.0, as_horizon=100_000)
    cfg = _config(position_limit=80)
    q_ratio = 0.5  # = 40 shares
    skew_start = compute_skew(
        position_ratio=q_ratio, config=cfg, params=p, time_remaining=100_000,
    )
    skew_end = compute_skew(
        position_ratio=q_ratio, config=cfg, params=p, time_remaining=1_000,
    )
    # AS term: q * gamma * sigma^2 * (T - t).
    expected_start = 40.0 * 0.1 * 4.0 * 100_000
    expected_end = 40.0 * 0.1 * 4.0 * 1_000
    assert skew_start == pytest.approx(expected_start)
    assert skew_end == pytest.approx(expected_end)


# -------------------------------------------------------- size primitives


def test_compute_sizes_constant_mode() -> None:
    cfg = _config(quote_size=5)
    p = ShapeParams(size_mode="constant")
    assert compute_sizes(position_ratio=0.5, config=cfg, params=p) == (5, 5)


def test_compute_sizes_linear_asymmetric() -> None:
    cfg = _config(quote_size=5)
    p = ShapeParams(size_mode="linear", size_min=1, size_max=10)
    bid, ask = compute_sizes(position_ratio=0.5, config=cfg, params=p)
    assert bid < ask  # long → shrink bid, grow ask
    bid2, ask2 = compute_sizes(position_ratio=-0.5, config=cfg, params=p)
    assert bid2 > ask2  # short → grow bid, shrink ask


def test_compute_sizes_stepwise_triggers_above_ratio() -> None:
    cfg = _config(quote_size=5)
    p = ShapeParams(size_mode="stepwise", size_step_ratio=0.4, size_min=1, size_max=10)
    assert compute_sizes(position_ratio=0.3, config=cfg, params=p) == (5, 5)  # below step
    assert compute_sizes(position_ratio=0.7, config=cfg, params=p) == (1, 10)  # long triggers
    assert compute_sizes(position_ratio=-0.7, config=cfg, params=p) == (10, 1)  # short triggers


# -------------------------------------------------------- flatten primitive


def test_flatten_hard_matches_signal_engine() -> None:
    cfg = _config()
    p = ShapeParams(flatten_mode="hard", flatten_threshold=0.7)
    is_f, extra = compute_flatten(position_ratio=0.65, config=cfg, params=p)
    assert is_f is False and extra == 0.0
    is_f2, extra2 = compute_flatten(position_ratio=0.75, config=cfg, params=p)
    assert is_f2 is True and extra2 == 0.0


def test_flatten_soft_target_produces_extra_skew() -> None:
    cfg = _config()
    p = ShapeParams(
        flatten_mode="soft_target", flatten_k=0.5, skew_coef=4.0,
    )
    is_f, extra = compute_flatten(position_ratio=0.5, config=cfg, params=p)
    assert is_f is False
    assert extra == pytest.approx(0.5 * 4.0 * 0.5)


def test_flatten_as_continuous_always_off_hard() -> None:
    cfg = _config()
    p = ShapeParams(flatten_mode="as_continuous")
    is_f, extra = compute_flatten(position_ratio=0.99, config=cfg, params=p)
    assert is_f is False and extra == 0.0


# -------------------------------------------------------- end-to-end strategy


def test_strategy_at_c_h1_alt_defaults_produces_valid_intent() -> None:
    strat = AshShapeOverrideStrategy(
        fair_value_engine=FairValueEngine(),
        signal_engine=SignalEngine(),
        params=ShapeParams(),
    )
    ctx = StrategyContext(
        product="ASH_COATED_OSMIUM",
        snapshot=_snapshot(position=20),
        memory=ProductMemory(),
        config=_config(),
    )
    intent = strat.generate_intent(ctx)
    assert intent.product == "ASH_COATED_OSMIUM"
    assert intent.quote is not None
    assert intent.buy_below is not None and intent.sell_above is not None
    # Long: position_ratio = 0.25, skew = 4 * 0.25 = 1.0
    # buy_below = fair - 0.5 - 1.0, sell_above = fair + 0.5 - 1.0
    # Default fair_value is the engine's wall_mid on our fixture.
    # wall_bid = 9989 (volume 20), wall_ask = 10011 (volume 20); mid = 10000.
    expected_fair = (9_989 + 10_011) / 2.0
    assert intent.fair_value.price == pytest.approx(expected_fair)
    assert intent.buy_below == pytest.approx(expected_fair - 0.5 - 1.0)
    assert intent.sell_above == pytest.approx(expected_fair + 0.5 - 1.0)
    assert intent.quote.bid_size == 5
    assert intent.quote.ask_size == 5
    assert intent.metadata["skew_mode"] == "linear"


def test_strategy_flatten_recovery_disables_buy_side_when_long() -> None:
    strat = AshShapeOverrideStrategy(
        fair_value_engine=FairValueEngine(),
        signal_engine=SignalEngine(),
        params=ShapeParams(flatten_mode="hard", flatten_threshold=0.7),
    )
    # position_ratio = 60/80 = 0.75 > 0.7 → flatten
    ctx = StrategyContext(
        product="ASH_COATED_OSMIUM",
        snapshot=_snapshot(position=60),
        memory=ProductMemory(),
        config=_config(),
    )
    intent = strat.generate_intent(ctx)
    assert intent.mode == "recovery"
    assert intent.quote is not None
    assert intent.quote.bid_size == 0
    assert intent.buy_below is None


def test_strategy_validates_shape_params() -> None:
    with pytest.raises(ValueError):
        ShapeParams(skew_mode="nope")
    with pytest.raises(ValueError):
        ShapeParams(flatten_mode="nope")
    with pytest.raises(ValueError):
        ShapeParams(size_mode="nope")
    with pytest.raises(ValueError):
        ShapeParams(flatten_threshold=1.5)
    with pytest.raises(ValueError):
        ShapeParams(as_gamma=-0.1)

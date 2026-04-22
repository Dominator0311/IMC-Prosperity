"""Unit tests for Phase-C composite strategies.

Covers:
- ``ash_avellaneda_stoikov`` (C1)
- ``ash_gueant`` (C2)
- ``ash_cartea_skew`` (C3)
- Phase-C extensions to ``ash_target_position`` (C5)

Tests pin individual mechanisms to known values (closed-form
formulas) and verify that end-to-end ``generate_intent`` calls
produce well-shaped ``SignalIntent`` objects. Integration with the
replay harness is covered by the Phase-C runner tests.
"""

from __future__ import annotations

import math

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import BookLevel, NormalizedSnapshot, ProductMemory
from src.strategies.ash_avellaneda_stoikov import (
    AshAvellanedaStoikovStrategy,
    AvellanedaStoikovParams,
    half_spread,
    reservation_price,
)
from src.strategies.ash_cartea_skew import (
    AshCarteaSkewStrategy,
    CarteaSkewParams,
    compute_alpha,
)
from src.strategies.ash_gueant import (
    AshGueantStrategy,
    GueantParams,
    gueant_reservation_price,
    mean_reverting_factor,
)
from src.strategies.ash_target_position import (
    AshTargetPositionStrategy,
    TargetPositionParams,
    _ewma_of_recent_mids,
    _resolve_cap,
    _resolve_mean,
)
from src.strategies.base import StrategyContext

# ------------------------------------------------------------------ fixtures


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
        bids=(BookLevel(price=9_992, volume=10), BookLevel(price=9_989, volume=20)),
        asks=(BookLevel(price=10_008, volume=10), BookLevel(price=10_011, volume=20)),
        position=position,
    )


# ================================================================== C1: AS


def test_as_reservation_price_matches_formula() -> None:
    p = AvellanedaStoikovParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000)
    r = reservation_price(fair=10_000.0, position=40, timestamp=0, params=p)
    # r = 10000 - 40 * 5e-7 * 4 * 100000 = 10000 - 8 = 9992.0
    assert r == pytest.approx(9_992.0, rel=1e-9)


def test_as_half_spread_uses_both_terms() -> None:
    p = AvellanedaStoikovParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000)
    delta = half_spread(timestamp=0, params=p)
    term1 = 5e-7 * 4.0 * 100_000 / 2.0
    term2 = math.log(1.0 + 5e-7 / 0.4) / 5e-7
    assert delta == pytest.approx(term1 + term2, rel=1e-6)


def test_as_half_spread_respects_min_floor() -> None:
    p = AvellanedaStoikovParams(
        gamma=1e-3, sigma=2.0, k=1e6, horizon=100_000, min_half_spread=2.0,
    )
    # With tiny (1/gamma)*ln(1+gamma/k), raw delta would be << 2.0.
    delta = half_spread(timestamp=99_999, params=p)
    assert delta >= 2.0


def test_as_generate_intent_quotes_around_reservation() -> None:
    strat = AshAvellanedaStoikovStrategy(
        FairValueEngine(), SignalEngine(),
        AvellanedaStoikovParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000),
    )
    ctx = StrategyContext(
        product="ASH_COATED_OSMIUM",
        snapshot=_snapshot(position=20, timestamp=0),
        memory=ProductMemory(),
        config=_config(),
    )
    intent = strat.generate_intent(ctx)
    assert intent.quote is not None
    # Reservation price with long inventory shifts DOWN.
    expected_r = float(intent.fair_value.price) - 20 * 5e-7 * 4.0 * 100_000
    assert intent.metadata["reservation_price"] == pytest.approx(
        round(expected_r, 4), rel=1e-6,
    )


def test_as_params_validate() -> None:
    with pytest.raises(ValueError):
        AvellanedaStoikovParams(gamma=0.0)
    with pytest.raises(ValueError):
        AvellanedaStoikovParams(gamma=1e-6, sigma=-1.0)
    with pytest.raises(ValueError):
        AvellanedaStoikovParams(gamma=1e-6, k=0.0)


# ================================================================== C2: Guéant


def test_gueant_factor_collapses_to_t_minus_t_at_theta_zero() -> None:
    p = GueantParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000, theta=0.0)
    assert mean_reverting_factor(0, p) == pytest.approx(100_000.0)
    assert mean_reverting_factor(50_000, p) == pytest.approx(50_000.0)


def test_gueant_factor_saturates_at_large_theta_t() -> None:
    p = GueantParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000, theta=0.10)
    # theta * (T-t) >> 0 so factor ~ 1/(2 theta) = 5.
    assert mean_reverting_factor(0, p) == pytest.approx(5.0, rel=1e-3)


def test_gueant_reservation_price_is_mild_vs_as() -> None:
    # At theta=0.10, T-t=100k, mr_factor = 5. AS would give T-t=100k.
    # So Guéant's inventory-adjustment term is 20000x smaller than AS.
    gp = GueantParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000, theta=0.10)
    ap = AvellanedaStoikovParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000)
    g_r = gueant_reservation_price(fair=10_000.0, position=40, timestamp=0, params=gp)
    a_r = reservation_price(fair=10_000.0, position=40, timestamp=0, params=ap)
    assert abs(g_r - 10_000.0) < abs(a_r - 10_000.0)


def test_gueant_generate_intent_runs_end_to_end() -> None:
    strat = AshGueantStrategy(
        FairValueEngine(), SignalEngine(),
        GueantParams(gamma=5e-7, sigma=2.0, k=0.4, horizon=100_000, theta=0.10),
    )
    ctx = StrategyContext(
        product="ASH_COATED_OSMIUM",
        snapshot=_snapshot(position=10, timestamp=10_000),
        memory=ProductMemory(),
        config=_config(),
    )
    intent = strat.generate_intent(ctx)
    assert intent.quote is not None
    assert "theta" in intent.metadata
    assert intent.metadata["theta"] == 0.10


# ================================================================== C3: Cartea


def test_cartea_alpha_is_zero_when_mid_equals_fair() -> None:
    params = CarteaSkewParams(beta=1.0, fv_for_alpha="wall_mid")
    # With best_bid=9992 and best_ask=10008, wall_mid uses largest-volume
    # levels (9989 and 10011), so wall_mid=10000, mid=10000, residual=0.
    snap = _snapshot()
    alpha = compute_alpha(snap, ProductMemory(), _config(), params)
    assert alpha == pytest.approx(0.0)


def test_cartea_alpha_clips_large_residual() -> None:
    params = CarteaSkewParams(
        beta=1.0, fv_for_alpha="wall_mid", sigma_residual_prior=1.0, alpha_clip=2.5,
    )
    # wall_mid sits above mid by a huge offset via forcing wall levels
    # further up on both sides.
    snap = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=9_992, volume=1), BookLevel(price=9_970, volume=30)),
        asks=(BookLevel(price=10_008, volume=1), BookLevel(price=10_080, volume=30)),
    )
    alpha = compute_alpha(snap, ProductMemory(), _config(), params)
    # Raw residual = mid - wall_mid = 10000 - 10025 = -25 → z = -25, clip to -2.5.
    assert alpha == pytest.approx(-2.5)


def test_cartea_shifts_quotes_down_when_alpha_positive() -> None:
    # Force alpha > 0 by giving the mid a higher value than the wall_mid.
    # Planted: inside book at wide touches, wall well below mid.
    strat = AshCarteaSkewStrategy(
        FairValueEngine(), SignalEngine(),
        CarteaSkewParams(
            beta=2.0, fv_for_alpha="wall_mid",
            sigma_residual_prior=1.0, alpha_clip=10.0,
        ),
    )
    snap = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=9_995, volume=1), BookLevel(price=9_980, volume=30)),
        asks=(BookLevel(price=10_005, volume=1), BookLevel(price=10_010, volume=30)),
    )
    # wall_mid = (9980 + 10010)/2 = 9995; mid = 10000; residual = +5; alpha = +5.
    ctx = StrategyContext("ASH_COATED_OSMIUM", snap, ProductMemory(), _config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["alpha"] == pytest.approx(5.0)
    # alpha_shift = beta * alpha = 2 * 5 = +10, so bid/ask shift DOWN by 10.
    assert intent.metadata["alpha_shift"] == pytest.approx(10.0)


def test_cartea_params_validate() -> None:
    with pytest.raises(ValueError):
        CarteaSkewParams(beta=-0.1)
    with pytest.raises(ValueError):
        CarteaSkewParams(beta=1.0, fv_for_alpha="nonsense")


# ================================================================== C5: Target V2


def test_target_v2_ewma_mean_source_uses_memory() -> None:
    params = TargetPositionParams(
        mode="linear", alpha=1.0, mean_source="ewma", ewma_tau=100.0,
    )
    memory = ProductMemory()
    memory.recent_mids.extend([10_000.0] * 50)
    memory.recent_mids.extend([10_020.0] * 10)
    # EWMA with tau=100 on a long constant tail + small spike: ends
    # somewhere between 10000 and 10020, closer to 10020 than to mid of range.
    fake_fv = type("FV", (), {"price": 10_000.0})()
    mean = _resolve_mean(fake_fv, _config(), params, memory=memory)  # type: ignore[arg-type]
    assert 10_000.0 < mean < 10_020.0


def test_target_v2_ewma_helper_on_empty_returns_none() -> None:
    assert _ewma_of_recent_mids([], tau=100.0) is None


def test_target_v2_clip_to_flatten_caps_target() -> None:
    params = TargetPositionParams(
        mode="linear", alpha=100.0, cap=None, clip_to_flatten=True,
    )
    config = _config(position_limit=80, flatten_threshold=0.7)
    cap = _resolve_cap(config, params)
    assert cap == 56  # = floor(0.7 * 80)


def test_target_v2_sigma_ref_scales_effective_alpha() -> None:
    # High sigma_ref damps the effective pull.
    strat_dampened = AshTargetPositionStrategy(
        FairValueEngine(), SignalEngine(),
        TargetPositionParams(
            mode="linear", alpha=10.0, sigma_ref=5.0,
            mean_source="anchor", cap=80,
        ),
    )
    strat_full = AshTargetPositionStrategy(
        FairValueEngine(), SignalEngine(),
        TargetPositionParams(
            mode="linear", alpha=10.0, sigma_ref=1.0,
            mean_source="anchor", cap=80,
        ),
    )
    # Force a residual of +3 ticks via mid above anchor.
    snap = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=10_001, volume=10),),
        asks=(BookLevel(price=10_005, volume=10),),
    )  # mid = 10003, anchor = 10000, residual = +3
    ctx = StrategyContext("ASH_COATED_OSMIUM", snap, ProductMemory(), _config())
    i_dampened = strat_dampened.generate_intent(ctx)
    i_full = strat_full.generate_intent(ctx)
    # Full-alpha target = -10 * 3 = -30 (capped).
    # Dampened effective_alpha = 10/5 = 2 → target = -6.
    assert i_dampened.metadata["target_position"] == -6
    assert i_full.metadata["target_position"] == -30


def test_target_v2_defaults_reproduce_phase10_behavior() -> None:
    # sigma_ref=1.0 and clip_to_flatten=False → identical to Phase-10.
    p10 = TargetPositionParams(mode="linear", alpha=3.0, cap=30)
    assert p10.sigma_ref == 1.0
    assert p10.clip_to_flatten is False
    assert p10.mean_source == "anchor"

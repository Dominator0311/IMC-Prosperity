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


# ---- Phase 1: Limit-80 production config helpers ----


def _emeralds_80() -> ProductConfig:
    """EMERALDS production config: limit=80, skew=8.0, flatten=0.75."""
    return ProductConfig(
        position_limit=80,
        strategy_name="market_making",
        fair_value_method="anchor",
        anchor_price=10_000.0,
        taker_edge=1.0,
        maker_edge=2.0,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=8.0,
        flatten_threshold=0.75,
    )


def _tomatoes_80() -> ProductConfig:
    """TOMATOES signal-test config: limit=80, skew=12.0, flatten=0.70.

    Uses ``mid`` as the fair_value_method because SignalEngine does not
    read this field (it receives a FairValueEstimate directly).  This
    helper tests signal/skew/flatten behavior, not FV resolution.
    """
    return ProductConfig(
        position_limit=80,
        strategy_name="market_making",
        fair_value_method="mid",
        taker_edge=1.0,
        maker_edge=1.0,
        quote_size=4,
        max_aggressive_size=8,
        inventory_skew=12.0,
        flatten_threshold=0.70,
    )


# ---- Phase 1: EMERALDS long position tests (limit=80) ----


@pytest.mark.unit
@pytest.mark.parametrize("position", [10, 20, 40, 56])
def test_emeralds_80_long_skew_direction(position: int) -> None:
    """Long positions: buy_below decreases, sell_above decreases (skew > 0)."""
    engine = SignalEngine()
    neutral = engine.build_market_making_intent("P", _snapshot(0), _fair(), _emeralds_80())
    intent = engine.build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "hybrid"
    assert intent.buy_below is not None and neutral.buy_below is not None
    assert intent.sell_above is not None and neutral.sell_above is not None
    assert intent.buy_below < neutral.buy_below
    assert intent.sell_above < neutral.sell_above
    assert intent.quote is not None
    assert intent.quote.bid_size > 0 and intent.quote.ask_size > 0


@pytest.mark.unit
def test_emeralds_80_position_56_does_not_flatten() -> None:
    """Position 56/80 = 0.70 < 0.75 flatten threshold."""
    engine = SignalEngine()
    intent = engine.build_market_making_intent("P", _snapshot(56), _fair(), _emeralds_80())
    assert intent.mode == "hybrid"
    assert intent.buy_below is not None


@pytest.mark.unit
@pytest.mark.parametrize("position", [60, 70, 78])
def test_emeralds_80_long_flattening(position: int) -> None:
    """At position >= 60 (0.75*80), buy side disabled, ask pulled to FV."""
    engine = SignalEngine()
    intent = engine.build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "recovery"
    assert intent.buy_below is None
    assert intent.quote is not None
    assert intent.quote.bid_size == 0
    assert intent.quote.bid_price is None
    assert intent.quote.ask_size > 0
    assert intent.quote.ask_price is not None
    assert intent.quote.ask_price <= 10_000


# ---- Phase 1: EMERALDS short position tests ----


@pytest.mark.unit
@pytest.mark.parametrize("position", [-10, -20, -40, -56])
def test_emeralds_80_short_skew_reverses(position: int) -> None:
    """Short positions: negative skew moves buy/sell thresholds UP."""
    engine = SignalEngine()
    neutral = engine.build_market_making_intent("P", _snapshot(0), _fair(), _emeralds_80())
    intent = engine.build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "hybrid"
    assert intent.buy_below is not None and neutral.buy_below is not None
    assert intent.sell_above is not None and neutral.sell_above is not None
    assert intent.buy_below > neutral.buy_below
    assert intent.sell_above > neutral.sell_above


@pytest.mark.unit
@pytest.mark.parametrize("position", [-60, -70, -78])
def test_emeralds_80_short_flattening(position: int) -> None:
    """At position <= -60, sell side disabled, bid pulled to FV."""
    engine = SignalEngine()
    intent = engine.build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "recovery"
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size == 0
    assert intent.quote.ask_price is None
    assert intent.quote.bid_size > 0
    assert intent.quote.bid_price is not None
    assert intent.quote.bid_price >= 10_000


# ---- Phase 1: Symmetry tests ----


@pytest.mark.unit
@pytest.mark.parametrize("pos", [10, 20, 40, 56, 60, 70, 78])
def test_emeralds_80_long_short_symmetry(pos: int) -> None:
    """Long +N and short -N produce mirror-image intents."""
    engine = SignalEngine()
    long_i = engine.build_market_making_intent("P", _snapshot(pos), _fair(), _emeralds_80())
    short_i = engine.build_market_making_intent("P", _snapshot(-pos), _fair(), _emeralds_80())

    assert long_i.mode == short_i.mode

    if long_i.mode == "recovery":
        assert long_i.buy_below is None and short_i.sell_above is None
        assert long_i.quote.ask_price is not None and short_i.quote.bid_price is not None
        ask_dist = 10_000 - long_i.quote.ask_price
        bid_dist = short_i.quote.bid_price - 10_000
        assert abs(ask_dist - bid_dist) <= 1
    else:
        assert long_i.buy_below is not None and short_i.buy_below is not None
        assert long_i.sell_above is not None and short_i.sell_above is not None
        long_buy_dist = 10_000.0 - long_i.buy_below
        short_sell_dist = short_i.sell_above - 10_000.0
        assert abs(long_buy_dist - short_sell_dist) < 0.01


# ---- Phase 1: TOMATOES tests ----


@pytest.mark.unit
def test_tomatoes_80_flatten_triggers_at_56() -> None:
    """TOMATOES: flatten at 0.70 * 80 = 56."""
    engine = SignalEngine()
    below = engine.build_market_making_intent("P", _snapshot(55), _fair(), _tomatoes_80())
    assert below.mode == "hybrid"
    at_thresh = engine.build_market_making_intent("P", _snapshot(56), _fair(), _tomatoes_80())
    assert at_thresh.mode == "recovery"
    assert at_thresh.buy_below is None
    assert at_thresh.quote.bid_size == 0


@pytest.mark.unit
def test_tomatoes_80_short_flatten_triggers_at_minus_56() -> None:
    engine = SignalEngine()
    below = engine.build_market_making_intent("P", _snapshot(-55), _fair(), _tomatoes_80())
    assert below.mode == "hybrid"
    at_thresh = engine.build_market_making_intent("P", _snapshot(-56), _fair(), _tomatoes_80())
    assert at_thresh.mode == "recovery"
    assert at_thresh.sell_above is None
    assert at_thresh.quote.ask_size == 0


@pytest.mark.unit
@pytest.mark.parametrize("pos", [10, 40, 56, 70, 78])
def test_tomatoes_80_long_short_symmetry(pos: int) -> None:
    engine = SignalEngine()
    long_i = engine.build_market_making_intent("P", _snapshot(pos), _fair(), _tomatoes_80())
    short_i = engine.build_market_making_intent("P", _snapshot(-pos), _fair(), _tomatoes_80())
    assert long_i.mode == short_i.mode


# ---- Phase 1.5: Full pipeline stress tests ----


_STRESS_POSITIONS = [-78, -70, -56, -40, -20, -10, 0, 10, 20, 40, 56, 70, 78]


@pytest.mark.unit
@pytest.mark.parametrize("position", _STRESS_POSITIONS)
def test_emeralds_80_full_pipeline_legality(position: int) -> None:
    """Full pipeline at every stress position produces legal order set."""
    from src.core.execution import ExecutionEngine
    from src.core.risk import RiskManager

    config = _emeralds_80()
    snap = _snapshot(position)
    fv = _fair()

    intent = SignalEngine().build_market_making_intent("P", snap, fv, config)
    orders = ExecutionEngine().generate_orders(snap, intent, config)
    clipped = RiskManager().clip_orders("P", orders, position, config.position_limit)

    total_buy = sum(o.quantity for o in clipped if o.quantity > 0)
    total_sell = sum(-o.quantity for o in clipped if o.quantity < 0)
    assert total_buy <= config.position_limit - position
    assert total_sell <= config.position_limit + position


@pytest.mark.unit
def test_emeralds_80_skew_monotonicity() -> None:
    """Buy/sell thresholds decrease monotonically as long position increases."""
    engine = SignalEngine()
    config = _emeralds_80()
    prev_buy: float | None = None
    prev_sell: float | None = None

    for pos in range(0, 60):  # non-flattening range
        intent = engine.build_market_making_intent("P", _snapshot(pos), _fair(), config)
        assert intent.buy_below is not None
        assert intent.sell_above is not None
        if prev_buy is not None:
            assert intent.buy_below <= prev_buy
        if prev_sell is not None:
            assert intent.sell_above <= prev_sell
        prev_buy = intent.buy_below
        prev_sell = intent.sell_above


@pytest.mark.unit
def test_emeralds_80_no_dead_zone() -> None:
    """No gap between highest non-flattening position and flatten threshold."""
    engine = SignalEngine()
    config = _emeralds_80()

    # Position 59: last non-flattening (59/80 = 0.7375 < 0.75)
    intent_59 = engine.build_market_making_intent("P", _snapshot(59), _fair(), config)
    assert intent_59.mode == "hybrid"
    neutral = engine.build_market_making_intent("P", _snapshot(0), _fair(), config)
    assert intent_59.buy_below is not None and neutral.buy_below is not None
    # Skew at 59: 59/80 * 8.0 = 5.9 ticks — must be material
    assert neutral.buy_below - intent_59.buy_below > 5.0

    # Position 60: recovery kicks in immediately
    intent_60 = engine.build_market_making_intent("P", _snapshot(60), _fair(), config)
    assert intent_60.mode == "recovery"
    assert intent_60.buy_below is None


@pytest.mark.unit
@pytest.mark.parametrize("position", [60, 70, 78])
def test_emeralds_80_recovery_unwind_aggressive_long(position: int) -> None:
    """Long recovery: ask at or inside fair value (actively seeking to sell)."""
    intent = SignalEngine().build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "recovery"
    assert intent.quote.ask_price is not None
    assert intent.quote.ask_price <= _fair().price


@pytest.mark.unit
@pytest.mark.parametrize("position", [-60, -70, -78])
def test_emeralds_80_recovery_unwind_aggressive_short(position: int) -> None:
    """Short recovery: bid at or above fair value (actively seeking to buy)."""
    intent = SignalEngine().build_market_making_intent(
        "P", _snapshot(position), _fair(), _emeralds_80()
    )
    assert intent.mode == "recovery"
    assert intent.quote.bid_price is not None
    assert intent.quote.bid_price >= _fair().price


# ---- Phase-9 fastsearch knob behavior ----
#
# Build snapshots at arbitrary timestamps so the early-window branch can
# fire. The base config uses ``taker_edge=1.0`` and
# ``position_limit=20`` from ``_config()``.


def _snapshot_at(position: int, timestamp: int) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="P",
        timestamp=timestamp,
        bids=(BookLevel(9992, 15),),
        asks=(BookLevel(10008, 15),),
        position=position,
    )


def _fast_config(**extras) -> ProductConfig:
    kwargs = dict(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="anchor",
        anchor_price=10_000.0,
        taker_edge=1.0,
        maker_edge=2.0,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=2.0,
        flatten_threshold=0.75,
    )
    kwargs.update(extras)
    return ProductConfig(**kwargs)


@pytest.mark.unit
def test_phase9_per_side_taker_edge_asymmetry() -> None:
    """Family 5: split buy/sell taker edges applies full-day."""
    engine = SignalEngine()
    config = _fast_config(taker_edge_buy=0.5, taker_edge_sell=2.5)
    intent = engine.build_market_making_intent(
        "P", _snapshot_at(0, 500_000), _fair(), config
    )
    # buy_below = fair - 0.5 - 0 = 9999.5
    # sell_above = fair + 2.5 - 0 = 10002.5
    assert intent.buy_below == pytest.approx(9_999.5)
    assert intent.sell_above == pytest.approx(10_002.5)


@pytest.mark.unit
def test_phase9_early_window_switches_sell_edge_only() -> None:
    """Family 1: early_taker_edge_sell bites only before early_window."""
    engine = SignalEngine()
    config = _fast_config(early_window=25_000, early_taker_edge_sell=3.0)
    early = engine.build_market_making_intent("P", _snapshot_at(0, 5_000), _fair(), config)
    late = engine.build_market_making_intent("P", _snapshot_at(0, 30_000), _fair(), config)
    # Early: sell edge widened to 3.0; late: back to 1.0.
    assert early.sell_above == pytest.approx(10_003.0)
    assert late.sell_above == pytest.approx(10_001.0)
    # Buy edge unchanged in both.
    assert early.buy_below == pytest.approx(9_999.0)
    assert late.buy_below == pytest.approx(9_999.0)
    assert early.metadata["in_early_window"] is True
    assert late.metadata["in_early_window"] is False


@pytest.mark.unit
def test_phase9_early_short_cap_disables_sell_intent() -> None:
    """Family 2: once position <= cap in early window, sell is killed."""
    engine = SignalEngine()
    config = _fast_config(early_window=25_000, early_short_cap=-4)
    hit_cap = engine.build_market_making_intent(
        "P", _snapshot_at(-4, 5_000), _fair(), config
    )
    assert hit_cap.sell_above is None
    assert hit_cap.quote.ask_size == 0
    assert hit_cap.quote.ask_price is None
    assert hit_cap.mode == "recovery"
    # Still alive on the buy side (so we can recover toward flat).
    assert hit_cap.quote.bid_size > 0


@pytest.mark.unit
def test_phase9_early_short_cap_does_not_bite_after_window() -> None:
    engine = SignalEngine()
    config = _fast_config(early_window=25_000, early_short_cap=-4)
    late = engine.build_market_making_intent(
        "P", _snapshot_at(-4, 30_000), _fair(), config
    )
    assert late.sell_above is not None  # cap is off once ts >= window
    assert late.quote.ask_size > 0


@pytest.mark.unit
def test_phase9_early_short_skew_mult_amplifies_recovery() -> None:
    """Family 4: while short in early window, skew magnitude is boosted."""
    engine = SignalEngine()
    plain = _fast_config()  # mult = 1.0
    boosted = _fast_config(early_window=25_000, early_short_skew_mult=2.0)
    # Short by 5 (position_ratio = -0.25), pre-flatten.
    plain_intent = engine.build_market_making_intent(
        "P", _snapshot_at(-5, 5_000), _fair(), plain
    )
    boosted_intent = engine.build_market_making_intent(
        "P", _snapshot_at(-5, 5_000), _fair(), boosted
    )
    # The boosted intent has a MORE negative skew (short → skew < 0),
    # which shifts both taker thresholds UP by a larger amount.
    assert plain_intent.buy_below is not None and boosted_intent.buy_below is not None
    assert plain_intent.sell_above is not None and boosted_intent.sell_above is not None
    assert boosted_intent.buy_below > plain_intent.buy_below
    assert boosted_intent.sell_above > plain_intent.sell_above


@pytest.mark.unit
def test_phase9_early_short_flatten_triggers_recovery_sooner() -> None:
    """Family 4: stricter short-side flatten in early window forces recovery."""
    engine = SignalEngine()
    config = _fast_config(
        flatten_threshold=0.9,          # normal flatten would *not* fire at -12 / 20
        early_window=25_000,
        early_short_flatten=0.5,        # but early short flatten does (12/20 = 0.6 >= 0.5)
    )
    intent = engine.build_market_making_intent(
        "P", _snapshot_at(-12, 5_000), _fair(), config
    )
    assert intent.mode == "recovery"
    assert intent.sell_above is None
    assert intent.quote.ask_size == 0


@pytest.mark.unit
def test_phase9_all_knobs_at_defaults_matches_preexisting_signal() -> None:
    """Neutral Phase-9 knobs must leave output identical to the base config."""
    engine = SignalEngine()
    before = _config()  # legacy helper
    after = _fast_config()
    s = _snapshot(0)
    legacy = engine.build_market_making_intent("P", s, _fair(), before)
    extended = engine.build_market_making_intent("P", s, _fair(), after)
    assert legacy.buy_below == extended.buy_below
    assert legacy.sell_above == extended.sell_above
    assert legacy.mode == extended.mode
    assert legacy.quote.bid_price == extended.quote.bid_price
    assert legacy.quote.ask_price == extended.quote.ask_price

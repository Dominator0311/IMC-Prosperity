"""Tests for the PEPPER core-long + residual-overlay research strategy.

The strategy lives in ``src/strategies/pepper_core_long.py``. It is
**research-only** — never added to ``STRATEGY_REGISTRY`` and never
referenced by any shipped submission bundle. These tests cover:

1. ``compute_target_position``: residual → target mapping, including
   asymmetry, dead zones, floor/ceiling clipping, and degenerate inputs.
2. ``CoreLongParams``: validation at construction time.
3. ``PepperCoreLongStrategy.generate_intent``: intent shape at
   below-fair / above-fair / at-fair residuals, step-rate-limited
   adjustment, exec-style gating (maker / hybrid / taker), and that
   the strategy never emits orders that would push past floor/ceiling.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    BookLevel,
    FairValueEstimate,
    NormalizedSnapshot,
    ProductMemory,
)
from src.strategies.base import StrategyContext
from src.strategies.pepper_core_long import (
    CoreLongParams,
    PepperCoreLongStrategy,
    compute_target_position,
)


PEPPER = "INTARIAN_PEPPER_ROOT"


# --------------------------------------------------------------------------- #
# compute_target_position                                                     #
# --------------------------------------------------------------------------- #


def test_compute_target_zero_residual_returns_base_long() -> None:
    target = compute_target_position(
        residual=0.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=1.0,
        floor=0,
        ceiling=80,
    )
    assert target == 30


def test_compute_target_small_residual_inside_dead_zone_is_base_long() -> None:
    # Inside [-add_thresh, +trim_thresh] — no overlay.
    for r in (-2.9, -1.0, 0.5, 2.0, 4.9):
        assert (
            compute_target_position(
                residual=r,
                base_long=30,
                add_thresh=3.0,
                trim_thresh=5.0,
                add_gain=2.0,
                trim_gain=1.0,
                floor=0,
                ceiling=80,
            )
            == 30
        )


def test_compute_target_below_fair_adds_above_base_long() -> None:
    # r = -5 → excess = 5 - 3 = 2, overlay = +2 * 2 = +4 → 30 + 4 = 34
    target = compute_target_position(
        residual=-5.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=1.0,
        floor=0,
        ceiling=80,
    )
    assert target == 34


def test_compute_target_above_fair_trims_below_base_long() -> None:
    # r = +8 → excess = 8 - 5 = 3, overlay = -1 * 3 = -3 → 30 - 3 = 27
    target = compute_target_position(
        residual=8.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=1.0,
        floor=0,
        ceiling=80,
    )
    assert target == 27


def test_compute_target_floor_clips_large_positive_residual() -> None:
    # r = +100 → huge trim → target below floor → clipped to floor
    target = compute_target_position(
        residual=100.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=1.0,
        floor=10,
        ceiling=80,
    )
    assert target == 10


def test_compute_target_ceiling_clips_large_negative_residual() -> None:
    # r = -100 → huge add → target above ceiling → clipped to ceiling
    target = compute_target_position(
        residual=-100.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=1.0,
        floor=10,
        ceiling=60,
    )
    assert target == 60


def test_compute_target_floor_never_crosses_below_zero_when_set_zero() -> None:
    # floor=0 means strategy is allowed to go flat but not short.
    target = compute_target_position(
        residual=50.0,
        base_long=5,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=1.0,
        trim_gain=2.0,
        floor=0,
        ceiling=80,
    )
    assert target == 0


def test_compute_target_asymmetric_gains() -> None:
    # Trim side should be weaker than add side for the same excess.
    add_target = compute_target_position(
        residual=-10.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=3.0,
        add_gain=2.0,
        trim_gain=0.5,
        floor=0,
        ceiling=80,
    )
    trim_target = compute_target_position(
        residual=+10.0,
        base_long=30,
        add_thresh=3.0,
        trim_thresh=3.0,
        add_gain=2.0,
        trim_gain=0.5,
        floor=0,
        ceiling=80,
    )
    add_delta = add_target - 30  # + direction
    trim_delta = 30 - trim_target  # magnitude of trim
    assert add_delta > trim_delta


# --------------------------------------------------------------------------- #
# CoreLongParams validation                                                   #
# --------------------------------------------------------------------------- #


def test_params_reject_negative_base_long() -> None:
    with pytest.raises(ValueError, match="base_long"):
        CoreLongParams(base_long=-1)


def test_params_reject_negative_add_thresh() -> None:
    with pytest.raises(ValueError, match="add_thresh"):
        CoreLongParams(base_long=30, add_thresh=-0.1)


def test_params_reject_negative_trim_thresh() -> None:
    with pytest.raises(ValueError, match="trim_thresh"):
        CoreLongParams(base_long=30, trim_thresh=-0.5)


def test_params_reject_floor_above_ceiling() -> None:
    with pytest.raises(ValueError, match="floor"):
        CoreLongParams(base_long=30, floor=50, ceiling=20)


def test_params_reject_negative_floor() -> None:
    with pytest.raises(ValueError, match="floor"):
        CoreLongParams(base_long=30, floor=-1)


def test_params_reject_step_not_positive() -> None:
    with pytest.raises(ValueError, match="step"):
        CoreLongParams(base_long=30, step=0)


def test_params_reject_unknown_exec_style() -> None:
    with pytest.raises(ValueError, match="exec_style"):
        CoreLongParams(base_long=30, exec_style="bogus")


def test_params_accept_default_construction() -> None:
    # Defaults should form a valid spec.
    params = CoreLongParams(base_long=30)
    assert params.base_long == 30
    assert params.floor == 0
    assert params.ceiling == 80
    assert params.step > 0
    assert params.exec_style in ("maker", "hybrid", "taker")


# --------------------------------------------------------------------------- #
# PepperCoreLongStrategy.generate_intent                                      #
# --------------------------------------------------------------------------- #


def _config(position_limit: int = 80) -> ProductConfig:
    return ProductConfig(
        position_limit=position_limit,
        strategy_name="market_making",
        fair_value_method="linear_drift",
        fair_value_fallbacks=("mid",),
        taker_edge=1.0,
        maker_edge=1.0,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=2.0,
        flatten_threshold=0.7,
        history_length=32,
    )


def _snapshot(
    *,
    mid: float,
    position: int,
    timestamp: int = 1000,
    spread: int = 12,
    best_bid_volume: int = 20,
    best_ask_volume: int = 20,
) -> NormalizedSnapshot:
    best_bid_price = int(mid - spread / 2)
    best_ask_price = int(mid + spread / 2)
    return NormalizedSnapshot(
        product=PEPPER,
        timestamp=timestamp,
        bids=(
            BookLevel(best_bid_price, best_bid_volume),
            BookLevel(best_bid_price - 3, 30),
        ),
        asks=(
            BookLevel(best_ask_price, best_ask_volume),
            BookLevel(best_ask_price + 3, 30),
        ),
        position=position,
    )


class _FixedFairValueEngine:
    """Returns a fixed fair value regardless of snapshot / memory."""

    def __init__(self, price: float) -> None:
        self._price = price

    def estimate(
        self, product, snapshot, memory, config
    ) -> FairValueEstimate:  # noqa: ARG002
        return FairValueEstimate(
            price=self._price,
            method="linear_drift",
            confidence=0.9,
            components=MappingProxyType({"slope": 0.001}),
        )


def _make_strategy(
    params: CoreLongParams, fair_value: float = 12_000.0
) -> PepperCoreLongStrategy:
    fve = _FixedFairValueEngine(fair_value)
    sig = SignalEngine()
    # Cast is safe at runtime; the strategy only calls `.estimate(...)`.
    return PepperCoreLongStrategy(fve, sig, params)  # type: ignore[arg-type]


def _ctx(
    snapshot: NormalizedSnapshot,
    config: ProductConfig,
    *,
    recent_mids: list[float] | None = None,
) -> StrategyContext:
    mids = recent_mids if recent_mids is not None else [float(snapshot.mid or 12_000.0)]
    memory = ProductMemory(recent_mids=mids)
    return StrategyContext(
        product=PEPPER, snapshot=snapshot, memory=memory, config=config
    )


def test_intent_at_fair_no_position_quotes_toward_base_long() -> None:
    params = CoreLongParams(base_long=30, step=8, exec_style="hybrid")
    strategy = _make_strategy(params)
    snap = _snapshot(mid=12_000, position=0)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    # Want to accumulate toward base_long = 30; step-limited to 8.
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.bid_size <= 8
    assert intent.quote.ask_size == 0
    # Rationale identifies the strategy.
    assert "core_long" in intent.rationale.lower()


def test_intent_at_base_long_with_small_residual_no_order_pressure() -> None:
    params = CoreLongParams(
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        step=8,
        exec_style="hybrid",
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # Residual = 0 (mid == fair), position == base_long.
    snap = _snapshot(mid=12_000, position=30)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    # At target — neither side should be urgent. Maker quotes may be
    # present on both sides to harvest residual oscillation, but taker
    # thresholds should be None (no crossing).
    assert intent.buy_below is None
    assert intent.sell_above is None


def test_intent_deep_below_fair_opens_taker_buy_and_scales_up() -> None:
    # Large negative residual → target above base_long → need to buy.
    params = CoreLongParams(
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=4.0,
        trim_gain=1.0,
        step=10,
        exec_style="hybrid",
        hybrid_threshold=2.0,
    )
    strategy = _make_strategy(params, fair_value=12_010.0)
    # mid = fair - 8  →  residual = -8, |residual| >= hybrid_threshold
    snap = _snapshot(mid=12_002, position=30)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    # Hybrid + |residual| >= threshold → taker buy intent set.
    assert intent.buy_below is not None
    # Never emit a sell if we need to buy.
    assert intent.sell_above is None
    # Maker bid is also present for the same step-limited size.
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.ask_size == 0


def test_intent_deep_above_fair_opens_taker_sell_but_respects_floor() -> None:
    params = CoreLongParams(
        base_long=30,
        add_thresh=3.0,
        trim_thresh=5.0,
        add_gain=2.0,
        trim_gain=2.0,
        floor=20,
        step=8,
        exec_style="hybrid",
        hybrid_threshold=2.0,
    )
    # price = fair + 20 → huge positive residual → raw target = 30 - 2*(20-5)
    # = 30 - 30 = 0 → clipped to floor = 20. Position is 30, so sell 10.
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_020, position=30)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.sell_above is not None
    assert intent.buy_below is None
    # Step-limited to 8; effective gap is capped.
    assert intent.quote is not None
    assert intent.quote.ask_size > 0
    assert intent.quote.ask_size <= 8


def test_intent_at_floor_never_adds_more_sells() -> None:
    # Position already at floor; even a huge positive residual must not
    # emit any sell orders (we would cross below the floor).
    params = CoreLongParams(
        base_long=30,
        floor=20,
        trim_thresh=5.0,
        trim_gain=2.0,
        step=8,
        exec_style="hybrid",
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_050, position=20)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size == 0


def test_intent_at_ceiling_never_adds_more_buys() -> None:
    params = CoreLongParams(
        base_long=30,
        ceiling=60,
        add_thresh=3.0,
        add_gain=5.0,
        step=8,
        exec_style="hybrid",
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # price = fair - 50 → huge negative residual → target would be >> 60 →
    # clipped to ceiling=60. Position = 60.
    snap = _snapshot(mid=11_950, position=60)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.buy_below is None
    assert intent.quote is not None
    assert intent.quote.bid_size == 0


def test_intent_maker_only_exec_style_never_sets_taker_thresholds() -> None:
    params = CoreLongParams(
        base_long=30, step=8, exec_style="maker", add_thresh=3.0, add_gain=5.0
    )
    strategy = _make_strategy(params, fair_value=12_010.0)
    snap = _snapshot(mid=12_002, position=20)  # residual = -8, big deviation
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.buy_below is None
    assert intent.sell_above is None
    # But maker bid is present because we want more long.
    assert intent.quote is not None
    assert intent.quote.bid_size > 0


def test_intent_taker_only_exec_style_never_places_passive_quote() -> None:
    params = CoreLongParams(
        base_long=30, step=8, exec_style="taker", add_thresh=3.0, add_gain=5.0
    )
    strategy = _make_strategy(params, fair_value=12_010.0)
    snap = _snapshot(mid=12_002, position=20)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.buy_below is not None
    # Maker bid/ask should be None or size 0.
    assert intent.quote is not None
    assert intent.quote.bid_size == 0
    assert intent.quote.ask_size == 0


def test_intent_step_rate_limits_quote_size() -> None:
    # gap = 30 - 0 = 30 units; step = 4 → quote should be <= 4.
    params = CoreLongParams(base_long=30, step=4, exec_style="hybrid")
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_000, position=0)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.quote is not None
    assert intent.quote.bid_size <= 4


def test_intent_metadata_exposes_core_long_diagnostics() -> None:
    params = CoreLongParams(base_long=30, step=8, exec_style="hybrid")
    strategy = _make_strategy(params, fair_value=12_010.0)
    snap = _snapshot(mid=12_003, position=15)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    md = dict(intent.metadata)
    assert "residual" in md
    assert "target_position" in md
    assert "position_gap" in md
    assert "base_long" in md
    assert "effective_target" in md  # after step + floor/ceiling


def test_strategy_not_registered_in_live_registry() -> None:
    # Research-only module — must never be auto-registered.
    from src.strategies import STRATEGY_REGISTRY

    assert "pepper_core_long" not in STRATEGY_REGISTRY


# --------------------------------------------------------------------------- #
# v2: opening-acquisition branch                                              #
# --------------------------------------------------------------------------- #


def test_params_reject_negative_open_seed_size() -> None:
    with pytest.raises(ValueError, match="open_seed_size"):
        CoreLongParams(base_long=30, open_seed_size=-1)


def test_params_reject_open_seed_above_ceiling() -> None:
    with pytest.raises(ValueError, match="open_seed_size"):
        CoreLongParams(base_long=30, ceiling=40, open_seed_size=50)


def test_params_reject_negative_open_window() -> None:
    with pytest.raises(ValueError, match="open_window"):
        CoreLongParams(base_long=30, open_seed_size=30, open_window=-1)


def test_params_reject_unknown_open_take_mode() -> None:
    with pytest.raises(ValueError, match="open_take_mode"):
        CoreLongParams(base_long=30, open_take_mode="bogus")


def test_params_reject_guard_target_outside_bounds() -> None:
    with pytest.raises(ValueError, match="guard_target"):
        CoreLongParams(
            base_long=30,
            floor=10,
            ceiling=40,
            guard_window=8,
            guard_negative_slope=0.5,
            guard_target=50,
        )


def test_params_reject_micro_imbalance_threshold_above_one() -> None:
    with pytest.raises(ValueError, match="micro_imbalance_threshold"):
        CoreLongParams(base_long=30, micro_imbalance_threshold=1.1)


def test_params_reject_adaptive_high_slope_below_mid_slope() -> None:
    with pytest.raises(ValueError, match="adaptive_high_slope"):
        CoreLongParams(
            base_long=30,
            adaptive_caps_enabled=True,
            adaptive_mid_slope=0.10,
            adaptive_high_slope=0.05,
            adaptive_low_cap=20,
            adaptive_mid_cap=40,
            adaptive_high_cap=60,
        )


def test_params_reject_unordered_adaptive_caps() -> None:
    with pytest.raises(ValueError, match="adaptive caps"):
        CoreLongParams(
            base_long=30,
            floor=0,
            ceiling=80,
            adaptive_caps_enabled=True,
            guard_window=8,
            adaptive_mid_slope=0.05,
            adaptive_high_slope=0.10,
            adaptive_low_cap=60,
            adaptive_mid_cap=40,
            adaptive_high_cap=80,
        )


def test_params_reject_adaptive_caps_without_guard_window() -> None:
    with pytest.raises(ValueError, match="guard_window"):
        CoreLongParams(
            base_long=30,
            adaptive_caps_enabled=True,
            adaptive_mid_slope=0.05,
            adaptive_high_slope=0.10,
            adaptive_low_cap=20,
            adaptive_mid_cap=40,
            adaptive_high_cap=60,
        )


def test_params_accept_disabled_opening_by_default() -> None:
    params = CoreLongParams(base_long=30)
    assert params.open_seed_size == 0
    assert params.open_window == 0
    # open_no_short is a safety default — True when opening is used.
    assert params.open_no_short is True


def test_intent_opening_forces_taker_buy_at_tick_zero() -> None:
    # seed_size=40 at t=0, even with small residual that would NOT
    # satisfy hybrid_threshold=2.0 → taker buy must still fire.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=40,
        open_window=0,
        exec_style="hybrid",
        hybrid_threshold=2.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # residual = 0.5 (below hybrid_threshold); but opening forces taker.
    snap = _snapshot(mid=12_000, position=0, timestamp=0)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    # Opening taker buy must be set even though |residual| < hybrid_threshold.
    assert intent.buy_below is not None
    # Size is step-limited (step=8 → 8 units this tick).
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    assert intent.quote.bid_size <= 8
    # Opening must never emit a sell intent.
    assert intent.sell_above is None
    assert intent.quote.ask_size == 0
    # Metadata exposes in_opening for downstream diagnostics.
    assert intent.metadata["in_opening"] is True


def test_intent_opening_seed_overrides_overlay_target() -> None:
    # Even with a hugely negative residual that would tell the
    # overlay to push well above base_long, the opening branch pins
    # the target at open_seed_size. Confirms the v1 overlay is
    # overridden, not merely supplemented, during the opening.
    params = CoreLongParams(
        base_long=30,
        add_thresh=1.0,
        add_gain=10.0,  # overlay would say "go to +100" easily
        open_seed_size=40,
        open_window=100,
        ceiling=80,
        step=100,  # step-unclipped so target is the raw target
    )
    strategy = _make_strategy(params, fair_value=12_020.0)
    # Residual = -18, overlay would raw-target = 30 + 10*(18-1) = 200 → clipped to 80.
    snap = _snapshot(mid=12_002, position=0, timestamp=50)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    md = dict(intent.metadata)
    # target_position is the opening seed, NOT the overlay raw target.
    assert md["target_position"] == 40
    assert md["in_opening"] is True


def test_intent_opening_expires_after_window() -> None:
    # At t = open_window + 1 the strategy must revert to the
    # persistent_core + overlay behavior and no longer force taker.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=40,
        open_window=100,
        exec_style="hybrid",
        hybrid_threshold=5.0,  # high threshold so residual=0.5 alone never crosses
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # After the opening window, residual is 0.5 (below threshold) →
    # hybrid should NOT emit a taker buy.
    snap = _snapshot(mid=12_000, position=40, timestamp=101)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    # No taker intent (we're past opening, at base_long+10, residual small).
    assert intent.buy_below is None
    assert intent.sell_above is None
    # Metadata must reflect we are no longer in opening.
    assert intent.metadata["in_opening"] is False


def test_intent_opening_respects_ceiling_clip() -> None:
    # seed_size > position_limit → strategy clips to effective_ceiling.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=60,
        open_window=0,
        ceiling=80,
        step=8,
    )
    config = _config(position_limit=50)  # position_limit < ceiling
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_000, position=0, timestamp=0)
    intent = strategy.generate_intent(_ctx(snap, config))
    # effective_ceiling = min(80, 50) = 50. target_position = min(60, 50) = 50.
    md = dict(intent.metadata)
    assert md["target_position"] == 50
    assert md["ceiling"] == 50


def test_intent_opening_no_short_suppresses_sells_even_with_overlay_trim() -> None:
    # open_no_short=True must block sell quotes during the window
    # even if the bot is already above the seed target. This protects
    # the seed from being trimmed by residual overlay noise.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=20,  # position=30 is already ABOVE the seed
        open_window=500,
        open_no_short=True,
        trim_thresh=1.0,
        trim_gain=5.0,  # overlay would strongly want to trim
        exec_style="hybrid",
        hybrid_threshold=1.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # price above fair → overlay says "trim"; position > seed → gap is negative.
    snap = _snapshot(mid=12_010, position=30, timestamp=100)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    # open_no_short must zero all sells regardless of the internal target.
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.ask_size == 0


def test_intent_opening_allows_sells_when_open_no_short_is_false() -> None:
    # Explicit coverage: open_no_short=False means the seed is a
    # target but the overlay's sell side can still fire during the
    # window. Used as a sanity control, not a recommended config.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=10,
        open_window=500,
        open_no_short=False,
        trim_thresh=1.0,
        trim_gain=2.0,
        exec_style="hybrid",
        hybrid_threshold=1.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # position (30) above seed (10); residual positive; open_no_short off.
    snap = _snapshot(mid=12_010, position=30, timestamp=100)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    # We EXPECT a sell intent now (seed < position → target_position = 10,
    # gap is negative → hybrid with |residual|=10 >> threshold → taker sell).
    assert intent.sell_above is not None


def test_intent_opening_crosses_best_ask_not_just_drift_anchor() -> None:
    # REGRESSION: the first v2 run showed the opening seed producing
    # zero extra fills because the default buy_below=fair-taker_edge
    # sits well below the best ask. Opening must use a wide crossing
    # threshold (take any ask inside the book), matching the pattern
    # used by ``BuyAndHoldStrategy``.
    params = CoreLongParams(
        base_long=50,
        open_seed_size=40,
        open_window=0,
        exec_style="hybrid",
        hybrid_threshold=2.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # Spread=12 → best_ask ~ fair+6. A tight taker_edge=1 would put
    # buy_below at fair-1=11_999 — below best_ask=12_006 → no fill.
    # Opening must override this and emit a buy_below ABOVE best_ask.
    snap = _snapshot(mid=12_000, position=0, timestamp=0, spread=12)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    assert intent.buy_below is not None
    assert snap.best_ask is not None
    assert intent.buy_below > snap.best_ask.price, (
        f"opening buy_below ({intent.buy_below}) must exceed best_ask "
        f"({snap.best_ask.price}) to force a cross"
    )


def test_intent_opening_level1_only_uses_best_ask_threshold() -> None:
    params = CoreLongParams(
        base_long=50,
        open_seed_size=40,
        open_window=0,
        open_take_mode="level1_only",
        exec_style="hybrid",
        hybrid_threshold=2.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_000, position=0, timestamp=0, spread=12)
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert snap.best_ask is not None
    assert intent.buy_below == float(snap.best_ask.price)


def test_intent_non_opening_uses_drift_anchored_crossing_threshold() -> None:
    # Inverse of the regression above: outside the opening window we
    # keep the v1 drift-anchored crossing threshold (fair - taker_edge).
    # This preserves the v1 behavior for non-opening taker intents.
    params = CoreLongParams(
        base_long=50,
        open_seed_size=40,
        open_window=100,
        exec_style="hybrid",
        hybrid_threshold=2.0,
        step=8,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # mid = fair - 5, residual = -5 → hybrid taker eligible
    # (|residual|=5 > threshold=2.0). Post-opening: buy_below = fair - taker_edge.
    snap = _snapshot(mid=11_995, position=30, timestamp=5_000, spread=12)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    # config.taker_edge = 1.0 → buy_below = 12_000 - 1 = 11_999
    assert intent.buy_below is not None
    assert intent.buy_below < 12_000, (
        f"non-opening buy_below ({intent.buy_below}) must use drift-anchored "
        f"threshold (below fair_price), not the opening take-any-ask value"
    )


def test_intent_opening_disabled_by_zero_seed_size_backward_compatible() -> None:
    # open_seed_size=0 (default) must behave exactly like the v1
    # strategy — this preserves backward compatibility with existing
    # v1 test cases and the v1 runner.
    params = CoreLongParams(
        base_long=30,
        open_seed_size=0,  # disabled
        step=8,
        exec_style="hybrid",
        hybrid_threshold=5.0,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    # At t=0 with residual below hybrid_threshold: no taker buy (v1 behavior).
    snap = _snapshot(mid=12_000, position=0, timestamp=0)
    intent = strategy.generate_intent(_ctx(snap, _config()))
    # No taker buy because seed is disabled AND |residual|=0 < threshold.
    assert intent.buy_below is None
    assert intent.metadata["in_opening"] is False


def test_negative_drift_guard_clamps_target_even_when_residual_says_buy() -> None:
    params = CoreLongParams(
        base_long=80,
        ceiling=80,
        floor=0,
        step=8,
        exec_style="hybrid",
        add_thresh=3.0,
        add_gain=5.0,
        guard_window=8,
        guard_negative_slope=1.0,
        guard_r2_min=0.95,
        guard_target=20,
    )
    strategy = _make_strategy(params, fair_value=12_020.0)
    snap = _snapshot(mid=12_000.0, position=40)
    recent = [
        12_080.0,
        12_070.0,
        12_060.0,
        12_050.0,
        12_040.0,
        12_030.0,
        12_020.0,
        12_010.0,
    ]
    intent = strategy.generate_intent(_ctx(snap, _config(), recent_mids=recent))

    assert intent.buy_below is None
    assert intent.sell_above is not None
    assert intent.quote is not None
    assert intent.quote.ask_size > 0
    md = dict(intent.metadata)
    assert md["guard_active"] is True
    assert md["target_position"] == 20


def test_micro_bias_adds_inventory_when_residual_and_imbalance_agree() -> None:
    params = CoreLongParams(
        base_long=30,
        step=8,
        exec_style="maker",
        add_thresh=3.0,
        trim_thresh=5.0,
        micro_residual_threshold=1.5,
        micro_imbalance_threshold=0.2,
        micro_add_size=4,
    )
    strategy = _make_strategy(params, fair_value=12_002.0)
    snap = _snapshot(
        mid=12_000.0,
        position=30,
        best_bid_volume=30,
        best_ask_volume=10,
    )
    intent = strategy.generate_intent(_ctx(snap, _config()))

    assert intent.buy_below is None
    assert intent.sell_above is None
    assert intent.quote is not None
    assert intent.quote.bid_size > 0
    md = dict(intent.metadata)
    assert md["micro_bias"] == 4
    assert md["imbalance"] == 0.5
    assert md["target_position"] == 34


def test_adaptive_caps_reduce_long_target_when_drift_is_weak() -> None:
    params = CoreLongParams(
        base_long=80,
        ceiling=80,
        floor=0,
        step=100,
        exec_style="maker",
        guard_window=8,
        adaptive_caps_enabled=True,
        adaptive_r2_min=0.9,
        adaptive_mid_slope=0.05,
        adaptive_high_slope=0.10,
        adaptive_low_cap=40,
        adaptive_mid_cap=60,
        adaptive_high_cap=80,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_000.0, position=0)
    recent = [
        11_999.76,
        11_999.79,
        11_999.82,
        11_999.85,
        11_999.88,
        11_999.91,
        11_999.94,
        11_999.97,
    ]
    intent = strategy.generate_intent(_ctx(snap, _config(), recent_mids=recent))

    md = dict(intent.metadata)
    assert md["adaptive_caps_enabled"] is True
    assert md["adaptive_band"] == "low"
    assert md["adaptive_ceiling"] == 40
    assert md["ceiling"] == 40
    assert md["target_position"] == 40
    assert intent.quote is not None
    assert intent.quote.bid_size == 5


def test_adaptive_caps_keep_high_long_when_drift_is_strong() -> None:
    params = CoreLongParams(
        base_long=80,
        ceiling=80,
        floor=0,
        step=100,
        exec_style="maker",
        guard_window=8,
        adaptive_caps_enabled=True,
        adaptive_r2_min=0.9,
        adaptive_mid_slope=0.05,
        adaptive_high_slope=0.10,
        adaptive_low_cap=40,
        adaptive_mid_cap=60,
        adaptive_high_cap=80,
    )
    strategy = _make_strategy(params, fair_value=12_000.0)
    snap = _snapshot(mid=12_000.0, position=0)
    recent = [
        11_999.04,
        11_999.16,
        11_999.28,
        11_999.40,
        11_999.52,
        11_999.64,
        11_999.76,
        11_999.88,
    ]
    intent = strategy.generate_intent(_ctx(snap, _config(), recent_mids=recent))

    md = dict(intent.metadata)
    assert md["adaptive_band"] == "high"
    assert md["adaptive_ceiling"] == 80
    assert md["target_position"] == 80

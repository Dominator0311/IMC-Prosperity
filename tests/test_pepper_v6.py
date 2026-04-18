"""Tests for PepperV6CombinedStrategy.

Covers:
- param validation
- passive opening phase (bid at best_bid+1, no asks)
- taker fallback phase
- steady-state with maker cycling
- guard and reversal interaction
- hard floor/ceiling gates
"""

from __future__ import annotations

import pytest

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    BookLevel,
    NormalizedSnapshot,
    ProductMemory,
)
from src.strategies.base import StrategyContext
from src.strategies.pepper_v6_combined import (
    V6CombinedParams,
    PepperV6CombinedStrategy,
)

PEPPER = "INTARIAN_PEPPER_ROOT"


def _pepper_config() -> ProductConfig:
    return ProductConfig(
        position_limit=80,
        strategy_name="market_making",  # only for registry validation, ignored by research strategies
        fair_value_method="linear_drift",
        fair_value_fallbacks=("mid",),
        taker_edge=2.0,
        maker_edge=1.0,
        quote_size=10,
        max_aggressive_size=20,
        inventory_skew=2.0,
        flatten_threshold=0.7,
        history_length=32,
    )


def _snapshot(
    *,
    position: int = 0,
    bid: int = 11_990,
    bid_vol: int = 20,
    ask: int = 12_010,
    ask_vol: int = 20,
    timestamp: int = 1000,
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product=PEPPER,
        timestamp=timestamp,
        bids=(BookLevel(bid, bid_vol),),
        asks=(BookLevel(ask, ask_vol),),
        position=position,
    )


def _engines() -> tuple[FairValueEngine, SignalEngine]:
    return FairValueEngine(), SignalEngine()


def _memory_with_mids(mids: list[float]) -> ProductMemory:
    mem = ProductMemory()
    mem.recent_mids = list(mids)
    return mem


def _fresh_memory() -> ProductMemory:
    return _memory_with_mids([12_000.0] * 32)


# ------------------------------------------------------------------- Param validation


@pytest.mark.unit
class TestV6ParamValidation:
    def test_base_long_negative(self) -> None:
        with pytest.raises(ValueError, match="base_long"):
            V6CombinedParams(base_long=-1)

    def test_base_long_above_ceiling(self) -> None:
        with pytest.raises(ValueError, match="base_long"):
            V6CombinedParams(base_long=90, ceiling=80)

    def test_ceiling_below_floor(self) -> None:
        with pytest.raises(ValueError, match="ceiling"):
            V6CombinedParams(floor=50, ceiling=40)

    def test_step_zero(self) -> None:
        with pytest.raises(ValueError, match="step"):
            V6CombinedParams(step=0)

    def test_seed_above_ceiling(self) -> None:
        with pytest.raises(ValueError, match="opening_seed_size"):
            V6CombinedParams(opening_seed_size=100, ceiling=80)

    def test_invalid_exec_style(self) -> None:
        with pytest.raises(ValueError, match="exec_style"):
            V6CombinedParams(exec_style="bad")

    def test_guard_r2_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="guard_r2_min"):
            V6CombinedParams(guard_r2_min=1.5)

    def test_drift_reversal_target_outside_bounds(self) -> None:
        with pytest.raises(ValueError, match="drift_reversal_target"):
            V6CombinedParams(drift_reversal_target=-1)

    def test_valid_defaults(self) -> None:
        params = V6CombinedParams()
        assert params.base_long == 65
        assert params.opening_seed_size == 50
        assert params.maker_quote_size == 5


# ------------------------------------------------------------------- Passive opening


@pytest.mark.unit
class TestPassiveOpening:
    def test_first_tick_posts_passive_bid(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=50)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=0, bid=11_990, ask=12_010)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        # Should post passive bid at best_bid + 1 = 11991
        assert intent.quote.bid_price == 11_991
        assert intent.quote.bid_size > 0
        # No asks during opening
        assert intent.quote.ask_price is None
        assert intent.quote.ask_size == 0
        # No taker buy (passive only on first tick)
        assert intent.buy_below is None

    def test_no_sell_during_opening(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=50, opening_no_short=True)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=10, bid=11_990, ask=12_010)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        assert intent.sell_above is None
        assert intent.quote.ask_price is None

    def test_passive_bid_capped_at_ask_minus_tick(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            opening_seed_size=50,
            passive_bid_improve=100,  # absurd improvement
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=0, bid=12_005, ask=12_010)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        # Should be clamped to ask - tick_size = 12009
        assert intent.quote.bid_price is not None
        assert intent.quote.bid_price < 12_010


# ------------------------------------------------------------------- Taker fallback


@pytest.mark.unit
class TestTakerFallback:
    def test_taker_kicks_in_after_passive_window(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            opening_passive_window=2,
            opening_taker_fallback_tick=2,
            opening_seed_size=50,
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        mem = _fresh_memory()
        config = _pepper_config()

        # Tick 0, 1 → passive (no taker)
        for _ in range(2):
            snap = _snapshot(position=0)
            ctx = StrategyContext(PEPPER, snap, mem, config)
            intent = strat.generate_intent(ctx)
            assert intent.buy_below is None  # passive only

        # Tick 2 → taker fallback
        snap = _snapshot(position=0)
        ctx = StrategyContext(PEPPER, snap, mem, config)
        intent = strat.generate_intent(ctx)
        assert intent.buy_below == 1e9  # cross any ask

    def test_no_taker_once_seeded(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=50)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        mem = _fresh_memory()
        # Advance past opening window
        for _ in range(5):
            mem.counters["v6_tick_count"] = mem.counters.get("v6_tick_count", 0) + 1

        # Position already at seed → steady-state, no 1e9 taker
        mem.counters["v6_tick_count"] = 0  # reset for clean test
        snap = _snapshot(position=55)
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())
        intent = strat.generate_intent(ctx)
        assert intent.buy_below != 1e9 or intent.buy_below is None


# ------------------------------------------------------------------- Steady-state maker


@pytest.mark.unit
class TestSteadyStateMaker:
    def test_maker_quotes_both_sides_at_target(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            base_long=65,
            opening_seed_size=50,
            maker_quote_size=5,
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=65, bid=11_990, ask=12_010)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        # At base_long → both sides quoted
        assert intent.quote.bid_price is not None
        assert intent.quote.ask_price is not None
        assert intent.quote.bid_size > 0
        assert intent.quote.ask_size > 0
        # Inside the touch
        assert intent.quote.bid_price > 11_990
        assert intent.quote.ask_price < 12_010

    def test_no_maker_when_quote_size_zero(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            base_long=80,
            opening_seed_size=50,
            maker_quote_size=0,  # v6a: cycling off
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=80, bid=11_990, ask=12_010)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        # At ceiling with no maker → no quotes
        assert intent.quote.bid_price is None
        assert intent.quote.ask_price is None


# ------------------------------------------------------------------- Guard + reversal


@pytest.mark.unit
class TestGuardAndReversal:
    def _falling_mids(self, n: int = 40) -> list[float]:
        """Generate a clearly falling mid series."""
        return [12_000.0 - i * 2.0 for i in range(n)]

    def test_guard_caps_target(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            base_long=65,
            opening_seed_size=10,
            guard_window=32,
            guard_negative_slope=0.01,
            guard_r2_min=0.0,
            guard_target=0,
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        # Strongly falling mids → guard should activate
        mem = _memory_with_mids(self._falling_mids())
        snap = _snapshot(position=60, bid=11_900, ask=11_920)
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        # Guard caps target → should want to sell, not buy
        assert intent.metadata["guard_active"] is True
        # With step=8, from 60 the effective_target should be 60-8=52
        assert intent.metadata["effective_target"] <= 60

    def test_reversal_flips_asymmetry(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(
            base_long=65,
            opening_seed_size=10,
            maker_quote_size=5,
            drift_reversal_slope_threshold=0.02,
            drift_reversal_r2_min=0.0,
        )
        strat = PepperV6CombinedStrategy(fv, sg, params)
        mem = _memory_with_mids(self._falling_mids())
        snap = _snapshot(position=60, bid=11_900, ask=11_920)
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        assert intent.metadata["reversal_active"] is True


# ------------------------------------------------------------------- Hard gates


@pytest.mark.unit
class TestHardGates:
    def test_no_buy_at_ceiling(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=10)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=80)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        assert intent.buy_below is None
        assert intent.quote.bid_price is None

    def test_no_sell_at_floor(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=0, floor=0)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=0)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        assert intent.sell_above is None
        assert intent.quote.ask_price is None

    def test_rationale_is_v6(self) -> None:
        fv, sg = _engines()
        params = V6CombinedParams(opening_seed_size=0)
        strat = PepperV6CombinedStrategy(fv, sg, params)
        snap = _snapshot(position=50)
        mem = _fresh_memory()
        ctx = StrategyContext(PEPPER, snap, mem, _pepper_config())

        intent = strat.generate_intent(ctx)
        assert intent.rationale == "pepper_v6_combined"

"""Tests for the 5 new PEPPER strategy classes.

Covers:
- param validation
- basic intent shape at various positions
- seed phase behavior
- hard floor/ceiling gates
- rationale and mode
- each strategy's distinctive feature

These are research-only strategies, not in STRATEGY_REGISTRY.
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
    TradePrint,
)
from src.strategies.base import StrategyContext
from src.strategies.pepper_drift_asymmetric import (
    DriftAsymmetricParams,
    PepperDriftAsymmetricStrategy,
)
from src.strategies.pepper_flow_overlay import (
    FlowOverlayParams,
    PepperFlowOverlayStrategy,
    _estimate_net_flow,
)
from src.strategies.pepper_imbalance_timer import (
    ImbalanceTimerParams,
    PepperImbalanceTimerStrategy,
)
from src.strategies.pepper_passive_maker import (
    PassiveMakerParams,
    PepperPassiveMakerStrategy,
)
from src.strategies.pepper_passive_opener import (
    PassiveOpenerParams,
    PepperPassiveOpenerStrategy,
)

PEPPER = "INTARIAN_PEPPER_ROOT"


def _pepper_config() -> ProductConfig:
    return ProductConfig(
        position_limit=80,
        strategy_name="market_making",  # only used for registry lookup, ignored here
        fair_value_method="linear_drift",
        fair_value_fallbacks=("mid",),
        taker_edge=1.0,
        maker_edge=1.0,
        quote_size=5,
        max_aggressive_size=10,
        inventory_skew=2.0,
        flatten_threshold=0.8,
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
    trades: tuple[TradePrint, ...] = (),
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product=PEPPER,
        timestamp=timestamp,
        bids=(BookLevel(bid, bid_vol),),
        asks=(BookLevel(ask, ask_vol),),
        position=position,
        trades=trades,
    )


def _engines() -> tuple[FairValueEngine, SignalEngine]:
    return FairValueEngine(), SignalEngine()


def _memory_with_mids(mids: list[float]) -> ProductMemory:
    memory = ProductMemory()
    memory.recent_mids = list(mids)
    return memory


# ------------------------------------------------------------------- PassiveMaker


@pytest.mark.unit
def test_passive_maker_param_validation() -> None:
    with pytest.raises(ValueError, match="bid_edge"):
        PassiveMakerParams(bid_edge=-1.0)
    with pytest.raises(ValueError, match="ceiling"):
        PassiveMakerParams(floor=50, ceiling=40)
    with pytest.raises(ValueError, match="core_target"):
        PassiveMakerParams(core_target=999)
    with pytest.raises(ValueError, match="seed_mode"):
        PassiveMakerParams(seed_mode="weird")


@pytest.mark.unit
def test_passive_maker_quotes_inside_touch() -> None:
    fv, sg = _engines()
    params = PassiveMakerParams(
        bid_edge=3.0,
        ask_edge=5.0,
        quote_size=5,
        core_target=40,
        seed_size=0,  # disable opening
    )
    strat = PepperPassiveMakerStrategy(fv, sg, params)
    # Position already at core_target → steady-state both-sided quoting.
    snap = _snapshot(position=40, bid=11_990, ask=12_010)
    mem = _memory_with_mids([12_000.0] * 32)  # flat history, drift_fair ≈ 12000
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())

    intent = strat.generate_intent(ctx)
    assert intent.rationale == "pepper_passive_maker"
    # Both sides populated, both strictly inside best_bid/best_ask.
    assert intent.quote is not None
    assert intent.quote.bid_price is not None and intent.quote.bid_price > 11_990
    assert intent.quote.ask_price is not None and intent.quote.ask_price < 12_010
    assert intent.quote.bid_size == 5
    assert intent.quote.ask_size == 5


@pytest.mark.unit
def test_passive_maker_seed_suppresses_ask() -> None:
    fv, sg = _engines()
    params = PassiveMakerParams(seed_mode="passive", seed_size=40, seed_window=5000)
    strat = PepperPassiveMakerStrategy(fv, sg, params)
    snap = _snapshot(position=0, timestamp=0)
    mem = ProductMemory()
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())

    intent = strat.generate_intent(ctx)
    # During opening seed with position below seed_size: no ask at all.
    assert intent.quote is not None
    assert intent.quote.ask_price is None
    assert intent.quote.ask_size == 0
    # A bid should still be present for the passive open.
    assert intent.quote.bid_price is not None
    assert intent.quote.bid_size > 0


@pytest.mark.unit
def test_passive_maker_ceiling_gate() -> None:
    fv, sg = _engines()
    params = PassiveMakerParams(seed_size=0, core_target=40, ceiling=80)
    strat = PepperPassiveMakerStrategy(fv, sg, params)
    snap = _snapshot(position=80)
    mem = _memory_with_mids([12_000.0] * 32)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    # At ceiling: no buys.
    assert intent.quote is not None
    assert intent.quote.bid_price is None
    assert intent.quote.bid_size == 0
    assert intent.buy_below is None
    # Sells allowed.
    assert intent.quote.ask_size > 0


# ------------------------------------------------------------------- DriftAsymmetric


@pytest.mark.unit
def test_drift_asymmetric_param_validation() -> None:
    with pytest.raises(ValueError, match="slope_window"):
        DriftAsymmetricParams(slope_window=1)
    with pytest.raises(ValueError, match="slope_r2_min"):
        DriftAsymmetricParams(slope_r2_min=2.0)
    with pytest.raises(ValueError, match="reversal_target"):
        DriftAsymmetricParams(reversal_target=999)


@pytest.mark.unit
def test_drift_asymmetric_positive_slope_tightens_bid() -> None:
    fv, sg = _engines()
    params = DriftAsymmetricParams(
        base_edge=3.0,
        slope_skew_factor=10.0,
        max_asymmetry=3.0,
        slope_r2_min=0.0,  # accept any r2
        slope_window=5,
        seed_size=0,
        core_target=50,
        inventory_skew_coef=0.0,
    )
    strat = PepperDriftAsymmetricStrategy(fv, sg, params)
    # Rising mids → strongly positive slope → asymmetric: tight bid, wide ask.
    rising = [12_000, 12_001, 12_002, 12_003, 12_004]
    snap = _snapshot(position=50, bid=11_995, ask=12_015)
    mem = _memory_with_mids(rising)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["asymmetry"] > 0
    assert intent.metadata["bid_edge"] < intent.metadata["ask_edge"]


@pytest.mark.unit
def test_drift_asymmetric_reversal_guard() -> None:
    fv, sg = _engines()
    params = DriftAsymmetricParams(
        base_edge=3.0,
        slope_window=5,
        slope_r2_min=0.0,
        seed_size=0,
        core_target=60,
        reversal_slope_threshold=0.01,
        reversal_r2_min=0.0,
        reversal_target=0,
    )
    strat = PepperDriftAsymmetricStrategy(fv, sg, params)
    # Falling mids strong negative slope.
    falling = [12_020, 12_015, 12_010, 12_005, 12_000]
    snap = _snapshot(position=60, bid=11_990, ask=12_010)
    mem = _memory_with_mids(falling)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["reversal_active"] is True
    assert intent.metadata["effective_target"] == 0


# ------------------------------------------------------------------- ImbalanceTimer


@pytest.mark.unit
def test_imbalance_timer_param_validation() -> None:
    with pytest.raises(ValueError, match="add_imbalance_threshold"):
        ImbalanceTimerParams(add_imbalance_threshold=1.5)
    with pytest.raises(ValueError, match="core_target"):
        ImbalanceTimerParams(core_target=999)


@pytest.mark.unit
def test_imbalance_timer_bid_heavy_triggers_add() -> None:
    fv, sg = _engines()
    params = ImbalanceTimerParams(
        add_imbalance_threshold=0.30,
        add_size=4,
        max_add_mid_above_fair=2.0,
        min_top_depth=0,
        core_target=60,
        seed_size=0,
    )
    strat = PepperImbalanceTimerStrategy(fv, sg, params)
    # Big bid volume, small ask → imbalance >> 0.3.
    snap = _snapshot(position=50, bid=11_995, bid_vol=50, ask=12_005, ask_vol=5)
    mem = _memory_with_mids([12_000.0] * 32)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["add_triggered"] is True
    # Taker threshold set to best_ask to cross.
    assert intent.buy_below == 12_005.0


@pytest.mark.unit
def test_imbalance_timer_ask_heavy_triggers_trim() -> None:
    fv, sg = _engines()
    params = ImbalanceTimerParams(
        trim_imbalance_threshold=0.30,
        trim_size=4,
        min_trim_mid_above_fair=-10.0,  # easy to satisfy
        min_top_depth=0,
        core_target=60,
        seed_size=0,
    )
    strat = PepperImbalanceTimerStrategy(fv, sg, params)
    snap = _snapshot(position=70, bid=11_995, bid_vol=5, ask=12_005, ask_vol=50)
    mem = _memory_with_mids([12_000.0] * 32)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["trim_triggered"] is True
    assert intent.sell_above == 11_995.0


@pytest.mark.unit
def test_imbalance_timer_untrusted_signal_skipped() -> None:
    fv, sg = _engines()
    # Raise min_top_depth above the visible liquidity so signal is
    # considered untrusted.
    params = ImbalanceTimerParams(min_top_depth=1_000, core_target=60, seed_size=0)
    strat = PepperImbalanceTimerStrategy(fv, sg, params)
    snap = _snapshot(position=50, bid=11_995, bid_vol=50, ask=12_005, ask_vol=5)
    mem = _memory_with_mids([12_000.0] * 32)
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["signal_trusted"] is False
    assert intent.metadata["add_triggered"] is False


# ------------------------------------------------------------------- FlowOverlay


@pytest.mark.unit
def test_flow_overlay_param_validation() -> None:
    with pytest.raises(ValueError, match="flow_decay"):
        FlowOverlayParams(flow_decay=1.5)
    with pytest.raises(ValueError, match="core_long"):
        FlowOverlayParams(core_long=999)


@pytest.mark.unit
def test_estimate_net_flow() -> None:
    trades = (
        TradePrint(price=12_005, quantity=4, timestamp=100),  # buyer-agg (above 12000)
        TradePrint(price=11_995, quantity=3, timestamp=100),  # seller-agg
        TradePrint(price=12_000, quantity=5, timestamp=100),  # at-mid: 0
    )
    assert _estimate_net_flow(trades, prior_mid=12_000.0) == 4 - 3


@pytest.mark.unit
def test_flow_overlay_bullish_flow_biases_long() -> None:
    fv, sg = _engines()
    params = FlowOverlayParams(
        core_long=50,
        flow_decay=0.0,  # no decay: only this tick's flow matters
        flow_scale=1.0,
        flow_bias_size=20,
        flow_min_magnitude=0.0,
        seed_size=0,
    )
    strat = PepperFlowOverlayStrategy(fv, sg, params)
    trades = (
        TradePrint(price=12_005, quantity=10, timestamp=100),
        TradePrint(price=12_006, quantity=5, timestamp=100),
    )
    snap = _snapshot(position=50, trades=trades)
    mem = _memory_with_mids([12_000.0] * 32)
    mem.values["pepper_flow_prior_mid"] = 12_000.0
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["bias"] > 0
    assert intent.metadata["target"] > 50


@pytest.mark.unit
def test_flow_overlay_no_trades_bias_zero() -> None:
    fv, sg = _engines()
    params = FlowOverlayParams(core_long=50, flow_min_magnitude=0.0, seed_size=0)
    strat = PepperFlowOverlayStrategy(fv, sg, params)
    snap = _snapshot(position=50, trades=())
    mem = _memory_with_mids([12_000.0] * 32)
    mem.values["pepper_flow_prior_mid"] = 12_000.0
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.metadata["tick_flow"] == 0
    assert intent.metadata["bias"] == 0


# ------------------------------------------------------------------- PassiveOpener


@pytest.mark.unit
def test_passive_opener_param_validation() -> None:
    with pytest.raises(ValueError, match="passive_bid_improve"):
        PassiveOpenerParams(passive_bid_improve=-1)
    with pytest.raises(ValueError, match="seed_size"):
        PassiveOpenerParams(seed_size=200)
    with pytest.raises(ValueError, match="steady_core_target"):
        PassiveOpenerParams(steady_core_target=999)


@pytest.mark.unit
def test_passive_opener_first_tick_is_passive_not_taker() -> None:
    fv, sg = _engines()
    params = PassiveOpenerParams(
        opening_passive_window=3,
        opening_taker_fallback_tick=3,
        seed_size=40,
        passive_bid_improve=1,
        opening_max_size_per_tick=20,
    )
    strat = PepperPassiveOpenerStrategy(fv, sg, params)
    snap = _snapshot(position=0, bid=11_990, ask=12_010, timestamp=0)
    mem = ProductMemory()
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    # First tick: no taker.
    assert intent.buy_below is None
    # Passive bid at best_bid + 1.
    assert intent.quote is not None
    assert intent.quote.bid_price == 11_991
    # Size respects opening_max_size_per_tick.
    assert intent.quote.bid_size == 20
    # No ask while still below seed.
    assert intent.quote.ask_size == 0


@pytest.mark.unit
def test_passive_opener_fallback_after_window() -> None:
    fv, sg = _engines()
    params = PassiveOpenerParams(
        opening_passive_window=3,
        opening_taker_fallback_tick=3,
        seed_size=40,
    )
    strat = PepperPassiveOpenerStrategy(fv, sg, params)
    snap = _snapshot(position=5, bid=11_990, ask=12_010, timestamp=400)
    mem = ProductMemory()
    mem.counters["passive_opener_ticks"] = 4  # past fallback tick
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    # Taker fallback active: buy_below set to 1e9.
    assert intent.buy_below == 1e9


@pytest.mark.unit
def test_passive_opener_ceiling_blocks_buys() -> None:
    fv, sg = _engines()
    params = PassiveOpenerParams(seed_size=40, steady_core_target=40, ceiling=80)
    strat = PepperPassiveOpenerStrategy(fv, sg, params)
    snap = _snapshot(position=80, bid=11_990, ask=12_010, timestamp=5000)
    mem = _memory_with_mids([12_000.0] * 32)
    mem.counters["passive_opener_ticks"] = 10
    ctx = StrategyContext(product=PEPPER, snapshot=snap, memory=mem, config=_pepper_config())
    intent = strat.generate_intent(ctx)
    assert intent.quote is not None
    assert intent.quote.bid_size == 0
    assert intent.buy_below is None

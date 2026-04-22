"""Unit and integration tests for ``src.signals.flow_analyzer``."""

from __future__ import annotations

import dataclasses

import pytest

from src.core.config import default_engine_config
from src.core.types import (
    BookLevel,
    NormalizedSnapshot,
    ProductMemory,
    ScannerConfig,
    TradePrint,
)
from src.signals.flow_analyzer import FlowAnalyzer

# ------------------------------------------------------------ helpers


def _memory(**kwargs: object) -> ProductMemory:
    return ProductMemory(**kwargs)  # type: ignore[arg-type]


def _snapshot(
    trades: tuple[TradePrint, ...] = (),
    position: int = 0,
    product: str = "TEST",
    timestamp: int = 100,
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product=product,
        timestamp=timestamp,
        bids=(BookLevel(9998, 10),),
        asks=(BookLevel(10002, 10),),
        position=position,
        trades=trades,
    )


def _trade(
    quantity: int = 5,
    price: int = 10000,
    buyer: str | None = None,
    seller: str | None = None,
    source: str = "market",
) -> TradePrint:
    return TradePrint(
        price=price,
        quantity=quantity,
        buyer=buyer,
        seller=seller,
        timestamp=0,
        source=source,  # type: ignore[arg-type]
    )


def _default_config(**overrides: object) -> ScannerConfig:
    defaults: dict[str, object] = {
        "enabled": True,
        "extrema_window": 20,
        "extrema_tolerance": 1.0,
        "flow_decay": 0.8,
        "repeated_size_threshold": 3,
        "verbosity": 0,
    }
    defaults.update(overrides)
    return ScannerConfig(**defaults)  # type: ignore[arg-type]


# ------------------------------------------------------------ unit tests


@pytest.mark.unit
def test_disabled_scanner_returns_none() -> None:
    analyzer = FlowAnalyzer(_default_config(enabled=False))
    result = analyzer.scan(_snapshot(), _memory())
    assert result is None


@pytest.mark.unit
def test_empty_trades_produce_neutral_report() -> None:
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=()), _memory())
    assert report is not None
    assert report.net_flow == 0
    assert report.flow_score == 0.0
    assert report.near_high is False
    assert report.near_low is False
    assert len(report.flags) == 0


@pytest.mark.unit
def test_single_trade_no_repeated_size_flag() -> None:
    trades = (_trade(quantity=5, buyer="A"),)
    analyzer = FlowAnalyzer(_default_config(repeated_size_threshold=3))
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    flags_with_repeated = [f for f in report.flags if f.startswith("repeated_size")]
    assert len(flags_with_repeated) == 0


@pytest.mark.unit
def test_repeated_size_detection() -> None:
    trades = tuple(_trade(quantity=5, buyer="A") for _ in range(3))
    analyzer = FlowAnalyzer(_default_config(repeated_size_threshold=3))
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    assert "repeated_size_5x3" in report.flags


@pytest.mark.unit
def test_repeated_size_below_threshold() -> None:
    trades = (_trade(quantity=5, buyer="A"), _trade(quantity=5, buyer="B"))
    analyzer = FlowAnalyzer(_default_config(repeated_size_threshold=3))
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    flags_with_repeated = [f for f in report.flags if f.startswith("repeated_size")]
    assert len(flags_with_repeated) == 0


@pytest.mark.unit
def test_net_flow_positive_buyer_only() -> None:
    trades = (
        _trade(quantity=10, buyer="A", seller=None),
        _trade(quantity=5, buyer="B", seller=None),
    )
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    assert report.net_flow == 15


@pytest.mark.unit
def test_net_flow_negative_seller_only() -> None:
    trades = (
        _trade(quantity=10, buyer=None, seller="X"),
        _trade(quantity=3, buyer=None, seller="Y"),
    )
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    assert report.net_flow == -13


@pytest.mark.unit
def test_net_flow_zero_when_ambiguous() -> None:
    trades = (
        _trade(quantity=10, buyer="A", seller="B"),  # both -> 0
        _trade(quantity=5, buyer=None, seller=None),  # neither -> 0
    )
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    assert report.net_flow == 0


@pytest.mark.unit
def test_flow_score_decays_toward_zero() -> None:
    memory = _memory()
    memory.values["scan_flow_score"] = 0.8

    analyzer = FlowAnalyzer(_default_config(flow_decay=0.9))
    report = analyzer.scan(_snapshot(trades=()), memory)
    assert report is not None
    # With no trades, normalised = 0, so new = 0.9 * 0.8 + 0.1 * 0 = 0.72
    assert abs(report.flow_score - 0.72) < 1e-4


@pytest.mark.unit
def test_flow_score_clamped() -> None:
    memory = _memory()
    memory.values["scan_flow_score"] = 1.0

    # Strong buy side to push score further
    trades = tuple(_trade(quantity=100, buyer="A") for _ in range(10))
    analyzer = FlowAnalyzer(_default_config(flow_decay=0.5))
    report = analyzer.scan(_snapshot(trades=trades), memory)
    assert report is not None
    assert -1.0 <= report.flow_score <= 1.0


@pytest.mark.unit
def test_near_high_detection() -> None:
    memory = _memory(recent_mids=[9990.0, 10000.0, 10005.0])
    trades = (_trade(price=10005, buyer="A"),)
    analyzer = FlowAnalyzer(_default_config(extrema_tolerance=1.0))
    report = analyzer.scan(_snapshot(trades=trades), memory)
    assert report is not None
    assert report.near_high is True


@pytest.mark.unit
def test_near_low_detection() -> None:
    memory = _memory(recent_mids=[9990.0, 10000.0, 10005.0])
    trades = (_trade(price=9990, seller="X"),)
    analyzer = FlowAnalyzer(_default_config(extrema_tolerance=1.0))
    report = analyzer.scan(_snapshot(trades=trades), memory)
    assert report is not None
    assert report.near_low is True


@pytest.mark.unit
def test_no_extrema_with_empty_history() -> None:
    memory = _memory()
    trades = (_trade(price=10000, buyer="A"),)
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=trades), memory)
    assert report is not None
    assert report.near_high is False
    assert report.near_low is False


@pytest.mark.unit
def test_own_trades_excluded() -> None:
    trades = (
        _trade(quantity=10, buyer="A", source="own"),
        _trade(quantity=5, buyer="B", source="market"),
    )
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(trades=trades), _memory())
    assert report is not None
    # Only the market trade contributes
    assert report.net_flow == 5
    assert report.metadata["market_trade_count"] == 1


@pytest.mark.unit
def test_memory_persistence_across_scans() -> None:
    memory = _memory()
    analyzer = FlowAnalyzer(_default_config(flow_decay=0.5))

    # Step 1: strong buy
    trades1 = tuple(_trade(quantity=10, buyer="A") for _ in range(5))
    report1 = analyzer.scan(_snapshot(trades=trades1, timestamp=100), memory)
    assert report1 is not None
    score_after_1 = report1.flow_score

    # Step 2: strong sell
    trades2 = tuple(_trade(quantity=10, seller="X") for _ in range(5))
    report2 = analyzer.scan(_snapshot(trades=trades2, timestamp=200), memory)
    assert report2 is not None
    # Score should shift toward negative
    assert report2.flow_score < score_after_1


@pytest.mark.unit
def test_step_counter_increments() -> None:
    memory = _memory()
    analyzer = FlowAnalyzer(_default_config())
    analyzer.scan(_snapshot(timestamp=100), memory)
    assert memory.counters.get("scan_step_count") == 1
    analyzer.scan(_snapshot(timestamp=200), memory)
    assert memory.counters.get("scan_step_count") == 2


@pytest.mark.unit
def test_flow_report_is_frozen() -> None:
    analyzer = FlowAnalyzer(_default_config())
    report = analyzer.scan(_snapshot(), _memory())
    assert report is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.net_flow = 999  # type: ignore[misc]


# ------------------------------------------------------------ integration


@pytest.mark.unit
def test_trader_default_verbosity_0_silent() -> None:
    """Default config (verbosity=0) adds no scan keys to logger events."""
    from src.datamodel import Observation, OrderDepth, TradingState
    from src.trader import Trader

    config = default_engine_config()
    trader = Trader(config=config, reraise_exceptions=True)

    depth = OrderDepth()
    depth.buy_orders = {9998: 10}
    depth.sell_orders = {10002: -10}

    state = TradingState(
        traderData="",
        timestamp=100,
        listings={},
        order_depths={"EMERALDS": depth},
        own_trades={"EMERALDS": []},
        market_trades={"EMERALDS": []},
        position={"EMERALDS": 0},
        observations=Observation(),
    )
    trader.run(state)

    for event in trader.logger.events:
        assert "scan_flags" not in event
        assert "flow_report" not in event


@pytest.mark.unit
def test_trader_verbosity_1_logs_flags() -> None:
    """Verbosity=1 adds scan_flags but not full flow_report."""
    from src.core.types import ScannerConfig
    from src.datamodel import Observation, OrderDepth, Trade, TradingState
    from src.trader import Trader

    scanner_cfg = ScannerConfig(enabled=True, verbosity=1)
    config = dataclasses.replace(default_engine_config(), scanner_config=scanner_cfg)
    trader = Trader(config=config, reraise_exceptions=True)

    depth = OrderDepth()
    depth.buy_orders = {9998: 10}
    depth.sell_orders = {10002: -10}
    market_trade = Trade("EMERALDS", 9999, 5, "BuyerA", "", 100)

    state = TradingState(
        traderData="",
        timestamp=100,
        listings={},
        order_depths={"EMERALDS": depth},
        own_trades={"EMERALDS": []},
        market_trades={"EMERALDS": [market_trade]},
        position={"EMERALDS": 0},
        observations=Observation(),
    )
    trader.run(state)

    emerald_events = [e for e in trader.logger.events if e.get("product") == "EMERALDS"]
    assert len(emerald_events) > 0
    assert "scan_flags" in emerald_events[0]
    assert "flow_report" not in emerald_events[0]


@pytest.mark.unit
def test_trader_verbosity_2_logs_full_report() -> None:
    """Verbosity=2 adds full flow_report dict."""
    from src.core.types import ScannerConfig
    from src.datamodel import Observation, OrderDepth, Trade, TradingState
    from src.trader import Trader

    scanner_cfg = ScannerConfig(enabled=True, verbosity=2)
    config = dataclasses.replace(default_engine_config(), scanner_config=scanner_cfg)
    trader = Trader(config=config, reraise_exceptions=True)

    depth = OrderDepth()
    depth.buy_orders = {9998: 10}
    depth.sell_orders = {10002: -10}
    market_trade = Trade("EMERALDS", 9999, 5, "BuyerA", "", 100)

    state = TradingState(
        traderData="",
        timestamp=100,
        listings={},
        order_depths={"EMERALDS": depth},
        own_trades={"EMERALDS": []},
        market_trades={"EMERALDS": [market_trade]},
        position={"EMERALDS": 0},
        observations=Observation(),
    )
    trader.run(state)

    emerald_events = [e for e in trader.logger.events if e.get("product") == "EMERALDS"]
    assert len(emerald_events) > 0
    fr = emerald_events[0]["flow_report"]
    assert isinstance(fr, dict)
    assert "net_flow" in fr
    assert "flow_score" in fr
    assert "flags" in fr
    assert "repeated_sizes" in fr


# ------------------------------------------------------------ persistence


@pytest.mark.unit
def test_only_flow_score_and_step_count_persisted() -> None:
    """Scanner persists exactly scan_flow_score + scan_step_count."""
    memory = _memory(recent_mids=[9990.0, 10000.0, 10005.0])
    trades = (
        _trade(quantity=5, price=10005, buyer="A"),
        _trade(quantity=5, price=10005, buyer="B"),
        _trade(quantity=5, price=10005, buyer="C"),
    )
    analyzer = FlowAnalyzer(_default_config())
    analyzer.scan(_snapshot(trades=trades), memory)

    # Only these two keys should exist with the scan_ prefix
    scan_value_keys = [k for k in memory.values if k.startswith("scan_")]
    scan_counter_keys = [k for k in memory.counters if k.startswith("scan_")]
    scan_flag_keys = [k for k in memory.flags if k.startswith("scan_")]

    assert scan_value_keys == ["scan_flow_score"]
    assert scan_counter_keys == ["scan_step_count"]
    assert scan_flag_keys == []

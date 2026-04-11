"""Unit tests for ``src.backtest.parameter_sweep``."""

from __future__ import annotations

import pytest

from src.backtest.parameter_sweep import build_parameter_sweep_report
from src.backtest.replay_engine import ReplayEngine, ReplayStep
from src.core.config import EngineConfig, ProductConfig


def _row(timestamp: int, product: str, bid: int, ask: int) -> dict[str, str]:
    return {
        "day": "-1",
        "timestamp": str(timestamp),
        "product": product,
        "bid_price_1": str(bid),
        "bid_volume_1": "5",
        "bid_price_2": "",
        "bid_volume_2": "",
        "bid_price_3": "",
        "bid_volume_3": "",
        "ask_price_1": str(ask),
        "ask_volume_1": "5",
        "ask_price_2": "",
        "ask_volume_2": "",
        "ask_price_3": "",
        "ask_volume_3": "",
        "mid_price": str((bid + ask) / 2),
        "profit_and_loss": "0.0",
    }


def _replay() -> ReplayEngine:
    return ReplayEngine(
        [
            ReplayStep(day=-1, timestamp=0, rows_by_product={"P": _row(0, "P", 99, 101)}),
            ReplayStep(day=-1, timestamp=1, rows_by_product={"P": _row(1, "P", 100, 102)}),
            ReplayStep(day=-1, timestamp=2, rows_by_product={"P": _row(2, "P", 101, 103)}),
        ]
    )


@pytest.mark.unit
def test_build_parameter_sweep_report_runs_all_grid_rows() -> None:
    config = EngineConfig(
        products={
            "P": ProductConfig(
                position_limit=20,
                strategy_name="market_making",
                fair_value_method="mid",
                fair_value_fallbacks=("microprice",),
                maker_edge=2.0,
                taker_edge=1.0,
                inventory_skew=2.5,
                flatten_threshold=0.7,
            )
        }
    )
    report = build_parameter_sweep_report(
        _replay(),
        product="P",
        grid={
            "maker_edge": [1.0, 2.0],
            "taker_edge": [1.0],
            "inventory_skew": [2.5],
            "flatten_threshold": [0.7, 0.8],
        },
        config=config,
        run_label="unit",
    )

    assert report.product == "P"
    assert report.fair_value_method == "mid"
    assert len(report.rows) == 4
    assert report.baseline.params == {
        "maker_edge": 2.0,
        "taker_edge": 1.0,
        "inventory_skew": 2.5,
        "flatten_threshold": 0.7,
    }
    assert len(report.aggregates) == 6

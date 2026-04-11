"""Smoke tests for ``src.backtest.charts``.

These tests assert that each plotter writes a non-empty PNG under
a tmp path when given a reasonable ``SimulationResult``. They do not
verify pixel content — the higher-level check for chart *quality*
happens by human review. What we care about here is:

- the charts module doesn't crash on realistic inputs
- lazy matplotlib import works (Agg backend, no display)
- ``render_review_charts`` produces the expected filenames
- products with zero trades skip the trade-based plots
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backtest import charts
from src.backtest.metrics import (
    ProductResult,
    SimulationResult,
    TradeRecord,
)


def _record(
    *,
    product: str,
    side: str,
    price: float,
    quantity: int,
    timestamp: int,
    mode: str = "taker",
    fair: float | None = None,
) -> TradeRecord:
    return TradeRecord(
        product=product,
        side=side,  # type: ignore[arg-type]
        price=price,
        quantity=quantity,
        mode=mode,  # type: ignore[arg-type]
        decision_timestamp=timestamp,
        fill_timestamp=timestamp,
        fair_value_at_decision=fair,
        fair_value_method_at_decision="anchor" if fair is not None else None,
        mid_at_decision=price,
        mid_at_fill=price,
    )


def _result_with_two_products() -> SimulationResult:
    mid_series = {
        "P": tuple((ts, 100.0 + 0.1 * ts) for ts in range(30)),
        "Q": tuple((ts, 50.0 - 0.05 * ts) for ts in range(30)),
    }
    fair_value_series = {
        "P": tuple((ts, 100.0) for ts in range(30)),
        "Q": tuple((ts, 49.5) for ts in range(30)),
    }
    pnl_series = {
        "P": tuple((ts, float(ts)) for ts in range(30)),
        "Q": tuple((ts, float(-ts)) for ts in range(30)),
    }
    trades = [
        _record(product="P", side="buy", price=100.0, quantity=2, timestamp=3, fair=101.0),
        _record(product="P", side="sell", price=101.5, quantity=1, timestamp=10, fair=100.0),
        _record(
            product="P",
            side="buy",
            price=100.2,
            quantity=1,
            timestamp=15,
            mode="maker",
            fair=100.5,
        ),
    ]
    per_product = {
        "P": ProductResult(
            product="P",
            pnl=10.0,
            cash=-200.0,
            final_position=2,
            mark_price=102.0,
            order_count=10,
            trade_count=3,
            taker_trade_count=2,
            maker_trade_count=1,
            taker_trade_quantity=3,
            maker_trade_quantity=1,
            buy_trade_quantity=3,
            sell_trade_quantity=1,
            steps_near_limit=0,
            avg_entry_edge=0.5,
            entry_edge_count=3,
            avg_markout_1=1.0,
            markout_1_count=3,
            avg_markout_5=0.5,
            markout_5_count=3,
            avg_markout_20=None,
            markout_20_count=0,
        ),
        "Q": ProductResult(
            product="Q",
            pnl=-5.0,
            cash=0.0,
            final_position=0,
            mark_price=49.0,
            order_count=0,
            trade_count=0,  # zero-trade product
            taker_trade_count=0,
            maker_trade_count=0,
            taker_trade_quantity=0,
            maker_trade_quantity=0,
            buy_trade_quantity=0,
            sell_trade_quantity=0,
            steps_near_limit=0,
        ),
    }
    return SimulationResult(
        steps=30,
        total_pnl=5.0,
        per_product=per_product,
        trade_records=tuple(trades),
        mid_series=mid_series,
        fair_value_series=fair_value_series,
        pnl_series=pnl_series,
    )


@pytest.mark.integration
def test_render_review_charts_writes_expected_files(tmp_path: Path) -> None:
    written = charts.render_review_charts(_result_with_two_products(), out_dir=tmp_path)
    names = {p.name for p in written}

    # Trading product P gets the full suite.
    assert "price_vs_fair_P.png" in names
    assert "pnl_over_time_P.png" in names
    assert "position_over_time_P.png" in names
    assert "maker_taker_P.png" in names
    assert "markouts_P.png" in names

    # Non-trading product Q gets the three series-based charts but
    # skips maker_taker / markouts.
    assert "price_vs_fair_Q.png" in names
    assert "pnl_over_time_Q.png" in names
    assert "position_over_time_Q.png" in names
    assert "maker_taker_Q.png" not in names
    assert "markouts_Q.png" not in names

    # Total chart always attempted.
    assert "pnl_over_time_total.png" in names

    for path in written:
        assert path.exists()
        assert path.stat().st_size > 0


@pytest.mark.integration
def test_render_review_charts_noop_on_empty_result(tmp_path: Path) -> None:
    empty = SimulationResult(steps=0, total_pnl=0.0)
    written = charts.render_review_charts(empty, out_dir=tmp_path)
    assert written == []


@pytest.mark.integration
def test_render_markouts_handles_single_horizon(tmp_path: Path) -> None:
    result = _result_with_two_products()
    out = tmp_path / "markouts_P.png"
    # Only horizon 1 — should still render without crashing on the
    # unpacking path for a single-element axes.
    ok = charts.render_markouts(result, "P", out, horizons=(1,))
    assert ok
    assert out.exists()
    assert out.stat().st_size > 0

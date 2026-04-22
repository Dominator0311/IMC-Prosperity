"""Tests for stability_metrics distribution aggregation."""
from __future__ import annotations

import pytest

from src.analysis.calibration.generative_simulator import SessionResult
from src.analysis.calibration.stability_metrics import (
    render_report_markdown, summarize_sessions,
)


def _make_session(seed: int, pnl: float) -> SessionResult:
    return SessionResult(
        seed=seed, n_ticks=10, products=("P",),
        per_tick_equity=tuple([pnl * i / 9 for i in range(10)]),
        per_tick_position={"P": tuple([0] * 10)},
        per_tick_fv={"P": tuple([5000.0] * 10)},
        final_pnl=pnl,
        realized_alpha=pnl / 10,
        realized_r2=0.95,
        realized_downside_dev=0.0 if pnl >= 0 else abs(pnl),
        n_fills={"P": 5},
        n_orders_rejected_limit={"P": 0},
    )


def test_summarize_rejects_empty():
    with pytest.raises(ValueError, match="zero sessions"):
        summarize_sessions([], strategy_name="x")


def test_summarize_basic_stats():
    sessions = [_make_session(seed=i, pnl=float(i)) for i in range(10)]
    report = summarize_sessions(sessions, strategy_name="test")
    assert report.n_sessions == 10
    # PnLs are 0..9; mean should be 4.5, median 4.5.
    assert abs(report.pnl.mean - 4.5) < 1e-9
    assert abs(report.pnl.median - 4.5) < 1e-9
    assert report.pnl.min_value == 0.0
    assert report.pnl.max_value == 9.0
    # Win rate (PnL > 0): 9/10
    assert report.win_rate == 0.9


def test_summarize_identifies_worst_and_best_seeds():
    sessions = [_make_session(seed=i, pnl=float(i * 100)) for i in range(20)]
    report = summarize_sessions(sessions, strategy_name="test", top_n_seeds=3)
    assert report.worst_seeds == (0, 1, 2)
    assert report.best_seeds == (19, 18, 17)


def test_summarize_handles_all_negative_pnls():
    sessions = [_make_session(seed=i, pnl=-float(i + 1)) for i in range(5)]
    report = summarize_sessions(sessions, strategy_name="loser")
    assert report.win_rate == 0.0
    assert report.pnl.max_value == -1.0
    assert report.pnl.min_value == -5.0


def test_summarize_quantiles_correct_at_known_distribution():
    # PnLs = 0, 1, 2, ..., 99 -> q05=4.95, q25=24.75, q75=74.25, q95=94.05
    sessions = [_make_session(seed=i, pnl=float(i)) for i in range(100)]
    report = summarize_sessions(sessions, strategy_name="uniform")
    assert abs(report.pnl.q05 - 4.95) < 0.5
    assert abs(report.pnl.q95 - 94.05) < 0.5
    assert abs(report.pnl.q25 - 24.75) < 0.5
    assert abs(report.pnl.q75 - 74.25) < 0.5


def test_render_report_markdown_includes_strategy_names():
    sessions_a = [_make_session(seed=i, pnl=10.0) for i in range(5)]
    sessions_b = [_make_session(seed=i, pnl=20.0) for i in range(5)]
    a = summarize_sessions(sessions_a, strategy_name="alpha")
    b = summarize_sessions(sessions_b, strategy_name="beta")
    md = render_report_markdown([a, b])
    assert "## alpha" in md
    assert "## beta" in md
    assert "PnL distribution comparison" in md


def test_render_report_handles_no_reports():
    md = render_report_markdown([])
    assert "no reports" in md.lower()


def test_skewness_positive_for_right_tailed_distribution():
    # Most sessions PnL=0, one big winner.
    sessions = [_make_session(seed=i, pnl=0.0) for i in range(99)]
    sessions.append(_make_session(seed=99, pnl=1000.0))
    report = summarize_sessions(sessions, strategy_name="lottery")
    assert report.pnl.skew > 5  # very right-skewed


def test_distribution_with_constant_pnl_has_zero_std():
    sessions = [_make_session(seed=i, pnl=42.0) for i in range(10)]
    report = summarize_sessions(sessions, strategy_name="constant")
    assert report.pnl.std == 0.0
    assert report.pnl.mean == 42.0

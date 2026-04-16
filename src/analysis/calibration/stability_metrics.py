"""Aggregate Monte Carlo session results into a strategy stability profile.

Given N SessionResult objects from running the same strategy across N
independent seeds, compute:

  - PnL distribution (mean, median, std, quantiles 5/25/50/75/95, skew)
  - Equity-slope (alpha) distribution
  - R^2 distribution (the key overfit detector — high mean PnL paired
    with low / inconsistent R^2 = lucky strategy that doesn't reproduce)
  - Downside deviation distribution (negative-return semi-deviation)
  - Worst-N and best-N seeds, for failure-mode inspection

The aggregator is pure: takes a Sequence[SessionResult], returns a
frozen dataclass. Caller decides what to do with the report (write
to disk, render markdown, plot histograms).
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from src.analysis.calibration.generative_simulator import SessionResult


@dataclass(frozen=True)
class DistributionStats:
    """Standard summary stats for a 1-D distribution."""

    n: int
    mean: float
    median: float
    std: float
    q05: float
    q25: float
    q75: float
    q95: float
    skew: float
    min_value: float
    max_value: float


@dataclass(frozen=True)
class StrategyMonteCarloReport:
    """All outputs from N MC sessions for one strategy."""

    strategy_name: str
    n_sessions: int
    pnl: DistributionStats
    alpha: DistributionStats
    r2: DistributionStats
    downside_deviation: DistributionStats
    n_fills_per_session: DistributionStats
    n_orders_rejected_per_session: DistributionStats
    worst_seeds: tuple[int, ...]   # 5 lowest-PnL seeds
    best_seeds: tuple[int, ...]    # 5 highest-PnL seeds
    win_rate: float                # fraction of sessions with PnL > 0


def summarize_sessions(
    sessions: Sequence[SessionResult],
    *,
    strategy_name: str,
    top_n_seeds: int = 5,
) -> StrategyMonteCarloReport:
    """Aggregate N SessionResults into a strategy report.

    Raises:
        ValueError: if sessions is empty.
    """
    if not sessions:
        raise ValueError("Cannot summarize zero sessions")

    pnls = np.asarray([s.final_pnl for s in sessions], dtype=float)
    alphas = np.asarray([s.realized_alpha for s in sessions], dtype=float)
    r2s = np.asarray([s.realized_r2 for s in sessions], dtype=float)
    downside = np.asarray(
        [s.realized_downside_dev for s in sessions], dtype=float
    )
    n_fills = np.asarray(
        [sum(s.n_fills.values()) for s in sessions], dtype=float
    )
    n_rejected = np.asarray(
        [sum(s.n_orders_rejected_limit.values()) for s in sessions],
        dtype=float,
    )

    # Sort by PnL to find worst / best seeds.
    sorted_by_pnl = sorted(sessions, key=lambda s: s.final_pnl)
    worst = tuple(s.seed for s in sorted_by_pnl[:top_n_seeds])
    best = tuple(s.seed for s in sorted_by_pnl[-top_n_seeds:][::-1])
    win_rate = float(np.mean(pnls > 0))

    return StrategyMonteCarloReport(
        strategy_name=strategy_name,
        n_sessions=len(sessions),
        pnl=_distribution_stats(pnls),
        alpha=_distribution_stats(alphas),
        r2=_distribution_stats(r2s),
        downside_deviation=_distribution_stats(downside),
        n_fills_per_session=_distribution_stats(n_fills),
        n_orders_rejected_per_session=_distribution_stats(n_rejected),
        worst_seeds=worst,
        best_seeds=best,
        win_rate=win_rate,
    )


def render_report_markdown(
    reports: Sequence[StrategyMonteCarloReport],
) -> str:
    """Render one or more strategy reports as markdown."""
    lines: list[str] = ["# Monte Carlo strategy comparison", ""]
    if not reports:
        lines.append("(no reports)")
        return "\n".join(lines)
    n_sessions = reports[0].n_sessions
    lines.append(
        f"Each strategy was run across **{n_sessions} synthetic sessions**, "
        "each session = one full synthetic 1000-tick day with the same "
        "calibrated round-1 parameters."
    )
    lines.append("")

    # Comparison table: PnL summary across all strategies.
    lines.append("## PnL distribution comparison")
    lines.append("")
    lines.append("| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in reports:
        lines.append(
            f"| {r.strategy_name} | {r.pnl.mean:+.0f} | {r.pnl.median:+.0f} | "
            f"{r.pnl.std:.0f} | {r.pnl.q05:+.0f} | {r.pnl.q95:+.0f} | "
            f"{r.win_rate:.1%} | {r.r2.mean:+.3f} |"
        )
    lines.append("")

    # Per-strategy detail.
    for r in reports:
        lines.append(f"## {r.strategy_name}")
        lines.append("")
        lines.append(f"- Sessions: **{r.n_sessions}**")
        lines.append(f"- Win rate (PnL > 0): **{r.win_rate:.1%}**")
        lines.append("")
        lines.append("### PnL stats")
        lines.append(_dist_table(r.pnl))
        lines.append("")
        lines.append("### Alpha (slope of equity curve per tick)")
        lines.append(_dist_table(r.alpha))
        lines.append("")
        lines.append("### R^2 (consistency of equity slope; high = stable edge)")
        lines.append(_dist_table(r.r2))
        lines.append("")
        lines.append("### Downside deviation (semi-std of negative returns)")
        lines.append(_dist_table(r.downside_deviation))
        lines.append("")
        lines.append(
            f"- **Worst {len(r.worst_seeds)} seeds** (lowest PnL): "
            f"{', '.join(str(s) for s in r.worst_seeds)}"
        )
        lines.append(
            f"- **Best {len(r.best_seeds)} seeds** (highest PnL): "
            f"{', '.join(str(s) for s in r.best_seeds)}"
        )
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------- internals


def _distribution_stats(values: np.ndarray) -> DistributionStats:
    if len(values) == 0:
        return DistributionStats(
            n=0, mean=0.0, median=0.0, std=0.0,
            q05=0.0, q25=0.0, q75=0.0, q95=0.0,
            skew=0.0, min_value=0.0, max_value=0.0,
        )
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    skew = _skewness(values, mean=mean, std=std)
    return DistributionStats(
        n=len(values),
        mean=mean,
        median=float(np.median(values)),
        std=std,
        q05=float(np.quantile(values, 0.05)),
        q25=float(np.quantile(values, 0.25)),
        q75=float(np.quantile(values, 0.75)),
        q95=float(np.quantile(values, 0.95)),
        skew=skew,
        min_value=float(np.min(values)),
        max_value=float(np.max(values)),
    )


def _skewness(values: np.ndarray, *, mean: float, std: float) -> float:
    """Sample skewness (3rd standardized moment).

    Returns 0.0 for std=0 to avoid divide-by-zero (degenerate dist).
    """
    if std == 0 or len(values) < 3:
        return 0.0
    z = (values - mean) / std
    return float(np.mean(z ** 3))


def _dist_table(d: DistributionStats) -> str:
    """Render a DistributionStats as a small markdown table."""
    return (
        f"| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |\n"
        f"|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        f"| {d.n} | {d.mean:+.3f} | {d.median:+.3f} | {d.std:.3f} | "
        f"{d.q05:+.3f} | {d.q25:+.3f} | {d.q75:+.3f} | {d.q95:+.3f} | "
        f"{d.min_value:+.3f} | {d.max_value:+.3f} |"
    )

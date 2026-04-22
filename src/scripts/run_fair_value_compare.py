"""Run TOMATOES fair-value comparison with all 9 estimators.

Produces a comparison table with performance AND distinctness
diagnostics for shortlisting estimators for Phase 5 sweeps.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backtest.fair_value_compare import (
    build_fair_value_report,
    write_fair_value_report,
)
from src.backtest.replay_engine import ReplayEngine

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")

# All 9 estimators valid for TOMATOES (no anchor — TOMATOES has no anchor_price)
_TOMATOES_ESTIMATORS = (
    "mid",
    "rolling_mid",
    "weighted_mid",
    "ewma_mid",
    "depth_mid",
    "microprice",
    "wall_mid",
    "filtered_wall_mid",
    "hybrid_wall_micro",
)

_COVERAGE_GATE = 0.90


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="optim_tomatoes_fv")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    report = build_fair_value_report(
        replay,
        run_label=args.label,
        products=("TOMATOES",),
        estimator_names=_TOMATOES_ESTIMATORS,
    )
    directory = write_fair_value_report(report)

    print(f"Report written to {directory}")
    print()
    print(report.summary_text())

    # Shortlisting
    for product_report in report.products:
        eligible = [c for c in product_report.comparisons if c.coverage >= _COVERAGE_GATE]
        excluded = [c for c in product_report.comparisons if c.coverage < _COVERAGE_GATE]

        if excluded:
            print(f"\nExcluded (coverage < {_COVERAGE_GATE * 100:.0f}%):")
            for c in excluded:
                print(f"  {c.estimator}: coverage={c.coverage * 100:.1f}%")

        ranked = sorted(eligible, key=lambda c: c.pnl, reverse=True)
        top_3 = ranked[:3]

        print(f"\nTop 3 shortlisted estimators for {product_report.product}:")
        for i, c in enumerate(top_3, 1):
            d_pri = f"{c.mean_diff_vs_primary:.3f}" if c.mean_diff_vs_primary is not None else "n/a"
            d_mid = f"{c.mean_diff_vs_mid:.3f}" if c.mean_diff_vs_mid is not None else "n/a"
            chg = (
                f"{c.value_change_frequency * 100:.1f}%"
                if c.value_change_frequency is not None
                else "n/a"
            )
            print(
                f"  {i}. {c.estimator}: pnl={c.pnl:.2f}, trades={c.trade_count}, "
                f"d_primary={d_pri}, d_mid={d_mid}, chg={chg}"
            )


if __name__ == "__main__":
    main()

"""Estimator-aware TOMATOES parameter sweep.

Sweeps each shortlisted estimator with only the parameters that affect it:
- wall_mid: maker_edge x taker_edge (12 configs, no history dependency)
- rolling_mid: maker_edge x taker_edge x history_length (48 configs)
- weighted_mid: maker_edge x taker_edge x history_length (48 configs)

Total: 108 runs.
"""

from __future__ import annotations

import argparse
import math
from dataclasses import replace
from pathlib import Path

from src.backtest.parameter_sweep import (
    SweepRow,
    SweepValue,
    build_parameter_sweep_report,
    write_parameter_sweep_report,
)
from src.backtest.replay_engine import ReplayEngine
from src.core.config import EngineConfig, default_engine_config

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")

WALL_GRID: dict[str, list[SweepValue]] = {
    "maker_edge": [0.5, 1.0, 1.5, 2.0],
    "taker_edge": [0.5, 1.0, 1.5],
}

HISTORY_GRID: dict[str, list[SweepValue]] = {
    "maker_edge": [0.5, 1.0, 1.5, 2.0],
    "taker_edge": [0.5, 1.0, 1.5],
    "history_length": [16, 32, 48, 64],
}

SHORTLIST: list[tuple[str, dict[str, list[SweepValue]]]] = [
    ("wall_mid", WALL_GRID),
    ("rolling_mid", HISTORY_GRID),
    ("weighted_mid", HISTORY_GRID),
]


def _estimator_engine(estimator: str) -> EngineConfig:
    """Build EngineConfig with estimator as TOMATOES primary."""
    engine = default_engine_config()
    base = engine.product_config("TOMATOES")
    fallbacks = tuple(e for e in ("mid", "microprice") if e != estimator)
    mod = replace(base, fair_value_method=estimator, fair_value_fallbacks=fallbacks)
    return replace(engine, products={**engine.products, "TOMATOES": mod})


def _composite(row: SweepRow) -> tuple[float, float, int]:
    """(PnL, entry_edge, trade_count) -- all higher is better."""
    edge = row.avg_entry_edge if row.avg_entry_edge is not None else 0.0
    return (row.pnl, edge, row.trade_count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="optim_tomatoes_fv_sweep")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)

    all_rows: list[tuple[str, SweepRow]] = []

    for estimator, grid in SHORTLIST:
        grid_size = math.prod(len(v) for v in grid.values())
        print("=" * 60)
        print(f"Sweep: {estimator} ({grid_size} configs)")
        print("=" * 60)

        engine = _estimator_engine(estimator)
        report = build_parameter_sweep_report(
            replay,
            product="TOMATOES",
            grid=grid,
            config=engine,
            run_label=f"{args.label}_{estimator}",
        )
        write_parameter_sweep_report(report)
        print(report.summary_text(top_n=5))

        for row in report.rows:
            all_rows.append((estimator, row))
        print()

    # Merged cross-estimator ranking
    print("=" * 60)
    print("Merged cross-estimator ranking (top 15)")
    print("=" * 60)

    all_rows.sort(key=lambda x: _composite(x[1]), reverse=True)

    for i, (est, row) in enumerate(all_rows[:15], 1):
        edge = f"{row.avg_entry_edge:+.3f}" if row.avg_entry_edge is not None else "    n/a"
        mk = f"{row.maker_share * 100:.0f}%" if row.maker_share is not None else "n/a"
        hist = row.params.get("history_length", "-")
        print(
            f"  {i:>2}. {est:<14} maker={row.params.get('maker_edge')}, "
            f"taker={row.params.get('taker_edge')}, hist={hist}: "
            f"pnl={row.pnl:.2f}, edge={edge}, trades={row.trade_count}, "
            f"mk={mk}, near={row.steps_near_limit}, pos={row.final_position}"
        )


if __name__ == "__main__":
    main()

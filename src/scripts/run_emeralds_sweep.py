"""Staged EMERALDS parameter sweep.

Stage A: maker_edge x taker_edge (quote competitiveness)
Stage B: flatten_threshold x inventory_skew (inventory/recovery)

Stage B runs only on Stage A's top candidates.

Note: under the current local replay / fill model and the tested sweep
range, EMERALDS produced zero fills and zero PnL.  This strongly
suggests EMERALDS is not worth further optimization in the current
local tutorial replay setup.  It does NOT prove there is no EMERALDS
edge on the official site or under different fill behavior assumptions.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from src.backtest.parameter_sweep import (
    SweepRow,
    SweepValue,
    build_parameter_sweep_report,
    write_parameter_sweep_report,
)
from src.backtest.replay_engine import ReplayEngine
from src.core.config import default_engine_config

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")

STAGE_A_GRID: dict[str, list[SweepValue]] = {
    "maker_edge": [0.5, 1.0, 2.0, 3.0, 4.0],
    "taker_edge": [0.5, 1.0, 1.5, 2.0],
}

STAGE_B_GRID: dict[str, list[SweepValue]] = {
    "flatten_threshold": [0.65, 0.70, 0.75, 0.80],
    "inventory_skew": [4.0, 6.0, 8.0, 10.0],
}


def _composite_score(row: SweepRow) -> tuple[float, float, int]:
    """(PnL, entry_edge, trade_count) -- all higher is better."""
    edge = row.avg_entry_edge if row.avg_entry_edge is not None else 0.0
    return (row.pnl, edge, row.trade_count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="optim_emeralds")
    parser.add_argument("--top-n", type=int, default=3, help="Stage A winners to advance")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    engine_config = default_engine_config()

    # ---- Stage A: Quote Competitiveness ----
    print("=" * 60)
    print("Stage A: Quote competitiveness sweep")
    print("=" * 60)

    stage_a = build_parameter_sweep_report(
        replay,
        product="EMERALDS",
        grid=STAGE_A_GRID,
        run_label=f"{args.label}_stage_a",
    )
    write_parameter_sweep_report(stage_a)
    print(stage_a.summary_text())

    ranked_a = sorted(stage_a.rows, key=_composite_score, reverse=True)
    top_a = ranked_a[: args.top_n]

    print(f"\nStage A top {args.top_n}:")
    for i, row in enumerate(top_a, 1):
        edge = f"{row.avg_entry_edge:+.3f}" if row.avg_entry_edge is not None else "n/a"
        print(
            f"  {i}. maker={row.params['maker_edge']}, taker={row.params['taker_edge']}: "
            f"pnl={row.pnl:.2f}, edge={edge}, trades={row.trade_count}"
        )

    # ---- Stage B: Inventory/Recovery Refinement ----
    print()
    print("=" * 60)
    print("Stage B: Inventory/recovery refinement")
    print("=" * 60)

    base_product_config = engine_config.product_config("EMERALDS")
    all_b_rows: list[SweepRow] = []

    for rank, winner in enumerate(top_a, 1):
        candidate_config = replace(
            base_product_config,
            **cast(dict[str, Any], {k: v for k, v in winner.params.items()}),
        )
        modified_engine = replace(
            engine_config,
            products={**engine_config.products, "EMERALDS": candidate_config},
        )

        stage_b = build_parameter_sweep_report(
            replay,
            product="EMERALDS",
            grid=STAGE_B_GRID,
            config=modified_engine,
            run_label=f"{args.label}_stage_b_from_a{rank}",
        )
        write_parameter_sweep_report(stage_b)

        print(
            f"\nStage B from A#{rank} "
            f"(maker={winner.params['maker_edge']}, taker={winner.params['taker_edge']}):"
        )
        print(stage_b.summary_text(top_n=5))

        for row in stage_b.rows:
            merged_params = {**winner.params, **row.params}
            all_b_rows.append(
                SweepRow(
                    params=merged_params,
                    pnl=row.pnl,
                    trade_count=row.trade_count,
                    maker_share=row.maker_share,
                    final_position=row.final_position,
                    steps_near_limit=row.steps_near_limit,
                    avg_entry_edge=row.avg_entry_edge,
                )
            )

    # ---- Final ranking ----
    print()
    print("=" * 60)
    print("Combined ranking (all Stage B configs)")
    print("=" * 60)

    final_ranked = sorted(all_b_rows, key=_composite_score, reverse=True)
    print("\nTop 10:")
    for i, row in enumerate(final_ranked[:10], 1):
        edge = f"{row.avg_entry_edge:+.3f}" if row.avg_entry_edge is not None else "n/a"
        print(
            f"  {i}. maker={row.params.get('maker_edge')}, "
            f"taker={row.params.get('taker_edge')}, "
            f"skew={row.params.get('inventory_skew')}, "
            f"flat={row.params.get('flatten_threshold')}: "
            f"pnl={row.pnl:.2f}, edge={edge}, trades={row.trade_count}, "
            f"near_limit={row.steps_near_limit}"
        )

    print(f"\nBaseline: pnl={stage_a.baseline.pnl:.2f}, trades={stage_a.baseline.trade_count}")


if __name__ == "__main__":
    main()

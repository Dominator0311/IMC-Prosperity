"""Generate and persist a review pack for the tutorial replay.

Writes an enriched Phase 4a review pack under
``outputs/review_packs/<run_id>/``:

- ``summary.json`` / ``summary.txt`` — aggregate metrics, including
  markouts and entry edge with sample counts.
- ``trades.json`` — every fill with decision-time and fill-time
  context.
- ``series.json`` — step-indexed mid, fair-value and PnL series.
- ``manifest.json`` — pack provenance (run id, commit, data files,
  engine config, estimators, markout horizons).
- ``charts/*.png`` — price vs fair value, PnL over time, position
  over time, maker/taker decomposition, markout histograms, and a
  total PnL roll-up.
- ``notes.md`` — structured review template for the human workflow.

Pass ``--label`` to tag the run, ``--no-charts`` to skip the chart
render (useful for quick headless dumps).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backtest.replay_engine import ReplayEngine
from src.backtest.reporting import write_review_pack
from src.backtest.simulator import BacktestSimulator
from src.trader import Trader

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="tutorial_round_1", help="run label")
    parser.add_argument(
        "--no-charts",
        action="store_true",
        help="skip chart rendering (still writes metrics, trades, series, manifest)",
    )
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files found in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    trader = Trader()
    simulator = BacktestSimulator(trader=trader)
    result = simulator.run(replay)

    data_files = [str(path) for path in (*price_files, *trade_files)]
    directory = write_review_pack(
        result,
        run_label=args.label,
        render_charts=not args.no_charts,
        engine_config=trader.config,
        data_files=data_files,
    )

    print(f"Wrote review pack to {directory}")
    print()
    print(result.summary_table())
    print()
    print("Artifacts:")
    for name in sorted(p.name for p in directory.iterdir()):
        print(f"  {name}")
    if not args.no_charts:
        charts_dir = directory / "charts"
        if charts_dir.is_dir():
            print(f"  {charts_dir.name}/")
            for name in sorted(p.name for p in charts_dir.iterdir()):
                print(f"    {name}")


if __name__ == "__main__":
    main()

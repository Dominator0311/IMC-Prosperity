"""Compare fair-value estimators on the tutorial replay data.

Writes a metrics report under ``outputs/fair_value_comparison/<run_id>``
and prints the summary table to stdout.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.backtest.fair_value_compare import build_fair_value_report, write_fair_value_report
from src.backtest.replay_engine import ReplayEngine

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="tutorial_round_1", help="run label")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files found in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    report = build_fair_value_report(replay, run_label=args.label)
    directory = write_fair_value_report(report)

    print(f"Wrote fair value comparison report to {directory}")
    print()
    print(report.summary_text())


if __name__ == "__main__":
    main()

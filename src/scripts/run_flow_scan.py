"""Offline flow-scan review for the tutorial replay.

Runs the ``FlowAnalyzer`` at verbosity 2 against all tutorial data and
writes a structured report under ``outputs/flow_scans/<label>/``:

- ``flow_scan_report.json`` — per-product summary (total steps, flag
  histogram, peak flow score, extrema hit counts) plus every flagged
  step for quick inspection.
- ``flagged_steps.csv`` — flat CSV of flagged steps for scripting.

Usage::

    python -m src.scripts.run_flow_scan --label phase7_tutorial
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.backtest.replay_engine import ReplayEngine
from src.core.config import default_engine_config
from src.core.types import ScannerConfig
from src.trader import Trader

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")
_OUTPUT_DIR = Path("outputs/flow_scans")


@dataclass
class _ProductSummary:
    steps_scanned: int = 0
    flag_histogram: Counter[str] = field(default_factory=Counter)
    peak_flow_score: float = 0.0
    min_flow_score: float = 0.0
    near_high_count: int = 0
    near_low_count: int = 0
    flagged_step_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps_scanned": self.steps_scanned,
            "flag_histogram": dict(self.flag_histogram),
            "peak_flow_score": self.peak_flow_score,
            "min_flow_score": self.min_flow_score,
            "near_high_count": self.near_high_count,
            "near_low_count": self.near_low_count,
            "flagged_step_count": self.flagged_step_count,
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the flow scanner offline and write a review report.",
    )
    parser.add_argument("--label", default="phase7_tutorial", help="run label")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files found in {_TUTORIAL_DIR}")

    # Override scanner to verbosity=2 for full reports.
    base_config = default_engine_config()
    scan_cfg = ScannerConfig(enabled=True, verbosity=2)
    config = dataclasses.replace(base_config, scanner_config=scan_cfg)

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    trader = Trader(config=config)

    # Drive the trader step-by-step, collecting scanner events after each.
    # The simulator clears logger.events between steps, so we collect here.
    flagged_rows: list[dict[str, Any]] = []
    per_product: dict[str, _ProductSummary] = {}
    trader_data = ""

    for step in replay.steps:
        state = ReplayEngine.build_trading_state(
            step,
            trader_data=trader_data,
            position={},
            own_trades={},
        )
        _, _, trader_data = trader.run(state)

        for event in trader.logger.events:
            fr = event.get("flow_report")
            product = event.get("product")
            if product is None or fr is None or not isinstance(fr, dict):
                continue

            product_str = str(product)
            if product_str not in per_product:
                per_product[product_str] = _ProductSummary()
            summary = per_product[product_str]
            summary.steps_scanned += 1

            flow_score = float(fr.get("flow_score", 0.0))
            summary.peak_flow_score = max(summary.peak_flow_score, flow_score)
            summary.min_flow_score = min(summary.min_flow_score, flow_score)

            if fr.get("near_high"):
                summary.near_high_count += 1
            if fr.get("near_low"):
                summary.near_low_count += 1

            flags = fr.get("flags", [])
            for flag in flags:
                summary.flag_histogram[str(flag)] += 1

            if flags:
                summary.flagged_step_count += 1
                flagged_rows.append(
                    {
                        "timestamp": event.get("timestamp"),
                        "product": product_str,
                        "flags": "|".join(str(f) for f in flags),
                        "net_flow": fr.get("net_flow"),
                        "flow_score": flow_score,
                        "near_high": fr.get("near_high"),
                        "near_low": fr.get("near_low"),
                    }
                )

        # Clear events so they don't accumulate in the logger's buffer.
        trader.logger.events.clear()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{stamp}_{args.label}" if args.label else stamp
    out_dir = _OUTPUT_DIR / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "run_label": args.label,
        "generated_at": datetime.now(UTC).isoformat(),
        "per_product": {k: v.to_dict() for k, v in per_product.items()},
        "flagged_steps": flagged_rows,
    }
    (out_dir / "flow_scan_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str)
    )

    if flagged_rows:
        with (out_dir / "flagged_steps.csv").open("w", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "timestamp",
                    "product",
                    "flags",
                    "net_flow",
                    "flow_score",
                    "near_high",
                    "near_low",
                ],
            )
            writer.writeheader()
            writer.writerows(flagged_rows)

    print(f"Wrote flow scan report to {out_dir}")
    print()
    for product, summary in sorted(per_product.items()):
        print(f"  {product}:")
        print(f"    steps scanned:    {summary.steps_scanned}")
        print(f"    flagged steps:    {summary.flagged_step_count}")
        print(f"    peak flow score:  {summary.peak_flow_score}")
        print(f"    min flow score:   {summary.min_flow_score}")
        print(f"    near-high hits:   {summary.near_high_count}")
        print(f"    near-low hits:    {summary.near_low_count}")
        if summary.flag_histogram:
            print(f"    flag histogram:   {dict(summary.flag_histogram)}")
    if flagged_rows:
        print(f"\n  {len(flagged_rows)} flagged steps written to flagged_steps.csv")


if __name__ == "__main__":
    main()

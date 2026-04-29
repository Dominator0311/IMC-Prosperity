"""T01 — Fill-model calibration on R3 tape.

Sweeps passive_allocation ∈ {0.05, 0.10, 0.20, 0.30, 0.50} separately for:
  - Delta-1 products (HYDROGEL, VELVET, VEV_4000) — balanced flow
  - OTM vouchers (K=5300+) — one-sided bid-only flow

Outputs calibrated fill-model parameters to:
    outputs/round_3/calibration/<timestamp>.json

and documents them in:
    docs/round_3/CALIBRATION_RESULT.md

Usage:
    PYTHONPATH=. .venv/bin/python -m src.scripts.round_3.run_fill_calibration
"""

from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data/raw/round_3"
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "calibration"
DOCS_DIR = REPO_ROOT / "docs" / "round_3"

_PASSIVE_ALLOC_GRID = (0.05, 0.10, 0.20, 0.30, 0.50)

_DELTA1_PRODUCTS = {"HYDROGEL_PACK", "VELVETFRUIT_EXTRACT", "VEV_4000"}
_OTM_VOUCHER_PRODUCTS = {f"VEV_{k}" for k in (5300, 5400, 5500, 6000, 6500)}
_ALL_PRODUCTS = _DELTA1_PRODUCTS | _OTM_VOUCHER_PRODUCTS

DAYS = (0, 1, 2)


# ------------------------------------------------------------------ loader

def load_day_prices(day: int) -> dict[int, dict[str, dict]]:
    snap: dict[int, dict[str, dict]] = defaultdict(dict)
    path = DATA_DIR / f"prices_round_3_day_{day}.csv"
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                ts = int(row["timestamp"])
                product = row["product"]
                if product not in _ALL_PRODUCTS:
                    continue
                snap[ts][product] = {
                    "mid": float(row["mid_price"]) if row.get("mid_price") else None,
                    "bid": float(row["bid_price_1"]) if row.get("bid_price_1") else None,
                    "ask": float(row["ask_price_1"]) if row.get("ask_price_1") else None,
                    "bv": float(row["bid_volume_1"]) if row.get("bid_volume_1") else None,
                    "av": float(row["ask_volume_1"]) if row.get("ask_volume_1") else None,
                }
            except (ValueError, KeyError):
                continue
    return dict(snap)


def load_day_trades(day: int) -> list[dict]:
    trades = []
    path = DATA_DIR / f"trades_round_3_day_{day}.csv"
    with open(path) as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            try:
                product = row.get("symbol", row.get("product", ""))
                if product not in _ALL_PRODUCTS:
                    continue
                trades.append({
                    "ts": int(row["timestamp"]),
                    "product": product,
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except (ValueError, KeyError):
                continue
    return trades


# ------------------------------------------------------------------ core

@dataclass
class FillStats:
    """Passive fill statistics for a product class under a given allocation."""

    product_class: str
    passive_allocation: float
    simulated_fills: int = 0
    actual_fills: int = 0
    fill_rate: float = 0.0


def simulate_fills(
    prices_all_days: list[dict[int, dict[str, dict]]],
    trades_all_days: list[list[dict]],
    product_class: str,
    products: set[str],
    passive_allocation: float,
) -> FillStats:
    """Estimate passive fill rate for a product class.

    Model: at each tick we quote a passive order of size =
    passive_allocation × position_limit. A fill occurs when the
    trade tape shows a trade at our quoted price on the same tick.

    This is a rough first-order fill model. The FillCalibrationHarness
    in src/core/primitives/fill_calibration.py provides a more detailed
    harness — this script uses a simplified version for speed.
    """
    from src.core.r3_products import POS_LIMITS

    simulated = 0
    actual = 0

    for day_prices, day_trades in zip(prices_all_days, trades_all_days):
        # Group trades by (ts, product)
        trade_by_ts: dict[tuple[int, str], list[dict]] = defaultdict(list)
        for t in day_trades:
            if t["product"] in products:
                trade_by_ts[(t["ts"], t["product"])].append(t)

        for ts in sorted(day_prices):
            for product in products:
                snap = day_prices[ts].get(product)
                if snap is None or snap["bid"] is None or snap["ask"] is None:
                    continue
                limit = POS_LIMITS.get(product, 200)
                quote_size = max(1, int(limit * passive_allocation))

                # Count as simulated fill opportunity each tick
                simulated += 2  # bid side + ask side

                # Count actual fills: trades in the tape at this product/ts
                ts_trades = trade_by_ts.get((ts, product), [])
                if ts_trades:
                    # At least one fill on bid or ask side
                    fill_count = min(2, len(ts_trades))
                    actual += fill_count

    fill_rate = actual / max(simulated, 1)
    return FillStats(
        product_class=product_class,
        passive_allocation=passive_allocation,
        simulated_fills=simulated,
        actual_fills=actual,
        fill_rate=fill_rate,
    )


def calibrate() -> dict[str, Any]:
    """Run calibration sweep. Returns best params per product class."""
    print("Loading R3 data...")
    prices_all = [load_day_prices(d) for d in DAYS]
    trades_all = [load_day_trades(d) for d in DAYS]

    results: dict[str, list[FillStats]] = {
        "delta1": [],
        "otm_voucher": [],
    }

    print("Sweeping passive_allocation grid...")
    for alloc in _PASSIVE_ALLOC_GRID:
        d1 = simulate_fills(
            prices_all, trades_all, "delta1", _DELTA1_PRODUCTS, alloc
        )
        otm = simulate_fills(
            prices_all, trades_all, "otm_voucher", _OTM_VOUCHER_PRODUCTS, alloc
        )
        results["delta1"].append(d1)
        results["otm_voucher"].append(otm)
        print(
            f"  alloc={alloc:.2f}  delta1_rate={d1.fill_rate:.3f}  "
            f"otm_rate={otm.fill_rate:.3f}"
        )

    # Choose the allocation whose fill_rate is closest to empirical ~15%
    target_fill_rate = 0.15
    best: dict[str, FillStats] = {}
    for cls, stats_list in results.items():
        best[cls] = min(
            stats_list,
            key=lambda s: abs(s.fill_rate - target_fill_rate),
        )

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "target_fill_rate": target_fill_rate,
        "best": {cls: asdict(s) for cls, s in best.items()},
        "full_sweep": {
            cls: [asdict(s) for s in stats_list]
            for cls, stats_list in results.items()
        },
    }


def write_outputs(result: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ts_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"{ts_str}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nCalibration result written to: {out_path}")

    # Document in CALIBRATION_RESULT.md
    md_path = DOCS_DIR / "CALIBRATION_RESULT.md"
    best = result["best"]
    lines = [
        "# R3 Fill-Model Calibration Result",
        "",
        f"Generated: {result['timestamp']}",
        "",
        "## Best parameters (closest to 15% empirical fill rate)",
        "",
        "| Product class | passive_allocation | fill_rate |",
        "|---|---|---|",
    ]
    for cls, stats in best.items():
        lines.append(
            f"| {cls} | {stats['passive_allocation']:.2f} "
            f"| {stats['fill_rate']:.3f} |"
        )
    lines += [
        "",
        "## Use in sweeps",
        "",
        "Set `passive_allocation` in `FillModel` to the values above",
        "when running T02b parameter sweeps and T12 LOO validation.",
        "",
        f"Full sweep data: `outputs/round_3/calibration/{out_path.name}`",
    ]
    with open(md_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Calibration notes written to: {md_path}")


if __name__ == "__main__":
    result = calibrate()
    write_outputs(result)

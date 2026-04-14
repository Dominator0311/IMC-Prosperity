"""Phase 5: per-candidate review-pack diagnostic tables.

Reads each Round-1 review pack in
``outputs/round_1/review_packs/`` and computes:

- per-day PnL + per-day trade count for the product of interest
- lag-1 autocorrelation of step-level PnL deltas (is edge clustered?)
- per-day EOD position
- maker / taker fill share
- fraction of PnL that accrues in the last 20 % of the run (a simple
  "time-concentration" check)

Emits a compact Markdown table suitable for the per-candidate
interpretation notes. Does NOT re-run any simulator.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_pack_stats
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.scripts.round_1.run_round1_review_packs import CANDIDATES

_DEFAULT_PACKS_DIR = Path("outputs/round_1/review_packs")
_DEFAULT_OUT_FILE = Path("outputs/round_1/notes/phase5_pack_stats.md")


def _latest_pack(root: Path, label: str) -> Path | None:
    matches = [p for p in root.glob("*") if p.is_dir() and label in p.name]
    return max(matches, key=lambda p: p.name) if matches else None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return cov / (var_x**0.5 * var_y**0.5)


def _analyze(pack: Path, product: str) -> dict[str, Any]:
    summary = json.loads((pack / "summary.json").read_text())
    trades = json.loads((pack / "trades.json").read_text())["trades"]
    series = json.loads((pack / "series.json").read_text())

    # Per-product aggregates (dict keyed by product name)
    per_product = summary.get("per_product", {}) or {}
    pr = per_product.get(product, {})

    # Per-day PnL from pnl_series + pnl_keys
    pnl_vals = [float(v) for _, v in series.get("pnl_series", {}).get(product, [])]
    pnl_keys = series.get("pnl_keys", {}).get(product, [])
    per_day_last: dict[int, float] = {}
    for key, val in zip(pnl_keys, pnl_vals, strict=True):
        day = key[0]
        if day is None:
            continue
        per_day_last[day] = val

    days_sorted = sorted(per_day_last)
    per_day_pnl: dict[int, float] = {}
    prev = 0.0
    for d in days_sorted:
        per_day_pnl[d] = per_day_last[d] - prev
        prev = per_day_last[d]

    # Clustering diagnostics
    deltas = [b - a for a, b in zip(pnl_vals, pnl_vals[1:], strict=False)]
    autocorr = _pearson(deltas[:-1], deltas[1:]) if len(deltas) >= 2 else None

    # Time-concentration: PnL in last 20 % of steps
    total_pnl = pnl_vals[-1] if pnl_vals else 0.0
    if pnl_vals and len(pnl_vals) >= 5:
        split_idx = int(0.8 * len(pnl_vals))
        pnl_before = pnl_vals[split_idx - 1]
        pnl_tail = total_pnl - pnl_before
        tail_share = pnl_tail / total_pnl if total_pnl != 0 else None
    else:
        tail_share = None

    # EOD positions from trades
    eod_pos_by_day: dict[int, int] = {}
    running = 0
    product_trades = sorted(
        (t for t in trades if t.get("product") == product),
        key=lambda t: (t.get("fill_day") or 0, t.get("fill_timestamp") or 0),
    )
    for t in product_trades:
        qty = int(t.get("quantity", 0))
        running += qty if t.get("side") == "buy" else -qty
        d = t.get("fill_day")
        if d is not None:
            eod_pos_by_day[d] = running

    trade_count = pr.get("trade_count", 0)
    maker_qty = pr.get("maker_trade_quantity", 0)
    taker_qty = pr.get("taker_trade_quantity", 0)
    maker_share = (maker_qty / (maker_qty + taker_qty)) if (maker_qty + taker_qty) > 0 else None

    return {
        "product": product,
        "total_pnl": total_pnl,
        "per_day_pnl": per_day_pnl,
        "eod_pos_by_day": eod_pos_by_day,
        "lag1_autocorr": autocorr,
        "tail20_pnl_share": tail_share,
        "trade_count": trade_count,
        "maker_share": maker_share,
        "final_position": pr.get("final_position"),
        "steps_near_limit": pr.get("steps_near_limit"),
        "avg_entry_edge": pr.get("avg_entry_edge"),
        "avg_markout_1": pr.get("avg_markout_1"),
        "avg_markout_5": pr.get("avg_markout_5"),
        "avg_markout_20": pr.get("avg_markout_20"),
    }


def _fmt(value: float | int | None, *, digits: int = 0, signed: bool = False) -> str:
    if value is None:
        return "—"
    fmt = f"+.{digits}f" if signed else f".{digits}f"
    try:
        return format(float(value), fmt)
    except (TypeError, ValueError):
        return "—"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs-dir", type=Path, default=_DEFAULT_PACKS_DIR)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT_FILE)
    args = parser.parse_args()

    rows: list[tuple[str, dict[str, Any]]] = []
    for label, info in CANDIDATES.items():
        pack = _latest_pack(args.packs_dir, label)
        if pack is None:
            print(f"[skip] no pack for {label}")
            continue
        analysis = _analyze(pack, info["product"])
        analysis["pack"] = str(pack)
        rows.append((label, analysis))

    lines: list[str] = [
        "# Round 1 — Phase 5 per-candidate review-pack diagnostics",
        "",
        "All figures derive from the review packs under "
        f"`{args.packs_dir}` (one pack per candidate, re-run with "
        "`run_round1_review_packs.py`).",
        "",
        "## Headline table",
        "",
        "| Candidate | Product | Total PnL | Day -2 | Day -1 | Day 0 | Tail-20% share | Lag-1 autocorr | Maker % | Near-limit | Edge | mk-1 | mk-5 | mk-20 |",
        "|-----------|---------|-----------|--------|--------|-------|----------------|----------------|---------|------------|------|------|------|-------|",
    ]
    for label, a in rows:
        day_pnl = a["per_day_pnl"]
        lines.append(
            f"| {label} "
            f"| {a['product']} "
            f"| {_fmt(a['total_pnl'], signed=True)} "
            f"| {_fmt(day_pnl.get(-2), signed=True)} "
            f"| {_fmt(day_pnl.get(-1), signed=True)} "
            f"| {_fmt(day_pnl.get(0), signed=True)} "
            f"| {_fmt((a['tail20_pnl_share'] or 0) * 100, digits=1)}% "
            f"| {_fmt(a['lag1_autocorr'], digits=3, signed=True)} "
            f"| {_fmt((a['maker_share'] or 0) * 100, digits=1)}% "
            f"| {_fmt(a['steps_near_limit'])} "
            f"| {_fmt(a['avg_entry_edge'], digits=2, signed=True)} "
            f"| {_fmt(a['avg_markout_1'], digits=2, signed=True)} "
            f"| {_fmt(a['avg_markout_5'], digits=2, signed=True)} "
            f"| {_fmt(a['avg_markout_20'], digits=2, signed=True)} |"
        )

    lines += [
        "",
        "## EOD positions per candidate",
        "",
        "| Candidate | Day -2 EOD pos | Day -1 EOD pos | Day 0 EOD pos |",
        "|-----------|---------------:|---------------:|--------------:|",
    ]
    for label, a in rows:
        eod = a["eod_pos_by_day"]
        lines.append(
            f"| {label} | {eod.get(-2, '—')} | {eod.get(-1, '—')} | {eod.get(0, '—')} |"
        )

    lines += [
        "",
        "## Interpretation keys",
        "- **Tail-20% share**: fraction of total PnL that accrued in the last 20 % of simulation steps. ≈20 % indicates steady accrual; >50 % flags time-clustered edge.",
        "- **Lag-1 autocorr**: step-to-step PnL autocorrelation. ≈0 = independent, >0 = bursty clusters, <0 = mean-reverting within-day (typical for market-making on noisy mids).",
        "- **Maker %**: fraction of traded quantity executed as a maker fill. Phase-1 replay fill model rewards both maker and taker paths; watch how this shifts between candidates.",
        "- **EOD position**: signed end-of-day inventory. PEPPER mids are continuous across day boundaries in the sample data, so EOD exposure only matters if the drift reverses or halts intra-day.",
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()

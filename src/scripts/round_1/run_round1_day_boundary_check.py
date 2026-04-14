"""Phase 5: PEPPER day-boundary / end-of-day diagnostic.

For each PEPPER shortlist candidate, walks the review pack's
``trades.json`` + ``series.json`` and answers:

1. What is the **end-of-day position** on each day?
2. How much PnL accrues in the **last K steps** of each day (the
   "overnight-exposed" slice)?
3. What would PnL look like under a **hypothetical
   flatten-before-boundary overlay** — force the book flat at a
   chosen per-day cutoff step, using the last observed mid as the
   flatten price?
4. What is the per-day PnL and how clustered is the PnL time series
   (lag-1 autocorrelation of the per-step PnL series)?

This is a **post-hoc** analysis; it never re-runs the simulator. It
reads the packs written by ``run_round1_review_packs.py``.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_day_boundary_check \
        [--packs-dir outputs/round_1/review_packs] \
        [--cutoff-step 9800] [--tail-steps 200]
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PRODUCT = "INTARIAN_PEPPER_ROOT"
_DEFAULT_PACKS_DIR = Path("outputs/round_1/review_packs")
_DEFAULT_OUT_DIR = Path("outputs/round_1/notes")

# A single IMC replay day spans 10 000 snapshots at step 100, i.e.
# timestamps 0, 100, 200, ..., 999 900 per day. So step-index *i* maps
# to timestamp *i × 100*, and the day covers 10 000 steps.
_STEPS_PER_DAY = 10_000
_TIMESTAMP_STEP = 100
_DAY_END_TIMESTAMP = _STEPS_PER_DAY * _TIMESTAMP_STEP  # 1 000 000


@dataclass
class _PerDay:
    pnl_at_end_of_day: float | None = None
    position_at_end_of_day: int = 0
    tail_pnl: float = 0.0
    trade_count: int = 0
    trades_in_tail: int = 0


@dataclass
class _CandidateAnalysis:
    pack: str
    last_run_label: str
    per_day: dict[int, _PerDay] = field(default_factory=dict)
    overall_pnl: float | None = None
    pnl_lag1_autocorr: float | None = None
    flatten_overlay_pnl_delta_by_day: dict[int, float] = field(default_factory=dict)
    flatten_overlay_total_delta: float = 0.0


# ---------------------------------------------------------------- helpers


def _latest_pack_dir(root: Path, label_prefix: str) -> Path | None:
    candidates = [p for p in root.glob("*") if p.is_dir() and label_prefix in p.name]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)


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


def _load_pack(pack_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = json.loads((pack_dir / "manifest.json").read_text())
    trades = json.loads((pack_dir / "trades.json").read_text())
    series = json.loads((pack_dir / "series.json").read_text())
    return manifest, trades, series


# ---------------------------------------------------------------- analysis


def _analyze_pack(pack_dir: Path, *, tail_steps: int, cutoff_step: int) -> _CandidateAnalysis:
    """Compute per-day diagnostics for PEPPER from a review pack."""
    manifest, trades_doc, series_doc = _load_pack(pack_dir)

    analysis = _CandidateAnalysis(
        pack=str(pack_dir),
        last_run_label=str(manifest.get("run_label") or pack_dir.name),
    )

    # ---- Per-day position trajectory from the trade tape ---------------
    pepper_trades = [t for t in trades_doc.get("trades", []) if t.get("product") == _PRODUCT]

    # A single pass: track running position and cash across trades in
    # order of fill, then bucket the running position / cumulative
    # realized PnL by day.
    pepper_trades.sort(key=lambda t: (t.get("fill_day") or 0, t.get("fill_timestamp") or 0))

    position = 0
    cash = 0.0
    pnl_at_day_end: dict[int, float] = {}
    position_at_day_end: dict[int, int] = {}
    trades_by_day: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for t in pepper_trades:
        side = t.get("side")
        qty = int(t.get("quantity", 0))
        price = float(t.get("price", 0.0))
        signed = qty if side == "buy" else -qty
        position += signed
        cash -= signed * price
        day = t.get("fill_day")
        trades_by_day[day].append(t)

    # Use the pack's mid_series to get the end-of-day mid per day so we
    # can mark the position to market at the close.
    mid_series_pepper: list[list[float]] = series_doc.get("mid_series", {}).get(_PRODUCT, [])
    mid_keys_pepper: list[list[Any]] = series_doc.get("mid_keys", {}).get(_PRODUCT, [])

    # Build per-day last mid + cumulative PnL by walking mids step-by-step.
    # mid_series entries are [timestamp, mid]; mid_keys entries are [day, timestamp]
    pnl_series_pepper = series_doc.get("pnl_series", {}).get(_PRODUCT, [])
    pnl_keys_pepper = series_doc.get("pnl_keys", {}).get(_PRODUCT, [])

    last_mid_for_day: dict[int, float] = {}
    for (_, mid_val), key in zip(mid_series_pepper, mid_keys_pepper, strict=True):
        day = key[0]
        if day is not None:
            last_mid_for_day[day] = float(mid_val)

    # Cumulative PnL at each step (pack's pnl_series already tracks
    # mark-to-market including open position at that step).
    pnl_at_each_step: dict[tuple[int, int], float] = {}
    for (ts, val), key in zip(pnl_series_pepper, pnl_keys_pepper, strict=True):
        day, timestamp = key[0], key[1]
        pnl_at_each_step[(day, timestamp)] = float(val)

    # For each day, find the last pnl_series entry with that day, and
    # the position trajectory replayed from trades up to that timestamp.
    all_days = sorted({key[0] for key in pnl_keys_pepper if key[0] is not None})
    for day in all_days:
        day_keys = [k for k in pnl_keys_pepper if k[0] == day]
        if not day_keys:
            continue
        last_key = max(day_keys, key=lambda k: k[1])
        pnl_at_day_end[day] = pnl_at_each_step.get((last_key[0], last_key[1]))

    # End-of-day position via trade replay in fill order.
    pos_traj = 0
    for t in pepper_trades:
        qty = int(t.get("quantity", 0))
        side = t.get("side")
        pos_traj += qty if side == "buy" else -qty
        day = t.get("fill_day")
        if day is not None:
            position_at_day_end[day] = pos_traj

    for day in all_days:
        pd = analysis.per_day.setdefault(day, _PerDay())
        pd.pnl_at_end_of_day = pnl_at_day_end.get(day)
        pd.position_at_end_of_day = position_at_day_end.get(day, 0)
        pd.trade_count = len(trades_by_day.get(day, []))

    # ---- Tail-of-day PnL accrual -------------------------------------
    tail_cutoff_timestamp = _DAY_END_TIMESTAMP - (tail_steps * _TIMESTAMP_STEP)
    tail_pnl_by_day: dict[int, float] = {}
    for day in all_days:
        day_keys = sorted(((k[0], k[1]) for k in pnl_keys_pepper if k[0] == day), key=lambda k: k[1])
        if not day_keys:
            continue
        # Tail PnL = pnl at day end - pnl at tail-cutoff step
        last_key = day_keys[-1]
        # Find the closest key at-or-before the tail_cutoff_timestamp.
        pre_tail_keys = [k for k in day_keys if k[1] < tail_cutoff_timestamp]
        if not pre_tail_keys:
            continue
        pre_tail_key = pre_tail_keys[-1]
        tail_delta = pnl_at_each_step.get(last_key, 0.0) - pnl_at_each_step.get(pre_tail_key, 0.0)
        tail_pnl_by_day[day] = tail_delta

    for day, tail in tail_pnl_by_day.items():
        analysis.per_day.setdefault(day, _PerDay()).tail_pnl = tail
        analysis.per_day[day].trades_in_tail = sum(
            1
            for t in trades_by_day.get(day, [])
            if (t.get("fill_timestamp") or 0) >= tail_cutoff_timestamp
        )

    # ---- Hypothetical flatten-before-boundary overlay ----------------
    # Cutoff_step is in "steps from day start" (0..99). Convert to
    # timestamp: cutoff_step * 100. For each day, if the candidate's
    # position at that cutoff is nonzero, the overlay flattens it at
    # the mid observed at that step.
    cutoff_timestamp = cutoff_step * _TIMESTAMP_STEP
    overlay_delta_total = 0.0
    overlay_by_day: dict[int, float] = {}

    for day in all_days:
        # Position at cutoff_step: replay trades with fill_timestamp < cutoff_timestamp.
        pos_at_cutoff = 0
        for t in trades_by_day.get(day, []):
            fill_ts = int(t.get("fill_timestamp") or 0)
            if fill_ts < cutoff_timestamp:
                qty = int(t.get("quantity", 0))
                side = t.get("side")
                pos_at_cutoff += qty if side == "buy" else -qty
        # Position at cutoff = pos_at_prev_day_end + pos_at_cutoff
        prev_days = [d for d in all_days if d < day]
        pos_carry = position_at_day_end.get(prev_days[-1], 0) if prev_days else 0
        total_pos_at_cutoff = pos_carry + pos_at_cutoff

        # End-of-day mid (as the overlay's "close" price).
        mid_close = last_mid_for_day.get(day)
        # Mid at cutoff timestamp (approximation: closest mid with timestamp <= cutoff).
        day_mid_pairs = [
            (k[1], mid_series_pepper[i][1])
            for i, k in enumerate(mid_keys_pepper)
            if k[0] == day
        ]
        if not day_mid_pairs or mid_close is None:
            continue
        mid_at_cutoff = next(
            (mid for ts, mid in reversed(day_mid_pairs) if ts <= cutoff_timestamp),
            day_mid_pairs[-1][1],
        )

        # Flattening at cutoff removes (total_pos_at_cutoff) units of exposure.
        # Under the **actual** trajectory, those units continued to trade
        # until EOD. The overlay delta is the difference between:
        #   - realized PnL if we'd flattened at mid_at_cutoff
        #   - realized PnL actually earned on that position through EOD
        # Approximation: the actual PnL change from cutoff to close for
        # the open position is `total_pos_at_cutoff * (mid_close - mid_at_cutoff)`
        # (all residual trades assumed to round-trip; this understates
        # activity but is directionally correct). The overlay removes
        # this exposure by closing at mid_at_cutoff.
        exposure_delta = total_pos_at_cutoff * (mid_close - mid_at_cutoff)
        overlay_delta = -exposure_delta  # overlay's marginal impact on final PnL
        overlay_by_day[day] = overlay_delta
        overlay_delta_total += overlay_delta

    analysis.flatten_overlay_pnl_delta_by_day = overlay_by_day
    analysis.flatten_overlay_total_delta = overlay_delta_total

    # ---- PnL clustering (lag-1 autocorrelation of step deltas) -------
    if pnl_series_pepper:
        cum_pnl = [float(v) for _, v in pnl_series_pepper]
        deltas = [b - a for a, b in zip(cum_pnl, cum_pnl[1:], strict=False)]
        if len(deltas) >= 2:
            analysis.pnl_lag1_autocorr = _pearson(deltas[:-1], deltas[1:])
        analysis.overall_pnl = cum_pnl[-1]

    return analysis


# ---------------------------------------------------------------- entry


def _pepper_candidate_labels() -> list[str]:
    return [
        "pepper_c1_linear_drift_h32_t20_f08",
        "pepper_c1b_linear_drift_h32_t20_f07",
        "pepper_c2_linear_drift_h32_skew1_f09",
        "pepper_c3_linear_drift_h32_skew4_f08",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs-dir", type=Path, default=_DEFAULT_PACKS_DIR)
    parser.add_argument("--out-dir", type=Path, default=_DEFAULT_OUT_DIR)
    parser.add_argument(
        "--cutoff-step",
        type=int,
        default=9800,
        help=(
            "Hypothetical flatten cutoff, in steps-from-day-start "
            "(0–9999). Default 9800 = last 2 %% of the day."
        ),
    )
    parser.add_argument(
        "--tail-steps",
        type=int,
        default=200,
        help=(
            "Tail-of-day window size in steps for PnL accrual stats. "
            "Default 200 = last 2 %% of the day."
        ),
    )
    args = parser.parse_args()

    labels = _pepper_candidate_labels()
    rows: list[dict[str, Any]] = []

    for label in labels:
        pack_dir = _latest_pack_dir(args.packs_dir, label)
        if pack_dir is None:
            print(f"[skip] no review pack found for {label} under {args.packs_dir}")
            continue

        analysis = _analyze_pack(
            pack_dir,
            tail_steps=args.tail_steps,
            cutoff_step=args.cutoff_step,
        )
        rows.append(
            {
                "label": label,
                "pack": str(pack_dir),
                "overall_pnl": analysis.overall_pnl,
                "pnl_lag1_autocorr": analysis.pnl_lag1_autocorr,
                "per_day": {
                    day: {
                        "pnl_at_end_of_day": pd.pnl_at_end_of_day,
                        "position_at_end_of_day": pd.position_at_end_of_day,
                        "tail_pnl": pd.tail_pnl,
                        "trades_in_tail": pd.trades_in_tail,
                        "trade_count": pd.trade_count,
                    }
                    for day, pd in analysis.per_day.items()
                },
                "flatten_overlay_pnl_delta_by_day": analysis.flatten_overlay_pnl_delta_by_day,
                "flatten_overlay_total_delta": analysis.flatten_overlay_total_delta,
            }
        )

    # Summary table (stdout + markdown)
    lines = [
        "# Round 1 — PEPPER day-boundary / end-of-day diagnostic",
        "",
        f"Packs root: `{args.packs_dir}`",
        f"Tail window: last {args.tail_steps} steps per day",
        f"Flatten overlay cutoff: step {args.cutoff_step} of 100",
        "",
        "## Per-candidate summary",
        "",
        "| Candidate | Overall PnL | Lag-1 autocorr | EOD pos d-2 | EOD pos d-1 | EOD pos d0 | Tail PnL d-2 | Tail PnL d-1 | Tail PnL d0 | Overlay total delta |",
        "|-----------|-------------|----------------|-------------|-------------|------------|--------------|--------------|-------------|---------------------|",
    ]
    for row in rows:
        pd_2 = row["per_day"].get(-2, {})
        pd_1 = row["per_day"].get(-1, {})
        pd_0 = row["per_day"].get(0, {})
        lines.append(
            f"| {row['label']} "
            f"| {_fmt_f(row['overall_pnl'])} "
            f"| {_fmt_f(row['pnl_lag1_autocorr'], digits=3)} "
            f"| {pd_2.get('position_at_end_of_day', '—')} "
            f"| {pd_1.get('position_at_end_of_day', '—')} "
            f"| {pd_0.get('position_at_end_of_day', '—')} "
            f"| {_fmt_f(pd_2.get('tail_pnl'))} "
            f"| {_fmt_f(pd_1.get('tail_pnl'))} "
            f"| {_fmt_f(pd_0.get('tail_pnl'))} "
            f"| {_fmt_f(row['flatten_overlay_total_delta'])} |"
        )

    lines.append("")
    lines.append("## Interpretation guide")
    lines.append("")
    lines.append(
        "- **EOD position**: large absolute values exposed to the +1 000 overnight jump. "
        "Sign matters: long before a jump earns the +1 000, short before a jump loses 1 000 per unit."
    )
    lines.append(
        "- **Tail PnL**: PnL accrued in the last tail-steps window of each day. "
        "Big negatives suggest adverse selection near close; big positives (and especially if they add up "
        "to most of the day's PnL) suggest the strategy makes most of its money riding the drift into close."
    )
    lines.append(
        "- **Lag-1 autocorr of step PnL**: near 0 = uncorrelated (steady); strongly positive = clustered "
        "(PnL arrives in bursts); negative = mean-reverting bar-by-bar."
    )
    lines.append(
        "- **Overlay total delta**: signed PnL impact if we'd flattened at the cutoff step using the mid at "
        "that moment. Positive means a pre-close flatten would have helped; negative means it would have cost us."
    )

    lines.append("")
    lines.append("## Per-candidate detail")
    for row in rows:
        lines.append("")
        lines.append(f"### {row['label']}")
        lines.append(f"Pack: `{row['pack']}`")
        lines.append("")
        lines.append("| Day | EOD pos | EOD cum PnL | Trades | Tail trades | Tail PnL | Overlay delta |")
        lines.append("|-----|---------|-------------|--------|-------------|----------|---------------|")
        for day in sorted(row["per_day"]):
            pd = row["per_day"][day]
            lines.append(
                f"| {day} "
                f"| {pd['position_at_end_of_day']} "
                f"| {_fmt_f(pd['pnl_at_end_of_day'])} "
                f"| {pd['trade_count']} "
                f"| {pd['trades_in_tail']} "
                f"| {_fmt_f(pd['tail_pnl'])} "
                f"| {_fmt_f(row['flatten_overlay_pnl_delta_by_day'].get(day))} |"
            )

    out_md = args.out_dir / "phase5_pepper_day_boundary.md"
    out_json = args.out_dir / "phase5_pepper_day_boundary.json"
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n")
    out_json.write_text(json.dumps(rows, indent=2, sort_keys=True, default=str))

    print("\n".join(lines))
    print(f"\nWrote {out_md}")
    print(f"Wrote {out_json}")


def _fmt_f(value: Any, *, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):+.{digits}f}"
    except (TypeError, ValueError):
        return "—"


if __name__ == "__main__":
    main()

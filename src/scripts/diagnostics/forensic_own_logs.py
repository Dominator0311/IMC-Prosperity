"""Forensic tick-by-tick analysis of the 16 official R2 run logs.

Parses the JSON-wrapped activitiesLog CSV for each run, extracts per-snapshot
ASH/PEPPER P&L deltas, book state, mid prices. Computes:

  1. ASH P&L accrual distribution + gain/loss snapshot counts
  2. Missed directional-trade windows (|Delta mid| >= 5 over 10 snapshots)
  3. OBI -> next-10-tick ASH P&L conditional relationship
  4. Variant divergence snapshots (Promoted vs Ash L1 vs v5 vs Killswitch)
  5. PEPPER gap vs theoretical 8000 decomposition
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

BASE = Path("/Users/abhinavgupta/Desktop/IMC/outputs/round_2/Official Results")
VARIANTS = ["Promoted", "Ash L1", "Killswitch", "v5"]


def load_run(log_path: Path) -> List[Dict]:
    """Return list of rows (dict) from a run's log file.

    The .log file is a JSON envelope whose `activitiesLog` field contains
    the semicolon-delimited CSV with all market snapshots + P&L.
    """
    with open(log_path, "r") as f:
        content = f.read()
    try:
        obj = json.loads(content)
        csv_text = obj["activitiesLog"]
    except json.JSONDecodeError:
        # Some logs may be raw CSV
        csv_text = content
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    rows = []
    for r in reader:
        try:
            rows.append({
                "day": int(r["day"]),
                "t": int(r["timestamp"]),
                "product": r["product"],
                "b1": float(r["bid_price_1"]) if r.get("bid_price_1") else None,
                "bv1": float(r["bid_volume_1"]) if r.get("bid_volume_1") else 0.0,
                "b2": float(r["bid_price_2"]) if r.get("bid_price_2") else None,
                "bv2": float(r["bid_volume_2"]) if r.get("bid_volume_2") else 0.0,
                "b3": float(r["bid_price_3"]) if r.get("bid_price_3") else None,
                "bv3": float(r["bid_volume_3"]) if r.get("bid_volume_3") else 0.0,
                "a1": float(r["ask_price_1"]) if r.get("ask_price_1") else None,
                "av1": float(r["ask_volume_1"]) if r.get("ask_volume_1") else 0.0,
                "a2": float(r["ask_price_2"]) if r.get("ask_price_2") else None,
                "av2": float(r["ask_volume_2"]) if r.get("ask_volume_2") else 0.0,
                "a3": float(r["ask_price_3"]) if r.get("ask_price_3") else None,
                "av3": float(r["ask_volume_3"]) if r.get("ask_volume_3") else 0.0,
                "mid": float(r["mid_price"]) if r.get("mid_price") else None,
                "pnl": float(r["profit_and_loss"]) if r.get("profit_and_loss") else 0.0,
            })
        except (ValueError, KeyError):
            continue
    return rows


def split_by_product(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["product"]].append(r)
    for k in out:
        out[k].sort(key=lambda r: (r["day"], r["t"]))
    return out


def compute_obi(row) -> float | None:
    """Order book imbalance across all 3 levels: (sum_bid - sum_ask)/sum."""
    bv = (row["bv1"] or 0) + (row["bv2"] or 0) + (row["bv3"] or 0)
    av = (row["av1"] or 0) + (row["av2"] or 0) + (row["av3"] or 0)
    tot = bv + av
    if tot <= 0:
        return None
    return (bv - av) / tot


def deltas(series):
    return [series[i] - series[i - 1] for i in range(1, len(series))]


def analyze_run(variant: str, run_idx: int, rows_ash, rows_pep):
    mids_ash = [r["mid"] for r in rows_ash]
    pnl_ash = [r["pnl"] for r in rows_ash]
    pnl_pep = [r["pnl"] for r in rows_pep]
    mids_pep = [r["mid"] for r in rows_pep]

    # Per-snapshot P&L deltas
    d_ash = deltas(pnl_ash)
    d_pep = deltas(pnl_pep)

    gain_snaps = sum(1 for x in d_ash if x > 0.5)
    loss_snaps = sum(1 for x in d_ash if x < -0.5)
    flat_snaps = sum(1 for x in d_ash if -0.5 <= x <= 0.5)

    return {
        "variant": variant,
        "run": run_idx,
        "n_ash": len(rows_ash),
        "n_pep": len(rows_pep),
        "ash_final_pnl": pnl_ash[-1] if pnl_ash else 0,
        "pep_final_pnl": pnl_pep[-1] if pnl_pep else 0,
        "ash_pnl_deltas": d_ash,
        "pep_pnl_deltas": d_pep,
        "ash_mids": mids_ash,
        "pep_mids": mids_pep,
        "ash_rows": rows_ash,
        "pep_rows": rows_pep,
        "ash_gain_snaps": gain_snaps,
        "ash_loss_snaps": loss_snaps,
        "ash_flat_snaps": flat_snaps,
    }


def find_dir_windows(mids: List[float], win: int = 10, thresh: float = 5.0):
    """Return list of (start_idx, end_idx, delta_mid) for windows where |mid[i+win]-mid[i]|>=thresh."""
    windows = []
    for i in range(len(mids) - win):
        if mids[i] is None or mids[i + win] is None:
            continue
        d = mids[i + win] - mids[i]
        if abs(d) >= thresh:
            windows.append((i, i + win, d))
    # Merge overlapping windows to avoid double counting
    merged = []
    for w in windows:
        if merged and w[0] <= merged[-1][1]:
            # extend
            merged[-1] = (merged[-1][0], max(merged[-1][1], w[1]),
                          (mids[max(merged[-1][1], w[1])] - mids[merged[-1][0]]))
        else:
            merged.append(list(w))
    return [tuple(w) for w in merged]


def obi_vs_pnl(rows, pnl_deltas, lookahead: int = 10):
    """For each snapshot t (with OBI), bucket by OBI sign/magnitude,
    correlate with sum of pnl deltas over t..t+lookahead.
    """
    buckets = defaultdict(list)  # bucket_label -> list of forward pnl sums
    for i in range(len(rows) - lookahead - 1):
        obi = compute_obi(rows[i])
        if obi is None:
            continue
        # Forward P&L accrual over next `lookahead` snapshots
        # pnl_deltas[j] corresponds to pnl change from row j to row j+1
        if i + lookahead > len(pnl_deltas):
            continue
        fwd_pnl = sum(pnl_deltas[i:i + lookahead])
        # Forward mid change
        fwd_mid = (rows[i + lookahead]["mid"] or 0) - (rows[i]["mid"] or 0)
        if obi <= -0.4:
            b = "obi_strong_neg"
        elif obi <= -0.15:
            b = "obi_neg"
        elif obi < 0.15:
            b = "obi_neutral"
        elif obi < 0.4:
            b = "obi_pos"
        else:
            b = "obi_strong_pos"
        buckets[b].append((fwd_pnl, fwd_mid))
    return buckets


def summarize_buckets(buckets):
    out = {}
    for k, vs in buckets.items():
        if not vs:
            continue
        pnl_list = [v[0] for v in vs]
        mid_list = [v[1] for v in vs]
        out[k] = {
            "n": len(vs),
            "mean_fwd_pnl": statistics.mean(pnl_list),
            "median_fwd_pnl": statistics.median(pnl_list),
            "mean_fwd_mid": statistics.mean(mid_list),
            "positive_mid_frac": sum(1 for m in mid_list if m > 0) / len(mid_list),
        }
    return out


def pct(x, n):
    if n == 0:
        return 0.0
    return 100.0 * x / n


def main():
    all_runs = []
    for variant in VARIANTS:
        vdir = BASE / variant
        for run_idx in sorted(os.listdir(vdir)):
            run_dir = vdir / run_idx
            if not run_dir.is_dir():
                continue
            logs = list(run_dir.glob("*.log"))
            if not logs:
                continue
            rows = load_run(logs[0])
            by_prod = split_by_product(rows)
            ash = by_prod.get("ASH_COATED_OSMIUM", [])
            pep = by_prod.get("INTARIAN_PEPPER_ROOT", [])
            if not ash or not pep:
                continue
            a = analyze_run(variant, int(run_idx), ash, pep)
            all_runs.append(a)
            print(f"{variant}/{run_idx}: n_ash={a['n_ash']} n_pep={a['n_pep']} "
                  f"ash_final={a['ash_final_pnl']:.1f} pep_final={a['pep_final_pnl']:.1f} "
                  f"gain_snaps={a['ash_gain_snaps']} loss_snaps={a['ash_loss_snaps']} flat={a['ash_flat_snaps']}")
    return all_runs


if __name__ == "__main__":
    runs = main()

    # Section 1: ASH P&L accrual distribution
    print("\n=== SECTION 1: ASH P&L accrual distribution by variant ===")
    by_variant = defaultdict(list)
    for r in runs:
        by_variant[r["variant"]].append(r)

    for v, rs in by_variant.items():
        all_deltas = []
        for r in rs:
            all_deltas.extend(r["ash_pnl_deltas"])
        if not all_deltas:
            continue
        mean_d = statistics.mean(all_deltas)
        med_d = statistics.median(all_deltas)
        pos = sum(1 for x in all_deltas if x > 0.5)
        neg = sum(1 for x in all_deltas if x < -0.5)
        flat = sum(1 for x in all_deltas if -0.5 <= x <= 0.5)
        pos_sum = sum(x for x in all_deltas if x > 0)
        neg_sum = sum(x for x in all_deltas if x < 0)
        print(f"{v}: n_deltas={len(all_deltas)} mean={mean_d:.3f} median={med_d:.3f} "
              f"pos={pos}({pct(pos,len(all_deltas)):.1f}%) neg={neg}({pct(neg,len(all_deltas)):.1f}%) "
              f"flat={flat}({pct(flat,len(all_deltas)):.1f}%) "
              f"gross_pos={pos_sum:.1f} gross_neg={neg_sum:.1f}")
        # Percentiles
        sorted_d = sorted(all_deltas)
        n = len(sorted_d)
        p = lambda q: sorted_d[int(q*n)]
        print(f"  p01={p(0.01):.2f} p05={p(0.05):.2f} p25={p(0.25):.2f} "
              f"p75={p(0.75):.2f} p95={p(0.95):.2f} p99={p(0.99):.2f} "
              f"min={sorted_d[0]:.2f} max={sorted_d[-1]:.2f}")

    # Section 2: Missed directional trade windows
    print("\n=== SECTION 2: Missed directional trade windows (|Delta mid|>=5 over 10 snapshots) ===")
    for v, rs in by_variant.items():
        total_windows = 0
        total_theoretical_capture = 0.0
        total_actual_window_pnl = 0.0
        runs_analyzed = 0
        for r in rs:
            mids = r["ash_mids"]
            d = r["ash_pnl_deltas"]
            windows = find_dir_windows(mids, win=10, thresh=5.0)
            total_windows += len(windows)
            for (s, e, dm) in windows:
                # Theoretical: position 80 captures dm full
                total_theoretical_capture += abs(dm) * 80
                # Actual: sum of pnl deltas in that range
                if e < len(d) + 1:
                    total_actual_window_pnl += sum(d[s:min(e, len(d))])
            runs_analyzed += 1
        if runs_analyzed > 0:
            print(f"{v}: avg {total_windows/runs_analyzed:.1f} dir-windows/run, "
                  f"theoretical_max={total_theoretical_capture/runs_analyzed:.0f}/run "
                  f"actual_in_windows={total_actual_window_pnl/runs_analyzed:.0f}/run "
                  f"capture_rate={100*total_actual_window_pnl/total_theoretical_capture if total_theoretical_capture>0 else 0:.1f}%")

    # Section 3: OBI vs ASH forward P&L
    print("\n=== SECTION 3: OBI buckets -> forward 10-snap ASH P&L delta ===")
    for v, rs in by_variant.items():
        agg_buckets = defaultdict(list)
        for r in rs:
            bs = obi_vs_pnl(r["ash_rows"], r["ash_pnl_deltas"], lookahead=10)
            for k, vs in bs.items():
                agg_buckets[k].extend(vs)
        summ = summarize_buckets(agg_buckets)
        print(f"\n--- {v} ---")
        for k in ["obi_strong_neg", "obi_neg", "obi_neutral", "obi_pos", "obi_strong_pos"]:
            if k in summ:
                s = summ[k]
                print(f"  {k:20s}: n={s['n']:5d} mean_fwd_pnl={s['mean_fwd_pnl']:+.3f} "
                      f"mean_fwd_mid={s['mean_fwd_mid']:+.3f} up_frac={s['positive_mid_frac']:.2f}")

    # Section 4: variant divergence per timestamp (where does v5 beat Promoted?)
    print("\n=== SECTION 4: Per-snapshot ASH P&L comparison v5 vs Promoted ===")
    # Average across runs for each variant at each timestamp index
    def avg_pnl_curve(rs):
        n = min(len(r["ash_pnl_deltas"]) for r in rs)
        avg = []
        for i in range(n):
            avg.append(statistics.mean(r["ash_pnl_deltas"][i] for r in rs))
        return avg

    v5_curve = avg_pnl_curve(by_variant["v5"])
    pr_curve = avg_pnl_curve(by_variant["Promoted"])
    ash_curve = avg_pnl_curve(by_variant["Ash L1"])
    ks_curve = avg_pnl_curve(by_variant["Killswitch"])

    n = min(len(v5_curve), len(pr_curve))
    v5_beats = [v5_curve[i] - pr_curve[i] for i in range(n)]
    v5_beats_sorted = sorted(enumerate(v5_beats), key=lambda x: -x[1])
    print(f"Top 15 snapshots where v5 beat Promoted (mean delta PnL):")
    for idx, d in v5_beats_sorted[:15]:
        t = (idx + 1) * 100
        # Reference mid change for that window in v5 run1
        mid_i = by_variant["v5"][0]["ash_mids"][idx] if idx < len(by_variant["v5"][0]["ash_mids"]) else None
        mid_i1 = by_variant["v5"][0]["ash_mids"][idx + 1] if idx + 1 < len(by_variant["v5"][0]["ash_mids"]) else None
        dm = (mid_i1 - mid_i) if (mid_i is not None and mid_i1 is not None) else None
        print(f"  t={t:6d}: v5={v5_curve[idx]:+.2f} promoted={pr_curve[idx]:+.2f} "
              f"diff={d:+.2f} Delta_mid={dm}")
    print(f"Total v5 - Promoted = {sum(v5_beats):.1f} (positive = v5 outperforms)")
    # Correlation with |Delta mid|
    from statistics import fmean
    corr_n = 0
    sum_diff_high_move = 0.0
    sum_diff_low_move = 0.0
    n_high = n_low = 0
    for idx in range(n):
        if idx + 1 >= len(by_variant["v5"][0]["ash_mids"]):
            break
        mid_i = by_variant["v5"][0]["ash_mids"][idx]
        mid_i1 = by_variant["v5"][0]["ash_mids"][idx + 1]
        if mid_i is None or mid_i1 is None:
            continue
        dm = abs(mid_i1 - mid_i)
        if dm >= 2:
            sum_diff_high_move += v5_beats[idx]
            n_high += 1
        else:
            sum_diff_low_move += v5_beats[idx]
            n_low += 1
    if n_high and n_low:
        print(f"v5 - Promoted on high-move snapshots (|dMid|>=2): sum={sum_diff_high_move:.1f} n={n_high} "
              f"mean={sum_diff_high_move/n_high:+.3f}")
        print(f"v5 - Promoted on low-move snapshots: sum={sum_diff_low_move:.1f} n={n_low} "
              f"mean={sum_diff_low_move/n_low:+.3f}")

    # Section 5: PEPPER gap decomposition
    print("\n=== SECTION 5: PEPPER gap decomposition ===")
    for v, rs in by_variant.items():
        finals = [r["pep_final_pnl"] for r in rs]
        if not finals:
            continue
        mean_final = statistics.mean(finals)
        # Theoretical: mid ends ~13000+100 = 13100 (roughly +100/sample if drift 0.1 per 100 ticks)
        # Actually: 1000 snapshots x drift 0.1 = 100 mid points, pos 80 -> 8000
        gap = 8000 - mean_final
        # Decompose: per-snapshot delta behavior
        all_d = []
        for r in rs:
            all_d.extend(r["pep_pnl_deltas"])
        pos_d = sum(x for x in all_d if x > 0)
        neg_d = sum(x for x in all_d if x < 0)
        n_d = len(all_d)
        mean_d = statistics.mean(all_d) if all_d else 0
        # Per-run ramp profile: how long to reach full long?
        ramp_times = []
        for r in rs:
            d = r["pep_pnl_deltas"]
            mids = r["pep_mids"]
            # Position proxy: dpnl / dmid when dmid != 0. Avg over first 50 snapshots
            # Actually: full-long pos=80 means dpnl = 80 * dmid. sample ratio
            ratios = []
            for i in range(len(d)):
                if i+1 < len(mids) and mids[i] is not None and mids[i+1] is not None:
                    dm = mids[i+1] - mids[i]
                    if abs(dm) > 0.1:
                        ratios.append(d[i] / dm)
            if ratios:
                # Find first index where implied pos >= 75
                for i, ratio in enumerate(ratios):
                    if ratio >= 75:
                        ramp_times.append(i)
                        break
        avg_ramp = statistics.mean(ramp_times) if ramp_times else -1
        print(f"{v}: avg_pep_final={mean_final:.0f} gap_from_8000={gap:.0f} "
              f"pos_gross={pos_d/len(rs):.0f}/run neg_gross={neg_d/len(rs):.0f}/run "
              f"mean_delta={mean_d:.3f} avg_ramp_to_pos75={avg_ramp:.1f} snapshots")

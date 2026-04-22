"""Zoom into recurring ASH loss hotspots: t~36600, t~64900, t~81800-86900.

These timestamps show up across ALL variants as worst snapshots. This suggests
a structural market condition, not a variant-specific bug.
"""
from __future__ import annotations
import statistics
from collections import defaultdict
from src.scripts.diagnostics.forensic_own_logs import (
    BASE, VARIANTS, load_run, split_by_product, analyze_run, compute_obi,
)
import os


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
            if ash and pep:
                all_runs.append(analyze_run(variant, int(run_idx), ash, pep))
    return all_runs


if __name__ == "__main__":
    runs = main()

    # Zoom in on windows around 36000-39000, 64000-70000, 81000-87000
    hotspots = [(36000, 39000), (64000, 70000), (81000, 87500)]

    print("=== Hotspot mid-price behavior (averaged across runs) ===")
    for v in VARIANTS:
        rs = [r for r in runs if r["variant"] == v]
        for lo, hi in hotspots:
            i_lo = lo // 100
            i_hi = hi // 100
            mids_samples = []
            pnls_samples = []
            for r in rs:
                if i_hi > len(r["ash_mids"]):
                    continue
                ms = r["ash_mids"][i_lo:i_hi]
                ds = r["ash_pnl_deltas"][i_lo:min(i_hi, len(r["ash_pnl_deltas"]))]
                if ms:
                    mids_samples.append(ms)
                    pnls_samples.append(ds)
            if not mids_samples:
                continue
            # Sample-averaged mid
            n = min(len(m) for m in mids_samples)
            avg_mid_start = statistics.mean(m[0] for m in mids_samples if m[0] is not None)
            avg_mid_end = statistics.mean(m[n-1] for m in mids_samples if m[n-1] is not None)
            # Min/max mid in the window
            mid_mins = [min(x for x in m if x is not None) for m in mids_samples]
            mid_maxs = [max(x for x in m if x is not None) for m in mids_samples]
            # Total PnL in window
            total_pnl = statistics.mean(sum(d) for d in pnls_samples)
            worst_pnl_snap = statistics.mean(min(d) for d in pnls_samples if d)
            print(f"{v} [{lo}-{hi}]: mid {avg_mid_start:.1f} -> {avg_mid_end:.1f} "
                  f"range({statistics.mean(mid_mins):.1f}-{statistics.mean(mid_maxs):.1f}) "
                  f"total_pnl={total_pnl:+.1f} worst_snap={worst_pnl_snap:+.1f}")

    # Per-snapshot ASH loss histograms in the 84500 window specifically
    print("\n=== t=84500 micro-analysis across all variants ===")
    for v in VARIANTS:
        rs = [r for r in runs if r["variant"] == v]
        for r in rs:
            i = 845  # snapshot index (84500/100)
            if i >= len(r["ash_rows"]):
                continue
            row = r["ash_rows"][i]
            obi = compute_obi(row)
            # 10 snapshots around
            mids = r["ash_mids"][max(0, i-5):i+10]
            pnls_d = r["ash_pnl_deltas"][max(0, i-5):min(i+10, len(r["ash_pnl_deltas"]))]
            obi_s = f"{obi:.2f}" if obi is not None else "NA"
            print(f"  {v} run{r['run']}: mid@t-500={r['ash_mids'][i-5]} "
                  f"mid@t={row['mid']} mid@t+5={r['ash_mids'][i+5] if i+5<len(r['ash_mids']) else 'NA'} "
                  f"obi@t={obi_s} "
                  f"dPnL[-5..+5]={['%.1f'%x for x in pnls_d]}")

    # Position inference at hotspots
    print("\n=== Implied position reconstruction at hotspots (Promoted run1) ===")
    rs = [r for r in runs if r["variant"] == "Promoted"]
    r = rs[0]
    # Iteratively solve for position: dPnL[i] = pos[i] * dmid + cash_flow_from_trades
    # Without per-trade data we can't separate. But approximate: if mid moves >> noise,
    # dPnL/dMid gives inventory.
    for lo, hi in hotspots:
        i_lo, i_hi = lo // 100, hi // 100
        print(f"\n  window {lo}-{hi}:")
        for i in range(i_lo, min(i_hi, len(r["ash_pnl_deltas"]))):
            if i+1 < len(r["ash_mids"]):
                dm = r["ash_mids"][i+1] - r["ash_mids"][i] if (r["ash_mids"][i] and r["ash_mids"][i+1]) else None
                dp = r["ash_pnl_deltas"][i]
                if dm is not None and abs(dm) >= 2:
                    implied_pos = dp / dm
                    t = (i+1) * 100
                    if abs(dp) >= 15:  # only interesting
                        print(f"    t={t}: dMid={dm:+.1f} dPnL={dp:+.1f} implied_pos={implied_pos:+.1f}")

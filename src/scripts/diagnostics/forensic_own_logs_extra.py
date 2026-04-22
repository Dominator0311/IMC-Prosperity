"""Extra forensic passes: (a) spread leakage on PEPPER, (b) OBI lookahead sweep,
(c) drawdown/losing-streak distribution on ASH, (d) cross-run volatility.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from src.scripts.diagnostics.forensic_own_logs import (
    BASE, VARIANTS, load_run, split_by_product, analyze_run,
    compute_obi, deltas, obi_vs_pnl, summarize_buckets,
)
from pathlib import Path
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
    by_variant = defaultdict(list)
    for r in runs:
        by_variant[r["variant"]].append(r)

    # (a) PEPPER spread & capture analysis
    print("=== PEPPER spread leakage ===")
    for v, rs in by_variant.items():
        spreads = []
        implied_pos = []
        snap_count = 0
        full_long_count = 0
        neg_d_count = 0
        for r in rs:
            pep = r["pep_rows"]
            d = r["pep_pnl_deltas"]
            for i, row in enumerate(pep):
                if row["b1"] is not None and row["a1"] is not None:
                    spreads.append(row["a1"] - row["b1"])
            # Implied position: d / dmid (only when |dmid| > 0.5 to avoid noise)
            mids = r["pep_mids"]
            for i in range(len(d)):
                if i+1 < len(mids) and mids[i] and mids[i+1]:
                    dm = mids[i+1] - mids[i]
                    if abs(dm) >= 0.5:
                        implied_pos.append(d[i] / dm)
                snap_count += 1
                if d[i] >= 7.5:
                    full_long_count += 1
                if d[i] < -0.5:
                    neg_d_count += 1
        if spreads:
            avg_sp = statistics.mean(spreads)
            med_sp = statistics.median(spreads)
            print(f"{v}: avg_spread={avg_sp:.2f} med_spread={med_sp:.2f} "
                  f"n_spread_samples={len(spreads)}")
        if implied_pos:
            print(f"  implied_pos: mean={statistics.mean(implied_pos):.1f} "
                  f"median={statistics.median(implied_pos):.1f} "
                  f"p25={sorted(implied_pos)[len(implied_pos)//4]:.1f} "
                  f"p75={sorted(implied_pos)[3*len(implied_pos)//4]:.1f}")
        print(f"  snapshots where |dPnL|>=7.5 (~full long drift): {full_long_count}/{snap_count} "
              f"({100*full_long_count/snap_count:.1f}%)")
        print(f"  snapshots with negative dPnL: {neg_d_count}/{snap_count} "
              f"({100*neg_d_count/snap_count:.1f}%)")

    # (b) OBI lookahead sweep on ASH
    print("\n=== OBI lookahead sweep (ASH, Promoted variant) ===")
    rs = by_variant["Promoted"]
    for la in [1, 3, 5, 10, 20, 50]:
        agg = defaultdict(list)
        for r in rs:
            bs = obi_vs_pnl(r["ash_rows"], r["ash_pnl_deltas"], lookahead=la)
            for k, vs in bs.items():
                agg[k].extend(vs)
        summ = summarize_buckets(agg)
        print(f"\n  lookahead={la}")
        for k in ["obi_strong_neg", "obi_neg", "obi_neutral", "obi_pos", "obi_strong_pos"]:
            if k in summ:
                s = summ[k]
                print(f"    {k:20s}: n={s['n']:5d} mean_fwd_pnl={s['mean_fwd_pnl']:+7.3f} "
                      f"mean_fwd_mid={s['mean_fwd_mid']:+7.3f}")

    # (c) OBI predictive edge for mid moves (does strong_neg -> down?)
    print("\n=== OBI mid-move predictive edge (all variants pooled) ===")
    agg = defaultdict(list)
    for r in runs:
        bs = obi_vs_pnl(r["ash_rows"], r["ash_pnl_deltas"], lookahead=10)
        for k, vs in bs.items():
            agg[k].extend(vs)
    for k in ["obi_strong_neg", "obi_neg", "obi_neutral", "obi_pos", "obi_strong_pos"]:
        vs = agg[k]
        if not vs:
            continue
        mids = [v[1] for v in vs]
        pos_moves = sum(1 for m in mids if m > 0)
        neg_moves = sum(1 for m in mids if m < 0)
        flat = len(mids) - pos_moves - neg_moves
        mean_m = statistics.mean(mids)
        print(f"  {k:20s}: n={len(mids):5d} mean_Dmid={mean_m:+.3f} "
              f"up={pos_moves}({100*pos_moves/len(mids):.0f}%) "
              f"down={neg_moves}({100*neg_moves/len(mids):.0f}%) "
              f"flat={flat}({100*flat/len(mids):.0f}%)")

    # (d) ASH largest losses (worst single-snapshot deltas)
    print("\n=== ASH worst single-snapshot losses by variant ===")
    for v, rs in by_variant.items():
        worst = []
        for r in rs:
            for i, d in enumerate(r["ash_pnl_deltas"]):
                mids = r["ash_mids"]
                if i+1 < len(mids) and mids[i] is not None and mids[i+1] is not None:
                    dm = mids[i+1] - mids[i]
                else:
                    dm = None
                worst.append((d, r["run"], (i+1)*100, dm))
        worst.sort()
        print(f"\n  {v}: 10 worst snapshot deltas")
        for d, ri, t, dm in worst[:10]:
            print(f"    run{ri} t={t}: dPnL={d:+7.2f} Dmid={dm}")
        # Longest losing streak
        for r in rs[:1]:
            longest = cur = 0
            run_loss = 0
            max_loss = 0
            for d in r["ash_pnl_deltas"]:
                if d < 0:
                    cur += 1
                    run_loss += d
                    max_loss = min(max_loss, run_loss)
                else:
                    longest = max(longest, cur)
                    cur = 0
                    run_loss = 0
            print(f"  run{r['run']}: longest losing-streak={longest} snapshots, "
                  f"max consecutive loss in streak={max_loss:.1f}")

    # (e) ASH P&L per-period: does P&L earned differ over early/mid/late sample?
    print("\n=== ASH P&L by sample-third ===")
    for v, rs in by_variant.items():
        first = []
        mid = []
        last = []
        for r in rs:
            d = r["ash_pnl_deltas"]
            n = len(d)
            first.append(sum(d[:n//3]))
            mid.append(sum(d[n//3:2*n//3]))
            last.append(sum(d[2*n//3:]))
        print(f"  {v}: first_third={statistics.mean(first):.0f} "
              f"mid={statistics.mean(mid):.0f} last={statistics.mean(last):.0f}")

    # (f) OBI signal strength: what fraction of the absolute OBI was "strong" (|OBI|>0.4)?
    print("\n=== OBI distribution on ASH (Promoted) ===")
    rs = by_variant["Promoted"]
    all_obi = []
    for r in rs:
        for row in r["ash_rows"]:
            o = compute_obi(row)
            if o is not None:
                all_obi.append(o)
    if all_obi:
        so = sorted(all_obi)
        n = len(so)
        print(f"  n={n} min={so[0]:.2f} p10={so[n//10]:.2f} p25={so[n//4]:.2f} "
              f"p50={so[n//2]:.2f} p75={so[3*n//4]:.2f} p90={so[9*n//10]:.2f} max={so[-1]:.2f}")
        abs_strong = sum(1 for o in all_obi if abs(o) > 0.4)
        print(f"  |OBI|>0.4: {abs_strong}/{n} ({100*abs_strong/n:.1f}%)")
        abs_weak = sum(1 for o in all_obi if abs(o) < 0.15)
        print(f"  |OBI|<0.15 (neutral): {abs_weak}/{n} ({100*abs_weak/n:.1f}%)")

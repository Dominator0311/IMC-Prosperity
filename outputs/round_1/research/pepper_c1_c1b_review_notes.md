# INTARIAN_PEPPER_ROOT · C1 vs C1b review notes

Both candidates share the same primary (linear_drift, history=32),
the same edges (maker=1.0, taker=2.0), and the same inventory_skew
(2.0). The only difference is **flatten_threshold**: C1 uses 0.8,
C1b uses 0.7.

- **C1 pack:** `outputs/round_1/review_packs/20260414T140404Z_round1_pepper_c1_linear_drift_h32_t20_f08/`
- **C1b pack:** `outputs/round_1/review_packs/20260414T140409Z_round1_pepper_c1b_linear_drift_h32_t20_f07/`

## Side-by-side headlines

| Metric | C1 (flatten=0.8) | C1b (flatten=0.7) | Δ (C1 − C1b) |
|--------|------------------|-------------------|--------------|
| Total PnL | +56 300 | +54 015 | **+2 285** |
| Day -2 PnL | +20 940 | +20 575 | +365 |
| Day -1 PnL | +16 642 | +16 056 | +586 |
| Day 0 PnL | +18 719 | +17 384 | +1 335 |
| Cross-day σ | ≈ 1 765 | ≈ 1 857 | — |
| EOD position d-2 | +13 | +13 | 0 |
| EOD position d-1 | +7 | +7 | 0 |
| EOD position d0 | +34 | +29 | +5 |
| Trade count | 800 | 792 | +8 |
| Near-limit steps | **1 733** (5.8 %) | **755** (2.5 %) | +978 |
| Avg entry edge | +2.95 | +2.95 | 0.00 |
| Markouts (h=1/5/20) | +3.51/+3.56/+3.44 | +3.50/+3.56/+3.43 | essentially tied |
| Lag-1 autocorr | −0.443 | −0.443 | 0.000 |
| Tail-20% PnL share | 23.7 % | 22.2 % | +1.5 pp |

## What the review packs show

- **Signal quality is identical.** Entry edge, markouts at h=1/5/20,
  and lag-1 autocorrelation are the same to within noise. Phase-5
  question #2 (C1 vs C1b) therefore resolves on **inventory hygiene**,
  not on PnL.
- **Per-day PnL is nearly identical across d-2 and d-1.** Day 0 is
  the only day with a meaningful split, and the divergence tracks
  the EOD-position difference (C1 carries +34 long into close vs
  C1b's +29).
- **Near-limit exposure differs by 2.3× (1 733 vs 755).** C1's more
  permissive flatten threshold lets the book pin the long limit
  substantially more often — in the 30 000-step replay it is at or
  near the limit for ~5.8 % of snapshots vs C1b's 2.5 %.
- **PnL is NOT time-clustered** in either candidate. Tail-20 % share
  sits around 22–24 %, close to the 20 % steady-accrual baseline.
  Lag-1 autocorr is strongly negative (−0.44), meaning step-by-step
  PnL mean-reverts — consistent with noisy mids bouncing around the
  +0.1/step drift.

## Day-boundary detail (PEPPER mids are continuous across days)

The Phase-2 hypothesis of a "+1 000 overnight jump" was wrong: the
PEPPER mid is continuous across day boundaries (day -2 ends at
~11 001, day -1 starts at ~10 998). The strategy never pays a 1 000-
tick transition cost, and a hypothetical flatten-before-boundary
overlay would *lose* −1 214 (C1) / −1 121 (C1b) of total PnL — it
would force us to sell a position that's about to earn drift edge.

See `outputs/round_1/notes/phase5_pepper_day_boundary.md` for the
full overlay table and tail-PnL-per-day breakdown.

## What remains uncertain

1. **Reliance on drift continuation.** All of this candidate's PnL
   comes from riding a monotonic +0.1/step drift with mean-reversion
   around it. If the official environment has a different drift
   slope, a pause, or a reversal, both C1 and C1b become
   systematically-wrong-direction makers.
2. **C1's extra PnL on day 0 is inventory-driven.** The +1 335 PnL
   gap on day 0 reflects C1 carrying +34 vs +29 at close. If that
   last-5-unit extension hits an adverse book move on the official
   exchange, the delta can flip negative.
3. **Taker edge grid boundary shared.** Both use taker=2.0, which is
   the top of the Phase-4 Stage-B grid. Neither candidate is the
   sensitive one — the taker=2.0 plateau was cleaner for h=32 than
   h=16, so the peak looks internal, but a future official-vs-local
   comparison may move this.

## Verdict

**C1b is the cleaner promoted default.** C1 earns +4 % extra PnL at
the cost of 2.3× more limit pinning on an almost-identical signal.
The plan explicitly warns against strategies that "depend heavily
on generous local fill assumptions" — and "spend more time pinned
at the wall" is the same type of risk. Keep C1 as a higher-upside
alternate if Phase 6 decides to ship two shortlist candidates.

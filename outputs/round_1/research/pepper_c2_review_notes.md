# INTARIAN_PEPPER_ROOT · C2 review notes

- **Config:** linear_drift primary (history=32); fallbacks (depth_mid, hybrid_wall_micro, mid); maker_edge=1.0; taker_edge=2.0; inventory_skew=1.0; flatten_threshold=0.9; position_limit=50 (placeholder).
- **Pack:** `outputs/round_1/review_packs/20260414T140415Z_round1_pepper_c2_linear_drift_h32_skew1_f09/`

C2 is identical to C1 on signal parameters (same primary, same
edges, same history) and differs only in **inventory aggressiveness**:
lower inventory_skew (1.0 vs 2.0) and higher flatten_threshold (0.9
vs 0.8) — i.e. less push-back against accumulating positions and
later capitulation to inventory.

## Headlines

| Metric | C2 | C1 (reference) | Δ (C2 − C1) |
|--------|-----|---------------|--------------|
| Total PnL | **+78 844** | +56 300 | **+22 544 (+40 %)** |
| Day -2 PnL | +32 422 | +20 940 | +11 482 |
| Day -1 PnL | +22 984 | +16 642 | +6 342 |
| Day 0 PnL | +23 437 | +18 719 | +4 718 |
| Cross-day σ | ≈ 4 400 | ≈ 1 765 | +2 635 |
| EOD position d-2 | +9 | +13 | −4 |
| EOD position d-1 | +12 | +7 | +5 |
| EOD position d0 | +37 | +34 | +3 |
| Trade count | 803 | 800 | +3 |
| **Near-limit steps** | **7 224 (24.1 %)** | 1 733 (5.8 %) | +5 491 |
| Avg entry edge | +2.94 | +2.95 | −0.01 |
| Markouts (h=1/5/20) | +3.49/+3.53/+3.43 | +3.51/+3.56/+3.44 | essentially tied |
| Lag-1 autocorr | −0.446 | −0.443 | −0.003 |
| Tail-20% PnL share | 22.4 % | 23.7 % | −1.3 pp |

## What the review pack shows — is the edge real or a limit-pinning artefact?

**The edge is real.** Phase-5 question #1 resolves affirmatively:

- **PnL is NOT time-clustered.** Tail-20 % share 22.4 % (close to the
  20 % steady-accrual baseline). Lag-1 autocorr −0.446. The extra
  +22 k PnL is not concentrated in one segment.
- **PnL uplift is proportional to exposure, not to signal.** Entry
  edge and markouts are identical to C1 at every horizon. Same
  decision-time edge; same post-fill quality. The +40 % PnL is earned
  by riding **more** of those trades, not by finding better ones.
- **Per-day PnL split mirrors C1.** Day-2 PnL is highest, day-1 and
  day-0 each ~70 % of day-2's. C2 amplifies the same profile;
  it does not break it.
- **EOD positions are all long on every day**, same as C1, with
  slightly larger swings (+37 on day 0 vs +34). Because PEPPER mids
  are continuous across days, those carry-ins earn drift PnL on the
  next day rather than paying an overnight shock.

## What the review pack shows — what's the cost?

- **Near-limit exposure is 4.2× C1's.** The strategy sits at or near
  the long limit for 24 % of the replay — roughly one snapshot in
  four.
- **Cross-day variance is 2.5× wider** (σ ≈ 4 400 vs 1 765). Day-2's
  +32 k dominates, day-1 and day-0 each contribute ~+23 k. This is
  still monotonic positive, but the distribution is heavier-tailed.
- **Failure mode is well-defined.** C2's advantage vanishes whenever
  the drift stalls or reverses. With 24 % of time at the long limit,
  a sudden downside move of even 40 ticks on the full 50-unit limit
  position costs −2 000 — one day of normal C2 PnL wiped out.
  **C2 is a directional bet that the official simulator has the same
  drift the sample data shows.**

## Day-boundary detail

Same continuous-mid property as C1: EOD positions on days -2 and -1
are carried into days -1 and 0 respectively, at essentially the same
price (the day transitions show a −3 tick change on d-2→d-1, 0 ticks
on d-1→d0). The hypothetical flatten-before-boundary overlay gives
−1 276 total delta (C2 would lose PnL if forced flat at step 9 800).

## What remains uncertain

1. **Drift generalisation.** Three sample days are not enough to
   guarantee +0.1/step on the official exchange. C2's leverage on
   drift is higher than any other candidate's.
2. **Near-limit 24 % is high.** If the official fill model is less
   permissive when the book is pinned (e.g. the exchange throttles
   orders past the limit differently), C2's realised fill rate could
   be materially lower than the replay suggests.
3. **Maker share still 0.2 %.** Same as C1 — this is a taker-driven
   edge. If the official exchange's fill model for aggressive taker
   trades at the touch differs, both C1 and C2 break together but C2
   loses more.

## Verdict

**Keep C2 as the higher-upside alternate for Phase 6.** The edge is
not a limit-pinning artefact — it is real, steady, and driven by
the same signal quality as C1, just at higher inventory leverage.

Given the plan's "do not self-suppress too early" principle combined
with "do not let beautiful theory override actual simulator edge",
C2 is a legitimate Phase-6 upload:

- Promoted: C1b (safer default).
- Alternate / higher-upside: C2 (directional bet on drift persistence).
- Baseline / ultra-safe control: C3 (zero-near-limit variant).

Phase 6 should upload C1b first to establish a reference; then C2 to
test whether the higher-leverage path is rewarded by the official
fill model; then C3 only if we need a low-risk baseline.

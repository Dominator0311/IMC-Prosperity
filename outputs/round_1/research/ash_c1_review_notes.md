# ASH_COATED_OSMIUM · C1 review notes

- **Config:** wall_mid primary; fallbacks (mid, microprice); anchor_price=10 000 (retained as last-resort fallback); maker_edge=1.5; taker_edge=0.5; inventory_skew=4.0; flatten_threshold=0.7; history_length=48; position_limit=50 (placeholder).
- **Pack:** `outputs/round_1/review_packs/20260414T140352Z_round1_ash_c1_wall_mid_t05/`

## Headlines

| Metric | Value |
|--------|-------|
| Total PnL (3 days) | +7 747 |
| Per-day PnL | +2 328 / +3 217 / +2 202 |
| Cross-day σ | ≈ 455 |
| Final positions (d-2 / d-1 / 0) | +20 / +13 / -9 |
| Trade count | 766 |
| Maker share | 0.3 % |
| Near-limit steps | 110 (0.4 %) |
| Avg entry edge | +2.08 |
| Markouts (h=1/5/20) | +1.89 / +1.79 / +1.72 |
| Lag-1 autocorr (step PnL) | −0.440 |
| Tail-20% PnL share | 13.3 % |

## What the review pack shows

- **Edge is real and steady.** Lag-1 autocorrelation of −0.44 and a
  13.3 % tail-20 % PnL share rule out time-clustered profit. PnL is
  evenly distributed across the run.
- **Markouts are strongly positive at every horizon** (+1.89 / +1.79
  / +1.72). Each trade on average captures ~2 ticks of immediate
  edge that sticks for 20+ snapshots.
- **The strategy leans taker-heavy.** With taker_edge=0.5 sitting
  inside the 16-tick median spread, the engine crosses whenever the
  residual `wall_mid − mid` exceeds 0.5 — that is, almost every time
  the book imbalance nudges wall_mid away from mid. Maker share is
  a token 0.3 %.
- **Cross-day variance is the biggest caveat.** Day -1 contributes
  +3 217 (41 % of total), day -2 and day 0 together +4 530. σ(day
  PnL)/mean ≈ 0.18 — noticeable variability. The wider daily range on
  day 0 (36 ticks vs 27 on d-2) may be driving the softer PnL there.
- **Inventory behaviour is live but under control.** EOD positions
  are +20, +13, −9 — the book genuinely moves with the oscillation.
  110 near-limit steps (0.4 % of replay) is minimal.

## What remains uncertain

1. **Simulator fill model dependency.** 99.7 % of traded quantity is
   taker. The Phase-5 plan's #3 question applies: is this edge
   reproducible on the official exchange or does it need this
   simulator's generous taker fill assumption? A maker-heavy rival
   (C2) is the direct comparison.
2. **Cross-day stability.** +2 328 → +3 217 → +2 202 is within the
   "acceptable noise" band, but the day-0 drop is consistent with the
   dossier's observation that day-0 mid variance was highest (σ 5.22
   vs 3.83 on d-1). A wider-variance day appears to compress this
   candidate's PnL.
3. **Grid-boundary flag.** taker_edge=0.5 sits at the Phase-4 Stage-A
   grid edge. Phase-4 boundary extension confirmed 0.25 is *worse*,
   so the peak is internal — but only by ~60 PnL. If official
   validation prefers a different taker_edge the peak may shift.

## Verdict

**Keep as alternate** going into Phase 6. Strong raw PnL and
markouts, steady time profile, healthy inventory — but edge is
taker-dominated, so a conservative promoted default that tolerates a
fill-model surprise (C2) should ship first. Promote C1 after official
validation if the edge holds.

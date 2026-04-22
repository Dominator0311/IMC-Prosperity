# INTARIAN_PEPPER_ROOT · C3 review notes

- **Config:** linear_drift primary (history=32); fallbacks (depth_mid, hybrid_wall_micro, mid); maker_edge=1.0; taker_edge=2.0; **inventory_skew=4.0**; flatten_threshold=0.8; position_limit=50 (placeholder).
- **Pack:** `outputs/round_1/review_packs/20260414T140421Z_round1_pepper_c3_linear_drift_h32_skew4_f08/`

C3 is the conservative inventory variant: same signal parameters as
C1 / C1b / C2, but `inventory_skew` is doubled to 4.0 so the strategy
pushes back harder on any position accumulation.

## Headlines

| Metric | C3 | C1 (reference) | Δ (C3 − C1) |
|--------|-----|---------------|--------------|
| Total PnL | +35 201 | +56 300 | −21 099 (−37 %) |
| Day -2 PnL | +12 966 | +20 940 | −7 974 |
| Day -1 PnL | +10 904 | +16 642 | −5 738 |
| Day 0 PnL | +11 331 | +18 719 | −7 388 |
| Cross-day σ | ≈ 875 | ≈ 1 765 | −890 |
| EOD position d-2 | +19 | +13 | +6 |
| EOD position d-1 | +2 | +7 | −5 |
| EOD position d0 | +18 | +34 | −16 |
| Trade count | 763 | 800 | −37 |
| **Near-limit steps** | **0 (0 %)** | 1 733 (5.8 %) | −1 733 |
| Avg entry edge | +2.96 | +2.95 | +0.01 |
| Markouts (h=1/5/20) | +3.52/+3.53/+3.40 | +3.51/+3.56/+3.44 | essentially tied |
| Lag-1 autocorr | −0.437 | −0.443 | +0.006 |
| Tail-20% PnL share | 24.0 % | 23.7 % | +0.3 pp |

## What the review pack shows

- **PnL is 63 % of C1, with zero near-limit exposure.** The trade-off
  is clean: ~37 % PnL give-up for complete elimination of limit
  pinning.
- **Per-day PnL is the tightest across candidates at this inventory
  level.** σ/mean ≈ 7.5 %, vs 16 % for C1 and 19 % for C2.
- **Signal quality is identical.** Same edge (+2.96), same markouts,
  same lag-1 autocorr. C3's PnL gap vs C1 comes entirely from the
  inventory brake suppressing exposure to drift continuation.
- **EOD positions stay much smaller.** +19 / +2 / +18 vs C1's
  +13 / +7 / +34. Day 0 in particular shows how aggressively skew=4.0
  unwinds the accumulated long.
- **Trade count is only 37 lower than C1** — inventory brake does not
  suppress trading, just retraces it more often.

## What remains uncertain

1. **PnL gives up 21 k** (~40 %) vs C1. Under the current local
   replay, that's a lot to leave on the table. On the other hand, on
   an official exchange where the drift may not persist as cleanly,
   the robustness could flip sign.
2. **Skew=4.0 is inside the Stage-C grid** (tested values 1.0, 2.0,
   4.0, 8.0). Going higher (skew=8.0) dropped PnL to +23 k. Going
   lower (skew=2.0 = C1) raises PnL but also near-limit.
3. **The flat inventory posture is only useful if the drift pauses
   or reverses.** On the current sample data, C3 clearly
   under-performs C1 / C2; it is most valuable as a control.

## Verdict

**Keep as baseline / ultra-safe control** in the Phase-6 upload
plan. Not promoted; used if we need a third submission slot to
triangulate (e.g., if C1b passes and C2 fails on the official
platform, C3 tells us whether the failure is "drift did not persist"
vs "inventory policy interacted badly"). If we only have two upload
slots, drop C3.

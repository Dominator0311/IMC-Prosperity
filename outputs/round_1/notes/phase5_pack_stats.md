# Round 1 — Phase 5 per-candidate review-pack diagnostics

All figures derive from the review packs under `outputs/round_1/review_packs` (one pack per candidate, re-run with `run_round1_review_packs.py`).

## Headline table

| Candidate | Product | Total PnL | Day -2 | Day -1 | Day 0 | Tail-20% share | Lag-1 autocorr | Maker % | Near-limit | Edge | mk-1 | mk-5 | mk-20 |
|-----------|---------|-----------|--------|--------|-------|----------------|----------------|---------|------------|------|------|------|-------|
| ash_c1_wall_mid_t05 | ASH_COATED_OSMIUM | +7747 | +2328 | +3217 | +2202 | 13.3% | -0.440 | 0.3% | 110 | +2.08 | +1.89 | +1.79 | +1.72 |
| ash_c2_ewma_mid_t025 | ASH_COATED_OSMIUM | +6447 | +2189 | +2124 | +2134 | 21.1% | -0.448 | 0.3% | 0 | +0.80 | +2.08 | +1.94 | +1.93 |
| pepper_c1_linear_drift_h32_t20_f08 | INTARIAN_PEPPER_ROOT | +56300 | +20940 | +16642 | +18719 | 23.7% | -0.443 | 0.3% | 1733 | +2.95 | +3.51 | +3.56 | +3.44 |
| pepper_c1b_linear_drift_h32_t20_f07 | INTARIAN_PEPPER_ROOT | +54015 | +20574 | +16056 | +17384 | 22.2% | -0.443 | 0.2% | 755 | +2.95 | +3.50 | +3.56 | +3.43 |
| pepper_c2_linear_drift_h32_skew1_f09 | INTARIAN_PEPPER_ROOT | +78844 | +32422 | +22984 | +23437 | 22.4% | -0.446 | 0.2% | 7224 | +2.94 | +3.49 | +3.53 | +3.43 |
| pepper_c3_linear_drift_h32_skew4_f08 | INTARIAN_PEPPER_ROOT | +35201 | +12966 | +10904 | +11331 | 24.0% | -0.437 | 0.7% | 0 | +2.96 | +3.52 | +3.53 | +3.40 |

## EOD positions per candidate

| Candidate | Day -2 EOD pos | Day -1 EOD pos | Day 0 EOD pos |
|-----------|---------------:|---------------:|--------------:|
| ash_c1_wall_mid_t05 | 20 | 13 | -9 |
| ash_c2_ewma_mid_t025 | 8 | 4 | 4 |
| pepper_c1_linear_drift_h32_t20_f08 | 13 | 7 | 34 |
| pepper_c1b_linear_drift_h32_t20_f07 | 13 | 7 | 29 |
| pepper_c2_linear_drift_h32_skew1_f09 | 9 | 12 | 37 |
| pepper_c3_linear_drift_h32_skew4_f08 | 19 | 2 | 18 |

## Interpretation keys
- **Tail-20% share**: fraction of total PnL that accrued in the last 20 % of simulation steps. ≈20 % indicates steady accrual; >50 % flags time-clustered edge.
- **Lag-1 autocorr**: step-to-step PnL autocorrelation. ≈0 = independent, >0 = bursty clusters, <0 = mean-reverting within-day (typical for market-making on noisy mids).
- **Maker %**: fraction of traded quantity executed as a maker fill. Phase-1 replay fill model rewards both maker and taker paths; watch how this shifts between candidates.
- **EOD position**: signed end-of-day inventory. PEPPER mids are continuous across day boundaries in the sample data, so EOD exposure only matters if the drift reverses or halts intra-day.

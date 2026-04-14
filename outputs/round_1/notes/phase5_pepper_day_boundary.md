# Round 1 — PEPPER day-boundary / end-of-day diagnostic

Packs root: `outputs/round_1/review_packs`
Tail window: last 200 steps per day
Flatten overlay cutoff: step 9800 of 100

## Per-candidate summary

| Candidate | Overall PnL | Lag-1 autocorr | EOD pos d-2 | EOD pos d-1 | EOD pos d0 | Tail PnL d-2 | Tail PnL d-1 | Tail PnL d0 | Overlay total delta |
|-----------|-------------|----------------|-------------|-------------|------------|--------------|--------------|-------------|---------------------|
| pepper_c1_linear_drift_h32_t20_f08 | +56300.0 | -0.443 | 13 | 7 | 34 | +294.5 | +301.5 | +872.0 | -1213.5 |
| pepper_c1b_linear_drift_h32_t20_f07 | +54015.0 | -0.443 | 13 | 7 | 29 | +294.5 | +301.5 | +772.0 | -1121.0 |
| pepper_c2_linear_drift_h32_skew1_f09 | +78844.0 | -0.446 | 9 | 12 | 37 | +208.5 | +394.0 | +932.0 | -1275.5 |
| pepper_c3_linear_drift_h32_skew4_f08 | +35201.0 | -0.437 | 19 | 2 | 18 | +423.5 | +209.0 | +520.0 | -1102.0 |

## Interpretation guide

- **EOD position**: large absolute values exposed to the +1 000 overnight jump. Sign matters: long before a jump earns the +1 000, short before a jump loses 1 000 per unit.
- **Tail PnL**: PnL accrued in the last tail-steps window of each day. Big negatives suggest adverse selection near close; big positives (and especially if they add up to most of the day's PnL) suggest the strategy makes most of its money riding the drift into close.
- **Lag-1 autocorr of step PnL**: near 0 = uncorrelated (steady); strongly positive = clustered (PnL arrives in bursts); negative = mean-reverting bar-by-bar.
- **Overlay total delta**: signed PnL impact if we'd flattened at the cutoff step using the mid at that moment. Positive means a pre-close flatten would have helped; negative means it would have cost us.

## Per-candidate detail

### pepper_c1_linear_drift_h32_t20_f08
Pack: `outputs/round_1/review_packs/20260414T140404Z_round1_pepper_c1_linear_drift_h32_t20_f08`

| Day | EOD pos | EOD cum PnL | Trades | Tail trades | Tail PnL | Overlay delta |
|-----|---------|-------------|--------|-------------|----------|---------------|
| -2 | 13 | +20939.5 | 244 | 1 | +294.5 | -344.0 |
| -1 | 7 | +37581.0 | 278 | 6 | +301.5 | -166.5 |
| 0 | 34 | +56300.0 | 278 | 4 | +872.0 | -703.0 |

### pepper_c1b_linear_drift_h32_t20_f07
Pack: `outputs/round_1/review_packs/20260414T140409Z_round1_pepper_c1b_linear_drift_h32_t20_f07`

| Day | EOD pos | EOD cum PnL | Trades | Tail trades | Tail PnL | Overlay delta |
|-----|---------|-------------|--------|-------------|----------|---------------|
| -2 | 13 | +20574.5 | 241 | 1 | +294.5 | -344.0 |
| -1 | 7 | +36631.0 | 276 | 6 | +301.5 | -166.5 |
| 0 | 29 | +54015.0 | 275 | 4 | +772.0 | -610.5 |

### pepper_c2_linear_drift_h32_skew1_f09
Pack: `outputs/round_1/review_packs/20260414T140415Z_round1_pepper_c2_linear_drift_h32_skew1_f09`

| Day | EOD pos | EOD cum PnL | Trades | Tail trades | Tail PnL | Overlay delta |
|-----|---------|-------------|--------|-------------|----------|---------------|
| -2 | 9 | +32422.5 | 243 | 1 | +208.5 | -258.0 |
| -1 | 12 | +55407.0 | 283 | 6 | +394.0 | -259.0 |
| 0 | 37 | +78844.0 | 277 | 4 | +932.0 | -758.5 |

### pepper_c3_linear_drift_h32_skew4_f08
Pack: `outputs/round_1/review_packs/20260414T140421Z_round1_pepper_c3_linear_drift_h32_skew4_f08`

| Day | EOD pos | EOD cum PnL | Trades | Tail trades | Tail PnL | Overlay delta |
|-----|---------|-------------|--------|-------------|----------|---------------|
| -2 | 19 | +12965.5 | 240 | 1 | +423.5 | -473.0 |
| -1 | 2 | +23870.0 | 262 | 6 | +209.0 | -74.0 |
| 0 | 18 | +35201.0 | 261 | 3 | +520.0 | -555.0 |

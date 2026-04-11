# Phase 3 Fair Value Note

This note records the first disciplined fair-value comparison pass built
for Phase 3.

The comparison workflow now lives in
`python -m src.scripts.compare_fair_values` and writes a report under
`outputs/fair_value_comparison/<run_id>/`.

## What the workflow compares

For each product and estimator it records:

- current-mid fit (`mae_now`)
- next-step mid fit (`mae_n1`)
- 5-step mid fit (`mae_n5`)
- replay PnL under the shared execution skeleton
- trade count, maker share, and time near position limits

This deliberately separates "tracks price well" from "earns money on one
sample" so we do not overfit to a single replay.

## Current tutorial read

### EMERALDS

- `anchor` remains the correct live choice.
- It beats the `mid` baseline on next-step fit and stays economically
  honest for a near-static product.
- `depth_mid` is the closest alternative, but there is no strong reason
  to replace the simple 10000 anchor.

Recommendation: keep `EMERALDS.fair_value_method = "anchor"`.

### TOMATOES

- `depth_mid` still has the best raw price-tracking fit.
- But the head-to-head tuning pass showed that tuned `weighted_mid`
  materially outperforms tuned `depth_mid` on the tutorial replay while
  keeping near-limit stress at zero.
- The winning tuned `weighted_mid` region was:
  `maker_edge=1`, `taker_edge=1`, `inventory_skew=3`, with
  `flatten_threshold` effectively irrelevant inside the tested range.
- `anchor` and `rolling_mid` are still treated as suspicious because
  they rely on weaker fit assumptions even when they print attractive
  replay PnL.

Recommendation: keep TOMATOES on tuned `weighted_mid` for the current
tutorial baseline and treat `depth_mid` as a future challenger, not the
default.

## Current status vs plan

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete for the tutorial products; EMERALDS stays on
  `anchor`, TOMATOES stays on tuned `weighted_mid`
- Phase 4: still incomplete because we do not yet have visual charts and
  timestamp drilldowns

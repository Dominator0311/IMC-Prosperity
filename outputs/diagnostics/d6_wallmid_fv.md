# D6 — Wall-Mid Fair-Value Counterfactual for ASH

Tests F2 + F4 convergent finding: top teams use wall_mid / max-amount-mid as fair value on stable products, not time-smoothed weighted_mid. Swap ASH primary FV method and measure ASH P&L on the R2 3-day local replay.

**Caveat:** local backtest is not the truth source (F7 calibration mismatch). A positive direction on local backtest + plausible mechanism = upload-to-IMC-simulator candidate.

| Variant | Total P&L | ASH P&L | ΔASH vs current | PEPPER | Trades | Near-limit |
|---|---|---|---|---|---|---|
| weighted_mid (current) | 249,375 | 9,847 | +0 | 239,528 | 989 | 30002 |
| wall_mid | 249,455 | 9,927 | +80 | 239,528 | 988 | 30355 |
| filtered_wall_mid | 249,455 | 9,927 | +80 | 239,528 | 988 | 30355 |
| microprice (sanity) | 240,510 | 982 | -8,865 | 239,528 | 393 | 35756 |
| hybrid_wall_micro (blend) | 241,136 | 1,608 | -8,239 | 239,528 | 510 | 30182 |

## Interpretation

- **ΔASH > 500 on wall_mid / filtered_wall_mid:** F2/F4 mechanical fix is directionally correct. Build the IMC-simulator upload.
- **ΔASH ≈ 0:** wall-mid fair value alone isn't the mechanism; we also need quote-inside-wall placement (F2 finding #2).
- **ΔASH < 0:** our current weighted_mid is actually calibrated to our ladder; the fix requires both FV and placement together.

## Next step if this diagnostic is positive

1. Create a new engine-config variant `round2_v5micro_wallmid_ash_engine_config`.
2. Use `src/scripts/round_2/export_test_variants.py` pattern to build an IMC test-upload bundle.
3. Upload to IMC simulator alongside current `Promoted` variant for direct A/B.
4. IF IMC test shows +500+ shells/sample on ASH, promote to R3 submission.

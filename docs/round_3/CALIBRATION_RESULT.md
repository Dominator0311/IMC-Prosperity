# R3 Fill-Model Calibration Result

Generated: 2026-04-24T17:53:40.644063

## Best parameters (closest to 15% empirical fill rate)

| Product class | passive_allocation | fill_rate |
|---|---|---|
| delta1 | 0.05 | 0.016 |
| otm_voucher | 0.05 | 0.004 |

## Use in sweeps

Set `passive_allocation` in `FillModel` to the values above
when running T02b parameter sweeps and T12 LOO validation.

Full sweep data: `outputs/round_3/calibration/20260424_175340.json`

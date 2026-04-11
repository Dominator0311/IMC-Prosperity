# TOMATOES Depth-Mid Tuning Note

This note records the first promotion attempt from `weighted_mid` to
`depth_mid`.

## Baseline promotion result

Switching TOMATOES from `weighted_mid` to `depth_mid` with the old
execution settings produced a tutorial replay result of:

- PnL: `-91`
- trades: `13`
- near-limit steps: `0`

That means the fair-value upgrade did **not** work as a drop-in swap.
The execution shell needed retuning.

## Focused sweep result

We ran a TOMATOES sweep over:

- `maker_edge`
- `taker_edge`
- `inventory_skew`
- `flatten_threshold`

The strongest repeatable signal was:

- raise `taker_edge` from `1` to `2`
- tighten `maker_edge` from `2` to `1`
- keep `inventory_skew` at least `2.5`
- `flatten_threshold` had no meaningful effect in this grid

Best observed configs were:

- `maker_edge=1`
- `taker_edge=2`
- `inventory_skew in {2.5, 3.0}`
- `flatten_threshold in {0.65, 0.7, 0.75}`

These all landed at `+24` PnL with no near-limit stress.

## Final head-to-head decision

We then ran the same focused sweep for `weighted_mid` and compared the
best tuned regions directly.

Result:

- tuned `depth_mid` best region: `+24`
- tuned `weighted_mid` best region: `+276`
- both showed `0` near-limit stress in the tested grid

That is strong enough to settle the tutorial baseline choice.

## Current repo choice

The default TOMATOES config now uses tuned `weighted_mid`:

- `fair_value_method = "weighted_mid"`
- `maker_edge = 1`
- `taker_edge = 1`
- `inventory_skew = 3.0`
- `flatten_threshold = 0.7`

## Honest interpretation

The useful conclusion from this experiment is not that `depth_mid` was a
mistake. It was a worthwhile challenger and the exercise helped us build
the comparison + sweep tooling Phase 3 needed.

So the right read is:

- `depth_mid` remains an interesting candidate because it tracks price
  better
- but tuned `weighted_mid` is the clear winner for the current tutorial
  baseline
- Phase 3 can now be considered complete, and future work should move to
  Phase 4 style review discipline and later robustness testing

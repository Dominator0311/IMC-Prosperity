# Tutorial Round 1 — Quick EDA

Source: `data/raw/tutorial_round_1/prices_round_0_day_{-1,-2}.csv`
Rows per product: 20,000 across two days.

## EMERALDS

| metric | value |
|---|---|
| mid mean | 10000.00 |
| mid median | 10000.00 |
| mid stdev | 0.72 |
| mid min / max | 9996.00 / 10004.00 |
| spread mean / median | 15.74 / 16.00 |
| spread min / max | 8.00 / 16.00 |
| best bid volume mean / median / max | 12.5 / 13.0 / 15 |
| best ask volume mean / median / max | 12.5 / 13.0 / 15 |

**Reads:**

- Mid is effectively a constant at 10000. Total drift across 20k rows is 8 ticks.
- Spread is almost always 16 (with occasional tightening to 8). That is a
  *huge* spread for an almost-static product.
- Best-level volume is around 12–13, so a maker quote of size 5 is well
  within what the top of book can absorb.
- The right fair value here is the anchor 10000, possibly nudged toward
  the microprice for book-imbalance tilts.
- The dominant risk is one-sided inventory pileup, not fair-value drift.

## TOMATOES

| metric | value |
|---|---|
| mid mean | 4992.76 |
| mid median | 4995.50 |
| mid stdev | 19.75 |
| mid min / max | 4946.50 / 5036.00 |
| spread mean / median | 13.02 / 13.00 |
| spread min / max | 5.00 / 14.00 |
| best bid volume mean / median / max | 7.4 / 7.0 / 12 |
| best ask volume mean / median / max | 7.4 / 7.0 / 12 |

**Reads:**

- Mid drifts meaningfully — ~90 ticks peak-to-peak, stdev ~20. A constant
  fair value is clearly wrong.
- Spread is narrower and more variable than EMERALDS: usually 13, with
  minimums down to 5 where taker opportunities are least likely to exist.
- Best-level volume is roughly half of EMERALDS, so maker sizes should
  be smaller and inventory discipline tighter.
- The right fair value here is a rolling or weighted mid. The
  short-memory predictive structure hypothesized in the plan is
  consistent with the observed drift.

## Implications for Phase 2 EMERALDS baseline

1. Anchor at 10000 is correct. Use it as the primary fair value.
2. Given spread ~= 16, a maker edge of 2 (quote at 9998 / 10002) should
   capture obvious edge every iteration the book is normal.
3. A taker edge of 1 is enough to cross an ask at 9999 or hit a bid at
   10001 when they appear, which is rare but essentially free money.
4. Keep max_aggressive_size modest (≤ 10) so a single burst of
   one-sided fills cannot breach the 20-unit position limit.
5. Flatten hard once the absolute position exceeds 75% of the limit —
   inventory is the primary failure mode, not mispricing.

## Tutorial trade tape quirk (important honesty note)

The tutorial trades CSV only prints EMERALDS activity at exactly three
prices: **9992**, **10000**, and **10008** — the best bid, the mid,
and the best ask of a "nominal" book. Any quote strictly inside the
spread (for example our default maker quotes at 9998 / 10002)
therefore receives **zero** passive-fill credit under our
trade-tape-match heuristic.

During Phase 2B we briefly tuned `EMERALDS.maker_edge=8` to land
quotes exactly at 9992 / 10008 so the passive fill model would match
the tape and the baseline would report nonzero PnL (+2144). That was
a simulation artifact:

1. On a real exchange the trade tape will print at many prices, so a
   strict inside-spread quote is the correct strategic choice and
   `maker_edge=8` would be strictly worse.
2. The `passive_allocation` parameter is unvalidated — PnL scales
   roughly linearly with it and 0.3 is a guess, not an empirical fit.

Phase 2C reverts `EMERALDS.maker_edge` to **2** (a principled
just-inside-the-spread quote) and accepts a near-zero EMERALDS PnL in
the tutorial baseline. The baseline is now an honest test that the
engine runs end-to-end, threads state across iterations, and clips
inventory correctly — not a performance claim. Phase 3 (fair-value
inference) and Phase 6 (parameter sweeps) will produce the real tuned
configuration.

### TOMATOES baseline is drift-lucky

Phase 2B's TOMATOES result (+37 PnL, mostly taker trades) is not
repeatable edge. The `weighted_mid` estimator lags the drifting mid,
so our taker fills happen *after* the book has already moved. The
specific upward drift direction across these two days handed us a few
fills in a favorable direction by accident. Reverse the drift and the
same strategy loses money on the same data. Do not treat +37 as
signal; treat it as simulator noise.

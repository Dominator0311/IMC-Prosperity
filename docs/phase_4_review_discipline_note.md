# Phase 4a Review Discipline Note

Phase 4a (the "data layer + charts" half of doctrine Phase 4) is now
in place. This note describes what each review pack contains, how to
read it, and how to reproduce a run from its manifest.

## How to generate a pack

```bash
source .venv/bin/activate
PYTHONPATH=. python -m src.scripts.run_review --label <short_tag>
```

Add `--no-charts` to skip PNG rendering if you only need the metrics
and manifest. Everything lands under
`outputs/review_packs/<timestamp>_<label>/`.

## Contents of a review pack

```
outputs/review_packs/<run_id>/
  manifest.json       # provenance (see below)
  summary.json        # per-product aggregates including edge/markouts
  summary.txt         # two human-readable tables
  trades.json         # one record per fill, decision + fill context
  series.json         # mid / fair-value / pnl step series
  charts/             # PNG artifacts (see below)
  notes.md            # structured human review template
```

## What the aggregate metrics mean

| Column  | Meaning |
|---------|---------|
| `edge`  | Quantity-weighted average **entry edge** = `sign × (fair_value_at_decision − price)`. Positive = trader believed it had an edge on the favourable side of its own fair value **at the moment it committed to the order**. |
| `edge_n`| Number of fills that contributed to `edge`. Fills where the decision-time fair value was missing are dropped. |
| `mk_1`  | Quantity-weighted average **markout** at +1 step = `sign × (mid[fill_step + 1] − price)`. Positive = trade looked favourable one step after the money moved. Uses **observable** mids only — no carry-forward. |
| `mk_5`, `mk_20` | Same formula at horizons +5 and +20 steps. |
| `mk_*_n`| Sample size for that horizon. Horizons that fall past the end of the replay (or land on a one-sided book) silently drop that record. Always read the count next to the mean. |

Entry edge uses **decision-time** fair value. Markouts use
**fill-time** execution price vs future observable mids. The
distinction matters for passive fills: a maker quote placed at step
T that clears at step T+K should be scored against the fair value we
believed at T, not the fair value we would compute at T+K. The
simulator threads this through via a private
`_PendingMakerOrder` type that bundles decision context with the
resting order.

## What the charts show

Rendered under `charts/` when `--no-charts` is not passed:

- `price_vs_fair_<PRODUCT>.png` — observable mid overlaid with the
  decision-time fair value the trader used each step. Taker fills
  are opaque ▲/▼ markers; maker fills are faded. First thing to
  look at when diagnosing surprising PnL.
- `pnl_over_time_<PRODUCT>.png` — cumulative PnL per step. The
  series is **gap-free**: when the book is one-sided, the last
  observed mid is carried forward for marking purposes. Trade
  effects and unrealised PnL both roll through here.
- `position_over_time_<PRODUCT>.png` — running position path. Look
  for periods stuck near the limit (use with `steps_near_limit`
  from summary).
- `maker_taker_<PRODUCT>.png` — horizontal bar showing buy/sell
  totals split by mode. Useful to spot "I thought I was market
  making but I'm 90% taker" regressions.
- `markouts_<PRODUCT>.png` — three histograms, one per horizon, with
  the mean marked. Most profitable: positive mass at +1 that
  sustains at +20. A strong +1 that reverses by +20 is a
  fast-alpha / stale-fair-value warning.
- `pnl_over_time_total.png` — single-line total PnL across all
  products, step-index aligned. The fastest chart to skim.

## How to fill in `notes.md`

The template has five sections. Phase 4a's whole point is that
**none of them should be left blank** before a change is accepted.

1. **Decision** — one of `keep`, `modify`, `discard`. Only three
   states; if you want to say "keep but tune later", write `modify`
   and put the tuning idea in *Next change to test*.
2. **What looked good** — concrete, chart-referenced observations.
   "TOMATOES price_vs_fair shows fair tracking mid on drift-up
   regime" beats "TOMATOES looks fine".
3. **What looked bad** — same rules. Blank is not an answer.
4. **Most important chart to inspect** — name the file and, when
   applicable, the timestamp window to zoom into. The Phase 4b
   drilldown tool (not yet built) will eventually read this.
5. **Next change to test** — the specific hypothesis for the next
   experiment. "Try `maker_edge=1` on EMERALDS for 1 day of replay"
   is actionable; "tune more" is not.

## Reproducing a pack from `manifest.json`

Every pack records enough state to be re-run bit-for-bit if the
working tree is at the same commit:

```json
{
  "run_id": "<timestamp>_<label>",
  "git_commit": "<short hash>",
  "git_dirty": false,
  "data_files": ["data/raw/..."],
  "engine_config": { "products": { "...": { ... } } },
  "estimators_per_product": { "...": { "primary": "...", "fallbacks": [...] } },
  "markout_horizons": [1, 5, 20]
}
```

To reproduce:

1. `git checkout <git_commit>` (`git_dirty=true` in a saved pack
   means the comparison isn't exactly reproducible — that's ok for
   day-to-day iteration, not ok for anything we're quoting as a
   result).
2. Confirm the CSVs in `data_files` still exist at the listed
   paths.
3. Run `python -m src.scripts.run_review --label <anything>` (or
   construct a custom `Trader` with the snapshot `engine_config`
   and drive `BacktestSimulator` directly).

## Current status vs plan

- Phase 4a (data layer + charts + enriched pack): **complete**
- Phase 4b (interactive timestamp drilldown for best/worst trades
  and near-limit slices): **deferred**
- Phase 5+ (TOMATOES dynamic extensions, parameter sweeps,
  signal scanner): unchanged from prior notes.

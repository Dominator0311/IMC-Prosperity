# ASH_COATED_OSMIUM — Round 1 Product Dossier

**Scope:** Phase 1 market-structure analysis using three days of replay
data (`day_-2`, `day_-1`, `day_0`; 30 000 snapshots, 27 644 two-sided).
No strategy has been implemented.

## TL;DR

- Leading hypothesis ("stable-anchor, maker-first product with anchor
  near 10 000") is **supported** by price, spread, and residual
  behaviour on all three days.
- Structural fair sits within ±2 ticks of **10 000**. Daily mid σ is
  only ~4–5 ticks; the range visited each day is ~27–36 ticks.
- Spread is **wide and stable** (median = 16, mean ≈ 16.2 on every
  day). This is inconsistent with an aggressive-taker product and
  strongly consistent with a spread-capture opportunity.
- In the Phase-1 replay (placeholder limit=50), **`wall_mid` is the
  most cross-day robust fair value** (PnL ≈ 2.6k / 3.4k / 2.6k on days
  -2/-1/0; 208–262 trades each day, negative `d_n1` markout on every
  day). `anchor` produces the highest single-day PnL on days -1 and 0
  but is the 5th-best on day -2 and pins inventory against the limit
  for 12 472 steps combined — a red flag.
- Local micro-aware estimators (`depth_mid`, `ewma_mid`,
  `hybrid_wall_micro`) show the **strongest next-mid markouts** but
  quote far less frequently and therefore leave PnL on the table under
  the current engine defaults.

## Key numbers (three-day aggregate, cleaned to two-sided snapshots)

| Day | n | mean mid | σ | min | max | range | spread mean | spread median |
|-----|---|----------|---|-----|-----|-------|-------------|---------------|
| -2  | 9 187 | 9 998.16 | 4.73 | 9 984.5  | 10 012.0 | 27.5 | 16.15 | 16 |
| -1  | 9 225 | 10 000.83 | 3.83 | 9 986.5  | 10 013.5 | 27.0 | 16.19 | 16 |
|  0  | 9 232 | 10 001.62 | 5.22 | 9 981.5  | 10 017.5 | 36.0 | 16.18 | 16 |

Per-day linear fits of mid against timestamp are essentially flat
(|slope| < 1.5e-4 per timestamp, residual σ ≈ 3.8–5.2 ≈ mid σ); there
is no intraday drift — only oscillation.

Inter-day mean shifts: +2.67 (day -2 → -1), +0.79 (day -1 → 0). The
level is **not drifting** across days; it re-centers each morning
within ±3 ticks of 10 000.

## A. Price and spread structure

- **Anchor behaviour:** median mid equals 9 998 / 10 001 / 10 002 on
  the three days. Oscillation is symmetric around 10 000; no bias.
- **Oscillation scale:** σ(mid) ≈ 4–5 ticks, which is only 0.3× the
  spread. The market sits well inside its own spread.
- **Spread structure:** median spread = 16 on every day. p25 = 16,
  p75 = 17, p95 = 19. Spread rarely collapses to a tight market;
  `spread_spike_fraction` (spread ≥ median + 2σ) ≈ 1%. There is no
  sign of a tight-spread regime to exploit with takes — this is
  primarily a maker product.
- **One-sided book fraction:** ~7.9% of snapshots have at least one
  empty side (balanced between missing-bid ≈ 4.0% and missing-ask ≈
  3.9%). Not high enough to break strategy logic, but residual /
  microprice estimators lose coverage here.

## B. Fair-value candidates

All figures below are from the combined 3-day replay under the
Phase-1 placeholder config (limit=50, taker_edge=1.0, maker_edge=1.0,
history_length=48). PnL rankings are indicative, **not** a promotion.

### Combined replay (three days, 27 644 two-sided snapshots)

| Estimator          | cov % | mae_now | mae_n1 | d_n1 | PnL (3-day) | Trades | mk% | Near-limit |
|--------------------|------:|--------:|-------:|-----:|------------:|-------:|----:|-----------:|
| anchor             | 100.0 | 3.859   | 3.859  | +2.609 | 9 991   | 550    | 1.0 | 12 472 |
| wall_mid           | 92.1  | 1.022   | 1.133  | −0.116 | 8 783   | 698    | 0.3 |  2 654 |
| filtered_wall_mid  | 92.1  | 1.022   | 1.133  | −0.116 | 8 783   | 698    | 0.3 |  2 654 |
| weighted_mid       | 100.0 | 1.197   | 1.252  | +0.003 | 8 840   | 616    | 0.3 |    789 |
| rolling_mid        | 100.0 | 1.380   | 1.416  | +0.167 | 8 597   | 618    | 0.2 |    961 |
| depth_mid          |  92.1 | 0.731   | 1.057  | −0.192 | 4 719   | 447    | 0.6 |    372 |
| ewma_mid           | 100.0 | 0.733   | 1.047  | −0.202 | 2 695   | 168    | 0.8 |      0 |
| mid                |  92.1 | 0.000   | 1.249  | +0.000 | 1 227   |  82    | 4.3 | 12 562 |
| microprice         |  92.1 | 0.981   | 1.230  | −0.019 | 1 195   |  83    | 3.7 |  9 462 |
| hybrid_wall_micro  |  92.1 | 0.998   | 1.067  | −0.182 | 1 087   | 127    | 1.5 |    677 |

### Cross-day robustness (same estimator across days; PnL only)

| Estimator          | Day -2 | Day -1 | Day 0 | Combined |
|--------------------|-------:|-------:|------:|---------:|
| wall_mid           | 2 644  | 3 373  | 2 642 | 8 783   |
| weighted_mid       | 2 696  | 3 094  | 2 886 | 8 840   |
| rolling_mid        | 2 754  | 3 168  | 2 618 | 8 597   |
| anchor             | 2 542  | 3 953  | 3 318 | 9 991   |
| depth_mid          | 1 400  | 1 910  | 1 243 | 4 719   |
| ewma_mid           |   684  |   921  | 1 044 | 2 695   |
| filtered_wall_mid  | 2 644  | 3 373  | 2 642 | 8 783   |
| hybrid_wall_micro  |   348  |   499  |   150 | 1 087   |
| mid                |   235  |   308  |   593 | 1 227   |
| microprice         |   253  |   298  |   553 | 1 195   |

### Reads

- **anchor** has the largest combined PnL, but its **cross-day
  dispersion is the widest** (2 542 → 3 953 → 3 318) and it spends
  **12 472 steps near the position limit** (≈42 % of all snapshots),
  meaning its book is chronically pinned. That PnL is potentially
  subsidised by the generous local fill model and may not survive an
  exchange that penalises stuck inventory.
- **wall_mid** (and its identical twin `filtered_wall_mid` on these
  thin 2–3 level books) is the **steadiest across days** and keeps
  inventory much healthier (near-limit ≈ 2 654 combined, ~9 %). It is
  the safest "robust default" candidate going into Phase 2.
- **weighted_mid / rolling_mid** are almost indistinguishable from
  `wall_mid` on PnL (8 840 / 8 597 / 8 783) but have *positive* `d_n1`
  markout deltas — i.e. they are slightly worse than plain `mid` at
  forecasting the next-step mid, even though they trade more.
- **depth_mid / ewma_mid** have the *best* markouts (`d_n1` ≈ −0.2)
  but quote much less — the current engine defaults under-exploit
  their signal. They are promising primaries for a maker-heavier
  variant in Phase 4.
- **mid / microprice** lose because their implied edge is smaller than
  the stable 16-tick spread, so they mostly idle.

### Residual analysis (aggregate, estimator - mid)

| Estimator          | \|resid\| mean | resid σ | skew | corr(resid, fwd_return h=1) |
|--------------------|---------------:|--------:|-----:|-----------------------------:|
| anchor             | 3.859 | 4.48 | +0.09 | **−0.200** |
| depth_mid          | 0.731 | 1.03 | −0.08 | **−0.602** |
| ewma_mid           | 0.733 | 0.98 | −0.07 | **−0.618** |
| wall_mid           | 1.022 | 1.36 | +0.03 | **−0.588** |
| hybrid_wall_micro  | 0.998 | 1.37 | −0.05 | **−0.609** |
| microprice         | 0.981 | 1.31 | +0.02 | **−0.502** |
| rolling_mid        | 1.380 | 1.81 | +0.01 | **−0.501** |
| weighted_mid       | 1.197 | 1.58 | +0.02 | **−0.551** |

- All micro estimators show strong **negative next-step return
  correlation with the residual**: when the estimator sits above mid,
  next-step mid drops; when below, it rises. That is exactly the
  signature of local mean reversion.
- `anchor` has a much weaker reversion signal (−0.200) — the anchor
  level is right on average but doesn't help forecast short-term
  direction.
- `ewma_mid` and `depth_mid` show the cleanest short-horizon reversion
  signal. They are strong candidates for a **Phase 2 strategy that
  takes on residual-driven entry**.

## C. Residual-based mean reversion summary

Positive vs negative residual buckets (h = 5 steps):

| Estimator          | Mean fwd return · resid > 0 | Mean fwd return · resid < 0 |
|--------------------|----------------------------:|----------------------------:|
| depth_mid          | −0.70 | +0.73 |
| ewma_mid           | −0.65 | +0.67 |
| wall_mid           | −0.70 | +0.73 |
| hybrid_wall_micro  | −0.75 | +0.78 |

There is a real ~±0.7-tick edge on 5-step markouts conditioning on
residual sign. That is roughly the magnitude needed to justify an
active maker/taker with a 1-tick edge budget once fees/slippage are
considered — but the replay fill model is generous, so this remains a
**leading hypothesis**, not proof.

## D. Bot / microstructure behaviour

- **Top-of-book volumes are clustered but not single-peaked.** The
  most common top-bid volumes are `{14, 12, 15, 10, 13}` with each
  appearing ~3 800–3 900 times (roughly 13 % of snapshots each). Same
  distribution on the ask side. The book is likely quoted by multiple
  market-maker bots with a **menu of canonical sizes in 10–15**, not a
  single persistent wall.
- **Spread is stable at 16 ticks.** `spread_spike_fraction` ≈ 1 %.
  This is consistent with the order book being almost always held
  open by resting bot quotes rather than being rebuilt after each
  crossing.
- **Trade tape:** 1 229 trades across three days (≈ 410/day).
  Trade-price offset vs simultaneous mid has `mean ≈ +0.15`,
  `std ≈ 8.2`, with histogram spikes at ±8 (388 at −8, ≈ 400 at +8).
  Trades print **at the touch** (mid ± 8 = best bid / best ask),
  confirming that external aggressors lift the bot quotes at the
  spread edges; there is no evidence of systematic hidden fills
  between the touches.
- **Counterparty inference is impossible:** all `buyer`/`seller`
  fields in the trade tape are blank on all three days. Any further
  bot inference must come from size patterns, timing, and book
  reshape behaviour — not IDs.

## E. Conclusions

- **What the product appears to be:** a **wide-spread, anchored
  oscillator**. Mid is glued to 10 000 ± 5, with 16-tick canonical
  spread, quoted by multiple bots cycling through a 10–15 size menu.
- **Strongest fair-value family under local replay:** `wall_mid` and
  its clones. It is the most cross-day consistent; `weighted_mid` and
  `rolling_mid` are nearly identical and worth keeping as a parallel
  alternate. `ewma_mid` / `depth_mid` have the cleanest short-horizon
  markouts but under-trade with the current edge defaults.
- **Execution read:** the product is **maker-dominant**. A 16-tick
  spread gives ample room to quote an inside-touch two-sided maker
  pair with room to skew against inventory. Taker edge is unlikely to
  be the dominant source of profit unless spread compresses — and it
  doesn't in the Phase-1 data.
- **Anchor as primary is risky:** the 9 991 combined PnL is misleading
  because it rides on 12 472 near-limit steps (42 %). A tighter
  limit, a less permissive local fill model, or an official exchange
  that throttles pinned books may erase that PnL. Keep `anchor` only
  as a fallback / sanity input.

## F. Still uncertain — things Phase 2–4 must decide

1. **Maker vs hybrid:** is the inside-touch maker fill rate actually
   reproducible on the official exchange, or is local replay too
   generous? This is the single biggest open question.
2. **Real position limit.** The Phase-1 placeholder (50) affects
   near-limit counts and therefore the anchor/wall_mid tradeoff. Once
   the official limit is confirmed, the sweeps in Phase 4 must be
   redone.
3. **Does the anchor actually move?** Three days is a short sample.
   The 10 000 centre is visually stable but must be monitored for
   regime shifts in later data.
4. **Best micro fair value for a maker strategy:** `wall_mid` vs
   `ewma_mid` vs `depth_mid`. The three give different PnL/markout
   trade-offs with Phase-1 defaults; Phase 4 Stage A should sweep only
   quote edges with each candidate and read the best from markouts.
5. **Residual-driven take overlay.** The −0.6 short-horizon reversion
   correlation suggests a small residual-triggered taker could add
   edge, but only if the take edge is ≥ 1 tick beyond the local
   micro-fair. Needs Phase 4 Stage B testing.

## G. Phase-1 data artefacts backing this dossier

- `outputs/round_1/eda/20260414T130527Z_round1_dossier_phase1/ash_coated_osmium_eda.json`
- `outputs/round_1/fair_value_comparison/20260414T130741Z_round1_fv_phase1_ASH_COATED_OSMIUM/`
- Per-day replay summaries are reproducible with:
  `PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_fv_compare --label <label>`

# INTARIAN_PEPPER_ROOT — Round 1 Product Dossier

**Scope:** Phase 1 market-structure analysis using three days of replay
data (`day_-2`, `day_-1`, `day_0`; 30 000 snapshots, 27 688 two-sided).
No strategy has been implemented.

> **Corrigendum (Phase 5).** This dossier repeatedly describes an
> **"overnight +1 000 jump"** between consecutive days. That framing
> was a misread. The daily *mean* mid rises by +1 000 per day because
> the +0.1-per-step intraday drift continues *across* day boundaries —
> day -2 closes at mid ≈ 11 001, day -1 opens at mid ≈ 10 998
> (Δ ≈ −3 ticks); day -1 closes at ≈ 11 998, day 0 opens at ≈ 11 998
> (Δ ≈ 0). The mid path is **continuous**, not discontinuous, on the
> sample data. Any reasoning in this dossier that depends on a
> discontinuous transition (overnight flatten to dodge a jump,
> inventory-sign risk at day close, etc.) is **invalidated**. The
> drift magnitude and per-day linear fit are still correct; only the
> day-to-day transition interpretation changes. See
> `outputs/round_1/notes/phase5_review_shortlist.md` and
> `outputs/round_1/notes/phase5_pepper_day_boundary.md` for the
> corrected analysis.

## TL;DR

- Leading hypothesis ("trend-fair with local reversion") is
  **supported and sharper than expected**: the mid follows an almost
  deterministic drift of **+0.1 ticks per timestamp step** (1 000
  ticks per 10 000-step day), and the drift **continues across day
  boundaries** — so the daily mean is +1 000 higher each day but the
  mid path is continuous (see corrigendum above; the original draft
  said "overnight jump of +1 000 ticks", which was wrong).
- σ of mid around that linear fit is only **~1.1–1.3 ticks** — the
  price sits on the drift with a tight ~±1-tick noise envelope.
- In the Phase-1 replay (placeholder limit=50), **lagging
  fair-values lose badly**. `mid`, `rolling_mid`, `weighted_mid` and
  `microprice` all post *negative* combined PnL (−67k, −36k, −8k, −65k
  respectively). **Book-aware, forward-leaning estimators win**:
  `depth_mid` (+40 428 combined PnL, top-2 every day), `ewma_mid`
  (+29 066), `hybrid_wall_micro` (+33 318). `wall_mid` does well on
  days -2 and -1 but loses on day 0 — **it is not cross-day robust**.
- `depth_mid` is the **current strongest PnL+robustness pick** for
  Phase 1 purposes; `hybrid_wall_micro` is the strongest markout-per-
  trade pick. A **custom drift-projecting estimator** (fair =
  base + slope × timestamp, calibrated live) is the single biggest
  open research idea for Phase 2.
- Execution read: spread is moderate (median 12–14, widening +1/day).
  With σ(noise) around the drift of ~1 tick, taker trades against
  stale quotes should have positive markout when the drift is
  correctly tracked. This product is likely **taker-first or mixed**,
  not maker-first.

## Key numbers (three-day aggregate, cleaned to two-sided snapshots)

| Day | n | mean mid | σ | min | max | range | spread mean | spread median |
|-----|---|----------|---|-----|-----|-------|-------------|---------------|
| -2  | 9 216 | 10 500.57 | 287.92 |  9 998.5 | 11 001.5 | 1 003 | 11.99 | 12 |
| -1  | 9 219 | 11 501.41 | 287.62 | 10 998.0 | 12 001.0 | 1 003 | 13.01 | 13 |
|  0  | 9 253 | 12 500.96 | 288.18 | 11 998.5 | 13 000.5 | 1 002 | 14.13 | 14 |

The daily standard deviation σ ≈ 288 is almost exactly
`range / √12 ≈ 289`, which is the σ of a uniform distribution over
the daily band. Combined with a near-perfect linear fit, **the price
moves linearly from the day's low to the day's high within a day**
(no material mean reversion to a single intraday level, only to the
line).

## A. Price and spread structure

- **Intraday drift:** simple OLS fit of `mid` against `timestamp` on
  each day:

  | Day | slope / step | intercept | residual σ | residual \|mean\| |
  |-----|-------------:|----------:|-----------:|------------------:|
  | -2  | +0.1000 | 10 000.0 | 1.12 | 0.89 |
  | -1  | +0.1000 | 10 999.9 | 1.26 | 0.99 |
  |  0  | +0.1000 | 12 000.0 | 1.34 | 1.07 |

  The slope is **identical on all three days** and the intercept is
  exactly `10 000 + 1 000 × (day + 2)`. This is almost certainly an
  engineered, deterministic process (within 1-tick rounding).

- **Inter-day shift:** means jump +1 000.84 then +999.55, i.e.
  **exactly +1 000 overnight**. The inter-day jump is larger than the
  daily oscillation around the line (σ ≈ 1.2) by three orders of
  magnitude, so any strategy that treats days in isolation is safe;
  any strategy that tries to carry state across day boundaries must
  handle the jump.

- **Spread:** widens +1 tick per day (12 → 13 → 14). Median spread is
  ≈ 6× the daily noise σ. One-sided book fraction 7.7%; spread-spike
  fraction 1.2%.

## B. Fair-value candidates

### Combined replay (three days, 27 688 two-sided snapshots)

| Estimator          | cov % | mae_now | mae_n1 | d_n1   | PnL (3-day) | Trades | mk% | Near-limit |
|--------------------|------:|--------:|-------:|-------:|------------:|-------:|----:|-----------:|
| depth_mid          |  92.3 | 0.595   | 0.943  | −0.136 |  **40 428** |  817   | 0.9 |  1 762 |
| hybrid_wall_micro  |  92.3 | 0.784   | 0.911  | −0.167 |  **33 318** |  584   | 0.4 |      0 |
| ewma_mid           | 100.0 | 0.665   | 0.949  | −0.129 |  29 066     |  829   | 0.3 |    568 |
| wall_mid           |  92.3 | 0.865   | 0.955  | −0.123 |  18 662     |  897   | 0.7 |  3 180 |
| filtered_wall_mid  |  92.3 | 0.865   | 0.955  | −0.123 |  18 662     |  897   | 0.7 |  3 180 |
| weighted_mid       | 100.0 | 1.860   | 1.969  | +0.890 |  −8 133     |  901   | 1.3 |  2 786 |
| rolling_mid        | 100.0 | 2.688   | 2.792  | +1.714 | −36 390     |  878   | 1.5 |  4 020 |
| microprice         |  92.3 | 0.705   | 1.010  | −0.068 | −65 277     |   79   |21.3 |  1 798 |
| mid                |  92.3 | 0.000   | 1.078  | +0.000 | −67 397     |   49   |13.4 |  6 290 |

### Cross-day robustness (PnL only)

| Estimator          | Day -2 | Day -1 | Day 0 | Combined |
|--------------------|-------:|-------:|------:|---------:|
| depth_mid          | 15 360 | 13 471 | 10 366 | **+40 428** |
| hybrid_wall_micro  | 12 112 | 10 799 | 10 587 | **+33 318** |
| ewma_mid           | 14 294 |  6 148 |  7 262 | +29 066 |
| wall_mid           | 16 292 |  2 358 |   −184 | +18 662 |
| filtered_wall_mid  | 16 292 |  2 358 |   −184 | +18 662 |
| weighted_mid       |  6 315 | −5 338 | −7 148 |  −8 133 |
| rolling_mid        | −7 780 |−14 548 |−11 725 | −36 390 |
| microprice         | −9 806 | −4 178 |−11 015 | −65 277 (combined run) |
| mid                |−10 268 | −8 639 |−13 831 | −67 397 (combined run) |

> The single-day PnLs for `mid`/`microprice` don't sum to the combined
> row because the combined run carries position across day boundaries
> — it is penalised by the overnight +1 000 jump. This is a **material
> property of the product**: a strategy holding inventory overnight
> either collects or pays that 1 000-tick step depending on sign. All
> serious candidates finish with very small net positions each day.

### Reads

- **Lagging (memory-based) estimators lose**. `mid`, `rolling_mid`,
  `weighted_mid`, `microprice` all print negative combined PnL.
  `rolling_mid` and `weighted_mid` lag a rising mid by 2–3 ticks
  (|resid|=2.69, 1.86) and get adverse-selected on trend. `mid`
  itself yields only ±1-tick edges, which is below the 12–14-tick
  spread, so it hardly quotes and accumulates a bad position at
  crossings.
- **`depth_mid` wins outright** on PnL, with the smallest current-mid
  residual (|resid|=0.595) and strong short-horizon markouts
  (d_n1=−0.136). It trades 817 times and never holds a large position
  (near_limit 1 762 combined, ~2 %).
- **`hybrid_wall_micro` has the best markouts** (mae_n1=0.911,
  d_n1=−0.167) and zero combined near-limit steps. Trades less (584)
  but quality per trade is highest.
- **`ewma_mid` is a strong mid-ground**: cross-day stable (14k / 6k /
  7k), low inventory risk.
- **`wall_mid` is fragile**: great on day -2 (+16 292) but collapses
  on day 0 (−184). Likely the wall reaches wrong levels when the drift
  is on.

### Residual analysis (aggregate, estimator − mid)

| Estimator          | \|resid\| mean | resid σ | skew | corr(resid, fwd_return h=1) |
|--------------------|---------------:|--------:|-----:|-----------------------------:|
| depth_mid          | 0.595 | 0.76 | +0.03 | **−0.576** |
| ewma_mid           | 0.665 | 0.87 | −0.02 | **−0.646** |
| hybrid_wall_micro  | 0.784 | 1.13 | −0.02 | **−0.593** |
| wall_mid           | 0.865 | 1.25 | +0.01 | **−0.563** |
| microprice         | 0.705 | 1.07 | +0.00 | **−0.459** |
| weighted_mid       | 1.860 | 2.52 | +0.04 | **−0.692** |
| rolling_mid        | 2.688 | 3.73 | +0.05 | **−0.693** |
| mid                | 0.000 | 0.00 |  n/a  | n/a |

- All micro-aware estimators show strong negative corr with next-step
  return; same reversion signature as ASH.
- But **the product is trending**, so this reversion is around the
  drift line, not around a static anchor. Estimators that sit below
  the current drift-adjusted fair (e.g. `rolling_mid`, `weighted_mid`)
  show the strongest apparent reversion but bleed PnL because they
  systematically *pay the trend*.

## C. Structural fair candidate not currently in the estimator zoo

The per-day fit strongly suggests a **deterministic drift-plus-noise
model**:

    fair(t, day) = 10 000 + 1 000 × (day + 2) + 0.1 × timestamp + ε,
                   ε ≈ N(0, 1.2)

This is not any existing estimator. A **custom trend-fair estimator**
that tracks the drift online (e.g. Kalman on mid with known slope, or
online linear regression over recent mids) should in principle
out-perform every estimator in the zoo.

Evidence:
- The drift slope is essentially constant (0.1 / timestamp) on all
  three days.
- Residual σ around the line is 1.1–1.3 — smaller than any current
  estimator's |resid| mean (depth_mid’s 0.595 |resid| is vs *mid*, not
  vs the drift line).
- The biggest risk for a trend-fair strategy is: (a) mis-estimating
  the slope on a new day, and (b) handling the overnight +1 000 jump.

This is the **single most promising idea** flagged by Phase 1 for
Phase 2 discussion.

## D. Bot / microstructure behaviour

- **Top-of-book volumes** are clustered at 8–12 (each appears in
  ~47–49 % of snapshots) on both sides, slightly narrower menu than
  ASH. Suggests market-maker bots with a small quote-size menu.
- **Spread widening across days** (12 → 13 → 14) with σ ≈ 2.6 is
  consistent with bots slightly increasing their spread as daily
  volatility grows (the drift range is constant, but noise and
  crossings may intensify). Not a regime-change signal.
- **Trade tape:** 1 103 trades across three days. Offset vs
  simultaneous mid has `mean = −0.39`, `std = 5.6`, histogram peaks at
  ±6 (≈ half-spread on day -2) and ±7/±8 (day 0). Trades print at the
  touch; the negative mean offset is most likely because mid itself
  is rising (the "mid at trade time" sample is slightly below the mid
  measured at the end of the 100-step interval).
- **Counterparty fields** are blank on all three days; no bot ID to
  mine.

## E. Conclusions

- **What the product appears to be:** a **deterministic-drift
  oscillator** with a moderate spread. Intraday price advances by
  +0.1 per timestamp ≈ +10 ticks per 100-step update, and jumps
  +1 000 overnight. The 1-tick noise envelope around the line is
  thick enough for a local reversion trade but small compared to the
  12–14 tick spread.
- **Strongest fair-value family under local replay:** `depth_mid`
  (best PnL + best cross-day consistency), followed by
  `hybrid_wall_micro` (best markout-per-trade + zero near-limit
  steps). `ewma_mid` is a safer mid-ground. None of these explicitly
  project the drift — the opportunity for a proper drift estimator is
  open and strong.
- **Execution read:** this looks like a **taker-first / mixed**
  product, not a maker-first product. Maker quotes centered on a
  lagging fair value will be hit adversely by the drift. A strategy
  that takes the ask when the drift-adjusted fair is clearly above
  the current best ask (and vice versa) has a natural edge.

## F. Still uncertain — things Phase 2–4 must decide

1. **Can the drift be estimated live?** Phase 2 should propose at
   least one candidate (e.g. online OLS with a small window, or a
   Kalman filter with fixed slope prior +0.1 / step and unknown
   base). Phase 4A should test it.
2. **What is the true position limit?** Phase-1 placeholder was 50.
   Too-small limit kills the drift-trade; too-large risks PnL
   volatility from the overnight jump.
3. **Overnight jump handling.** Do we always flat at end-of-day? Do
   we explicitly model the +1 000 reset and restart inventory fresh?
   Needs a Phase 2 decision.
4. **Is the slope stable on unseen days?** Three days share the same
   slope exactly. This is very clean — suspiciously clean — and could
   reflect a fixed simulator process. It must be **verified**
   on official IMC data; if it breaks, the whole strategy breaks.
5. **How aggressive can the taker be?** With spread = 12–14, a taker
   that waits for a clean drift-adjusted residual of 3+ ticks
   (e.g., best_ask − drift_fair < −3) would fire less often but with
   high markout. Phase 4 Stage B should sweep the take threshold.

## G. Phase-1 data artefacts backing this dossier

- `outputs/round_1/eda/20260414T130527Z_round1_dossier_phase1/intarian_pepper_root_eda.json`
- `outputs/round_1/fair_value_comparison/20260414T130807Z_round1_fv_phase1_INTARIAN_PEPPER_ROOT/`
- Per-day replay summaries reproducible with:
  `PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_fv_compare --label <label>`

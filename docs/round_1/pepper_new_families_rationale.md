# PEPPER — Five New Strategy Families: Design & No-Overfit Rationale

**Status:** research-only. None of these strategies are registered
in `STRATEGY_REGISTRY`. They follow the same "inlined-via-export-bundle"
pattern as `PepperCoreLongStrategy` (V2_clean / V3_nearhold).

**Dated:** 2026-04-16. All parameter values are chosen from
first-principles microstructure observations valid across all 3 real
training days, not fitted to day-0 specifically.

## Why a new family at all

The V3_nearhold / core-long family is saturated on drift-up tape.
Local Phase-11 frontier shows real-day mean of 79,417 — essentially
indistinguishable from buy-and-hold (79,381) — and all improvements
beyond this point are robustness to synthetic reversed/stepped tapes.
On the actual Round-1 official day (+0.1 slope, no reversal, no step),
buy-and-hold and V3 produce **the same 7,286 PEPPER PnL**.

To push PEPPER above 7,286 we have to exploit degrees of freedom that
no existing candidate touches:

| # | Lever | What's not currently used |
|---|-------|---------------------------|
| 1 | Passive maker fills | All V2-V4 configs are `exec_style="taker"` dominant |
| 2 | Drift-relative asymmetric quoting | Fodra-Labadie was cited in memos, never implemented |
| 3 | Top-of-book imbalance as timer | 0.56 correlation with next-tick move, unused |
| 4 | Trade-tape (aggressor flow) signal | `snapshot.trades` never read by any PEPPER strategy |
| 5 | Passive-first opening execution | All openers are taker crosses (level1 or all_asks) |

Each new family attacks exactly one of these.

## No-overfit discipline (applies to all 5)

1. **Parameter values are derived from observed microstructure, not
   optimized against one day.** Edges in ticks (`base_edge=3` ≈ 1/4 of
   modal 13-tick spread), slope scale factors chosen so observed
   +0.1/tick slope produces order-of-magnitude-1 edge asymmetry,
   EWMA half-lives in tick units.
2. **All new knobs default to inert / safe values.** Every candidate
   is a small superset of the baseline it inherits from; passing
   `core_target=0` / `seed_size=0` reduces each to a simpler form.
3. **Core position target ≤ 60, never 80.** Full long is buy-and-hold;
   leaving headroom is the whole point of each family.
4. **Loose r² gates (0.30).** The repo's own guard-carry sweep found
   tight r² gates (0.7+) made the guard inert on real data. 0.30
   keeps the safety nets meaningful.
5. **No micro-tuned values.** Every parameter is round (3, 5, 0.30,
   20) so it's visible the choice wasn't fit to a specific PnL peak.

## Candidate 1 — `pepper_passive_maker`

**Thesis.** PEPPER's 13-tick spread is much wider than the 2-3-tick
residual noise band. Taker round-trips cannot profitably cycle
inventory through the spread. Maker quotes posted *inside* the touch
can. With positive drift, asymmetric maker edges (tighter bid, wider
ask) give passive fills a long bias that aligns with the drift.

**Params (shipping):**

| Param | Value | Why |
|---|---:|---|
| `bid_edge` | 3.0 | ~¼ of modal 13-tick spread |
| `ask_edge` | 5.0 | Asymmetric: wider on the side against the drift |
| `quote_size` | 5 | Matches default `ProductConfig.quote_size` |
| `core_target` | 40 | Leaves 40 units of headroom for cycling |
| `inventory_skew_coef` | 0.04 | Soft bias back to core_target without dominating the asymmetry |
| `seed_mode` | "passive" | Never taker-open without trying passive first |
| `seed_size` | 40 | Match core_target; open acquires to the resting target |
| `seed_window` | 500 | Same as V3; apples-to-apples timing |
| `seed_taker_fallback_after` | 3 | After 3 ticks unfilled, fallback to taker |
| `min_spread_for_maker` | 4 | Skip maker quoting when spread collapses (rare) |

**Expected behavior on Round-1 tape:** bootstrap ≈ 40 long over first
3-5 ticks via passive+fallback; steady-state cycle ±10 units through
inside-spread fills; drift-carry on the 40-unit core.

## Candidate 2 — `pepper_drift_asymmetric`

**Thesis.** Fodra-Labadie (2012): the optimal MM response to a
non-martingale drifting price is asymmetric quoting favoring fills
on the side aligned with the trend. Our cited paper; never
implemented.

**Params (shipping):**

| Param | Value | Why |
|---|---:|---|
| `base_edge` | 3.0 | Same symmetric starting point |
| `slope_skew_factor` | 10.0 | Observed +0.1/tick slope → +1-tick asymmetry (~33% of base) |
| `max_asymmetry` | 3.0 | Cap so slope noise can't collapse the quotes to one-sided |
| `slope_window` | 32 | Matches default `linear_drift` `history_length` |
| `slope_r2_min` | 0.30 | Loose confidence filter; tight gates are inert |
| `core_target` | 50 | Mid-range |
| `inventory_skew_coef` | 0.05 | Active inventory correction |
| `reversal_slope_threshold` | 0.02 | Triggers when slope is 20% of observed magnitude (significant but not rare) |
| `reversal_r2_min` | 0.30 | Symmetric with signal gate |
| `reversal_target` | 0 | Go flat on strong reversal (safety) |

**Expected behavior:** on +0.1 drift tape, asymmetry = min(3, 10 × 0.1)
= 1 tick → bid_edge 2, ask_edge 4; inventory skew pushes quotes
gradually back to 50. On a reversal, collapses to flat.

## Candidate 3 — `pepper_imbalance_timer`

**Thesis.** Top-of-book imbalance (from `NormalizedSnapshot.book_imbalance`,
already exposed as a property on the snapshot) has 0.56 correlation
with next-tick mid on PEPPER. Use it as a **timer**, not as standalone
alpha — the drift remains the primary.

**Params (shipping):**

| Param | Value | Why |
|---|---:|---|
| `add_imbalance_threshold` | 0.30 | ~2:1 bid-heavy; meaningful above-noise signal |
| `trim_imbalance_threshold` | 0.30 | Symmetric |
| `add_size` / `trim_size` | 4 / 4 | ~5% of limit per event; many events/day |
| `max_add_mid_above_fair` | 2.0 | Don't chase: only add when price is reasonable |
| `min_trim_mid_above_fair` | 2.0 | Don't donate: only trim when price is rich |
| `core_target` | 60 | Higher anchor — drift still dominates |
| `background_quote_size` | 3 | Small continuous maker between events |
| `min_top_depth` | 8 | Reject thin-book imbalance signal |

**Expected behavior:** ~40-80 imbalance-triggered events/day adding
~4 units each; background maker continues between events; drift-carry
on the 60-unit core.

## Candidate 4 — `pepper_flow_overlay`

**Thesis.** Market trades (`snapshot.trades`) encode aggressor flow.
Positive EWMA of net-aggressor-flow → buyers dominating → short-horizon
pressure is up. No PEPPER strategy in the repo reads `snapshot.trades`.

**Params (shipping):**

| Param | Value | Why |
|---|---:|---|
| `flow_decay` | 0.85 | EWMA half-life ≈ 4.3 ticks; captures momentum without over-reacting |
| `flow_scale` | 0.5 | Each unit of net flow adds 0.5 target position units (conservative) |
| `flow_bias_size` | 20 | 25% of limit; meaningful bias but doesn't dominate core |
| `flow_min_magnitude` | 2.0 | Noise floor — ignore single-trade noise |
| `core_long` | 50 | Mid-range |
| `step` | 8 | Matches V3 rate limit |
| `taker_edge` | 1.5 | Conservative crossing |
| `maker_quote_size` | 3 | Small continuous maker background |

**Expected behavior:** target oscillates around 50 ± 20 depending on
recent aggressor balance. Drift carry on 50 + flow-timed extra 20 when
flow is strong and persistent.

## Candidate 5 — `pepper_passive_opener`

**Thesis.** Current opening execution pays full half-spread (~7 ticks)
on 30-80 opening units = 200-1,200 ticks donated at t=0. Post passive
bid at `best_bid+1` for 3 ticks first; fallback to taker only if
not filled.

**Params (shipping):**

| Param | Value | Why |
|---|---:|---|
| `opening_passive_window` | 3 | 3 ticks × 0.1 drift = 0.3 tick of drift-miss per unit waited |
| `opening_taker_fallback_tick` | 3 | Start taker at end of passive window |
| `passive_bid_improve` | 1 | Minimum improvement = max fill prob at min chase cost |
| `opening_max_size_per_tick` | 20 | Conservative pace; never oversize |
| `seed_size` | 40 | Match other candidates |
| `steady_core_target` | 40 | Same |
| `maker_bid_edge` / `maker_ask_edge` | 3.0 / 5.0 | Same asymmetric as PassiveMaker |
| `inventory_skew_coef` | 0.04 | Same |

**Expected behavior:** first 0-3 ticks: passive bid at best_bid+1.
If seed met: transition to steady-state maker. If not: taker fallback
at tick 3 finishes the seed.

## How to turn any candidate into a submission

1. **Research harness (fast iteration):** use
   `src.strategies.round_1_pepper_candidates.build_candidate_strategy`
   in a research script analogous to
   `outputs/round_1/pepper_sparse_overlay/run_search.py`.
2. **Official bundle:** replicate the V3_nearhold export pattern
   (`src/scripts/round_1/export_round1_v3_nearhold.py`):
   - inline the relevant strategy module (`pepper_passive_maker.py`,
     etc.) via `strip_module`
   - inline `round_1_pepper_candidates.py` similarly
   - rewire `Trader.__init__` to select the candidate's factory
   - keep the ASH leg as-is (K2 or the current best ASH config)
3. **Evaluation:** every candidate should be scored on the
   calibrated local fill model (see the outstanding calibration item
   in the Round-1 plan) before any upload slot is spent. Local score
   alone remains untrustworthy until the sim is calibrated against an
   official log.

## Expected incremental PnL (calibrated estimates)

Given the spread is 13 and residual noise is 2-3 ticks, and 27
bot-to-bot trades spanned 12,000–12,097 on j2's official day:

| Candidate | Primary lever | Pessimistic | Base | Optimistic |
|---|---|---:|---:|---:|
| passive_maker | inside-spread fills | +100 | +400 | +1,200 |
| drift_asymmetric | skewed maker fills | +50 | +250 | +800 |
| imbalance_timer | timed adds/trims | +50 | +200 | +600 |
| flow_overlay | momentum bias | +30 | +150 | +500 |
| passive_opener | cheaper entry | +80 | +200 | +400 |

These are additive-on-top-of buy-and-hold estimates. The candidates
are **not mutually exclusive** — the eventual "best PEPPER" strategy
will likely combine 2-3 (e.g. passive_maker + passive_opener) once
the winners on calibrated sim are known. Each is built standalone for
clean ablation.

## What's NOT in this family and why

- **No ML.** Sample size too small and structure too simple — overfit
  risk dominates.
- **No momentum-chasing taker strategies.** Spread too wide; round-trip
  taker cost exceeds residual amplitude.
- **No `depth_mid` as primary FV.** Fallback-chain safety issue is
  fixable, but unrelated to the 5 levers above.
- **No multi-product signals.** ASH-PEPPER cross-signal exploration is
  a separate research track.

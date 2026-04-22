# Critical Evaluation — Synthesis of 4-Agent Deep Dive

**Compiled:** 2026-04-22. After 4 parallel research agents + forensic verification against IMC simulator truth source.

**Bottom line: the 4-5× ASH gap is mechanical, not architectural. We use the wrong fair-value source and place quotes at the wrong levels. No OBI exploitation, no asymmetric quoting, no directional taker — top teams don't use those on stable products either.**

---

## 1. Truth source established

`outputs/round_2/Official Results/` contains 4 variants × 4 runs = 16 IMC simulator runs on 100k-tick samples. Each `.json` / `.log` file is the source of truth. Multiply per-sample × 10 → scored round P&L estimate.

### Per-product decomposition

| Variant | ASH (mean of 4) | PEPPER (mean) | Total mean |
|---|---|---|---|
| v5 | **818** | 7,154 | 7,972 |
| Ash L1 | 612 | **7,340** | 7,952 |
| Killswitch | 708 | 7,104 | 7,812 |
| Promoted (wide_w113) | 743 | 6,911 | 7,654 |

### The gap

- **We ship: 7,654-7,972 per sample = 76-80k per round.** User's 2-round total ≈ 179k ✓.
- **Top teams: 10-12k per sample = 100-120k per round.** Top-10 cluster at 225-240k for 2 rounds.
- **Gap per round: ~25-30k. ~25k/round = ~2,500/sample.**
- **PEPPER is near theoretical cap** (0.1 × 80 × 1000 = 8,000 max; we hit 6,900-7,340; top teams cap at 8,000). Max upside: +500-700/sample.
- **Remainder of gap (~1,800-2,000/sample) is on ASH.** Top teams extract 3,000-4,500 from ASH; we extract 612-818. **~4-5× gap.**

---

## 2. Four agents, four independent lines of evidence, one convergent conclusion

### Agent F1 — Forensic mining of our own 16 IMC simulator logs

- **MM-only architectural ceiling ≈ 1,000 shells on ASH.** No run crossed 1,000 across all 16 runs. Best: v5 run4 at 966.
- **Last-third bleed:** last 33% of each sample gains only 26-87 shells vs mid-third 400-470. Inventory builds up during mean-revert, late-sample drift punishes it.
- **Deterministic sim event at t=84,500:** EVERY variant in EVERY run loses -46 to -52 shells at this exact snapshot. Kill-switch before this tick = +50/run × 4 = +200.
- **Missed directional capture: 14%.** 13-16 windows/run with |Δmid|≥5 over 10 snapshots. Theoretical capture ≈ 4,000/run. We capture ~600.
- **v5's +75 over Promoted is NOISE.** High-vol snapshots: -1.2 shells. Low-vol: +76.6. Sweep winner was an artifact.
- **OBI directional ratio confirmed: 56% down vs 28% up at strong_neg OBI (2:1).** Real signal. But our symmetric MM's mean P&L is HIGHEST in strong_neg OBI (passive absorbtion of cheap asks). Signal exists but un-monetizable by symmetric MM.
- **PEPPER gap decomposition:** ~560 spread-crossing (unavoidable), ~200 slow ramp (FIXABLE, Ash L1 hits full-long 75% of snapshots vs Promoted 58%), ~350 mean-reversion hits (FIXABLE with kill-switch).
- **F1's wrong conclusion:** "rest of the gap is unavailable to pure MM architectures." F2 proves this is false.

### Agent F2 — Top-team MM code archaeology (decisive)

Across 8 top-team repos (P1 Stanford Cardinal; P2 Linear Utility, jmerle, pe049395; P3 chrispyroberts, CarterT27, TimoDiehm, Sylvain-Topeza):

- **`grep -i imbalance|obi|microprice|ofi|order_flow|book_imbalance` across all 8 stable/MR handlers = 0 hits.** Top teams do NOT use OBI on stable products.
- **All 8 teams quote symmetric two-sided on AMETHYSTS / PEARLS / RESIN.** No asymmetric quoting on stable products.
- **Directional taker overlays only on VOLATILE products (KELP, SQUID_INK) triggered by named-trader signals (Olivia) or MA-crossover. Never from OBI. Never on stable products.**
- **Convergent mechanism across all 8:**
  1. **Volume-robust mid as fair value:** wall-mid / max-amount-mid / size-filtered mid. NOT raw mid, NOT time-smoothed.
  2. **Quotes INSIDE the wall:** `bid = max_amt_bid + 1`, `ask = max_amt_ask - 1`.
- **Specific evidence:**
  - `pe049395/submissions/round5.py:782-786, 822-826`: hard clamp `p_b ≥ maxamt_bidprc + 1`
  - `timo/FrankfurtHedgehogs_polished.py:303-304`: `bid_price = bid_wall + 1`
  - `linear_utility/round1/round_1_v6.py:285`: `ask = best_ask_above_fair − 1`
  - `chrispyroberts`: wall_mid
  - `carter`: filtered by size ≥ 10
- **"SST template"** (take / clear / make with explicit `take_width`, `clear_width`, `disregard_edge`, `join_edge`, `default_edge`, `manage_position`, `prevent_adverse`): written by Linear Utility, ported verbatim by Sylvain. Battle-tested scaffold.
- **Stanford's stacked-maker pattern** (3 MM layers per side conditional on position sign) is a unique outlier, not carried forward. Worth experimenting with if SST saturates.

### Agent F3 — Academic OBI exploitation architectures

- **Confirmed our D4 finding:** Avellaneda-Stoikov reservation-price skew is an INVENTORY mechanism, not a directional-signal mechanism. Top teams' skew-placement frameworks use asymmetric EDGES, not shifted center.
- **Three architectures that would work IF OBI signal survives validation:**
  1. Microprice placement (Stoikov 2018) — simplest
  2. Asymmetric-edge quoting (Cartea-Jaimungal 2014): `δ_a* = baseline − α·E[ΔS|I]·τ`, `δ_b* = baseline + α·E[ΔS|I]·τ`
  3. Taker overlay (Hendershott-Menkveld, Cartea-Jaimungal-Penalva) — requires signal half-life > 5 ticks
- **BIG RED FLAG: +0.52 OBI IC is suspiciously high.** Published ICs are 0.05-0.15. Likely endogenous re-pricing / leakage / overfit. F3 proposes 4 validation tests (shuffle, strict-lag, remove-own-quotes, walk-forward).
- **Uplift if validated:** IC 0.2-0.5 → 15-40% uplift; IC 0.05-0.2 → 5-15%.

**Combined with F2's finding (no top team exploits OBI), this supports: either OBI IC is inflated or top teams tried and it didn't work. Either way, OBI-based architecture is not the path for stable products.**

### Agent F4 — Hidden microstructure alpha

Top 5 ranked findings:
1. **Wall-mid fair value + quote inside wall** (same as F2, independently derived). Biggest single fix.
2. Toxic-size filter (widen on size 1-2 adversely-selected prints).
3. Flatten-at-fair at position skew (transcript-1 "R1 optimization most teams missed").
4. Drift-aware MM on PEPPER (TimoDiehm KELP pattern for stable+drift combination).
5. 2-deep penny-jumping.
Plus: explicitly ruled out Olivia-class bot on R1/R2 (only exists on volatile products), hardcoded timestamps (banned post-P2-R2), iceberg refills on R1/R2 (no evidence), time-of-day seasonality on ASH/PEPPER (no signal source).

**F4 explicit build budget: 19h closes the ASH gap from 700 → ~3,500/sample.**

---

## 3. The synthesis — what to do and what NOT to do

### DO (ranked by evidence × impact)

| # | Fix | Hours | Evidence |
|---|---|---|---|
| **1** | **Swap ASH `fair_value_method` from `weighted_mid` → `filtered_wall_mid`** | **1h** | F2 (4 repos) + F4 independent |
| **2** | **Place quotes INSIDE the wall: `bid = max_amt_bid + 1`, `ask = max_amt_ask - 1`** | **3-4h** | F2 across pe049395, timo, linear_utility |
| 3 | Port SST template (take / clear / make with explicit edges) | 6-8h | F2 — Linear Utility + Sylvain |
| 4 | Toxic-size filter — widen when recent trade sizes are 1-2 | 3h | F4 — pe049395 |
| 5 | Flatten-at-fair for position reduction | 2-3h | F4 + transcript-1 |
| 6 | Drift-aware MM overlay on PEPPER | 3-4h | F4 — TimoDiehm KELP |
| 7 | Deterministic kill-switch at t=84,500 | 1h | F1 — identical loss across 16 runs |
| 8 | Ash-L1 PEPPER ramp logic into Promoted | 2h | F1 forensic — 75% vs 58% full-long occupancy |

**Total: ~21 hours. Estimated impact: close most of ASH gap + ~500 PEPPER uplift = ~2,000-3,000 shells/sample = ~20-30k/round.** That matches or exceeds the top-10 gap.

### EXPLICITLY DO NOT BUILD

Four agents converge on rejecting these:
- **OBI-based asymmetric quoting** on stable products. F2: zero top teams do it. F3: IC probably inflated.
- **Directional taker overlay triggered by OBI** on stable products. Same reason.
- **Microprice placement as primary FV on stable products.** Same — top teams use wall-mid, not microprice, for stable.
- **Counterparty-informed-flow detection on R1/R2.** F4: Olivia only appears on volatile products; no informed bot on stable R1/R2 products.
- **Bayesian ensemble FV / neural predictor** as the primary blueprint from previous plans. Top teams don't. Revisit only if #1-8 saturate.
- **Variance swaps, AMMs, perpetuals, auction crosses** (from earlier creative forecast). Low probability for P4 and orthogonal to closing the current gap.

### DEFER TO R3 SPECIFICALLY

These were in previous plans but are only relevant once baskets/options/macarons appear in R3+:
- Cross-product PortfolioContext (F4 pair test ρ≈0 for R1/R2, mechanical ρ≈0.7 for baskets)
- Residual-allocator default=True (marginal on R1/R2 MM, material on R3 arb)
- Counterparty intelligence engine (no informed bot on R1/R2; build as R3 dormant prep)

---

## 4. Vibing #1 at 324k — what to do about it

F4's Bayesian priors:
| Hypothesis | Prior | Action |
|---|---|---|
| H1 — banned exploit | 15% | Don't chase |
| **H2 — clean execution of the 9-item stack above** | **35%** | Our target |
| H3 — manual-round win | 25% | Unknown |
| H4 — second-order PEPPER edge we haven't identified | 25% | 3h forensic path analysis |

**Recommended: replicate H2 fully first. If after 21h we're still >15% below top-10, spend 3h on H4 PEPPER forensic.**

---

## 5. Critical caveats

- **4-run samples are too small for statistical significance** on variant ranking. v5 > Promoted is 2σ noise per F1.
- **OBI bucket means are contaminated by sample-wide negative drift** (~-16/10-snap).
- **F7 calibration issue still exists:** our local backtest reversed the true simulator ranking. DO NOT tune from local backtest without first calibrating `passive_allocation`.
- **We cannot validate any fix autonomously** — only IMC test-upload validates. Plan: implement wall-mid fix, submit to IMC simulator, measure.

---

## 6. The one-line version

**Change `fair_value_method="weighted_mid"` → `"filtered_wall_mid"` for ASH_COATED_OSMIUM in `src/scripts/round_2/_runtime.py`. Submit. Measure.**

If that alone closes 50%+ of the gap on IMC simulator, we have the mechanical cause. If not, iterate through #2-8 in order.

---

## 7. Discussion queue before implementing

1. **Are we confident in F2's "top teams don't use OBI on stable products" finding?** Counter-argument: maybe their P3 code was different from what would work in P4. But 4 agents independently converged, including F2's line-level code evidence. **Confidence: high.**

2. **Is #1 (wall-mid fair value) really a one-hour change?** Need to verify:
   - Our `FilteredWallMidEstimator` produces what top teams call "wall-mid" or "max-amt-mid"
   - Changing the config actually flows through the AshLadderStrategy quote placement
   - There's no downstream dependence on weighted_mid's specific numeric properties
   **Flag for inspection before shipping.**

3. **Should we ship #1 alone for the next upload, or bundle 1+2+3?**
   - Ship #1 alone: clean A/B, cheap to revert, but only closes part of gap.
   - Bundle 1+2+3: bigger swing, harder to diagnose if fails.
   - Recommended: **#1 alone for round 3 opening days; #1+2 if early results look right.**

4. **What's the R2-sample validation plan?**
   - Local backtest alone is not sufficient (F7 calibration)
   - IMC simulator test-upload is the true gauge
   - R3 is the next opportunity — but first we'd like to prove the fix on R2 data
   - Can we re-submit to R2 simulator for verification, or is that window closed?

---

*Next action: inspect the ASH strategy code, apply the minimal wall-mid change, run local backtest as a sanity check (not a truth), commit, and present results for discussion before IMC upload.*

# Engine Design Catalog — P4 R3/R4/R5 Adoption Plan

**Compiled:** 2026-04-22.
**Context change:** Scores reset from R3 this year. Three-round fresh tournament. No R1/R2 ratchet protection. Full-aggression prep warranted.

This document **does not repeat** the individual engine blueprints — it is the rank-ordered adoption plan that ties them together, bridges them with the hidden-alpha pick list, and tells you exactly what to build in what order.

---

## Four engine blueprints + one alpha atlas

| Doc | Scope | Key design choice |
|---|---|---|
| [engine_etf_basket.md](engine_etf_basket.md) | ETF/basket stat-arb (R3 most likely) | Welford online mean + `hedge_factor=0.5` + dual gate + close-at-zero + residual MM |
| [engine_options.md](engine_options.md) | Options vol MM (R3 or R4) | Residual-IV MM per strike + hybrid smile (quadratic prior → rolling mid-IV) + WW-gated aggregate hedge + jump kill-switch |
| [engine_statarb_signal.md](engine_statarb_signal.md) | Cross-exchange arb (R4) + counterparty signal (R3→R5) | Signed break-even + Thompson-bandit fill probe + conv-cap stockpile + percentile regime + K-means on 5 rolling features for informed-bot detection |
| [hidden_alpha_analysis.md](hidden_alpha_analysis.md) | 27 ranked alphas, tiered pick list | "Self-reported-miss" category is most reliable alpha source (public writeups don't crowd-arbitrage) |

Strategic overview: [P4_R3-5_STRATEGIC_BRIEF.md](P4_R3-5_STRATEGIC_BRIEF.md) (read first).

---

## The adoption plan — ~56 hours total prep

Time budget is for a 2-3 person team parallelizing. Each line item maps to a specific deliverable in the engine docs.

### Tier 0 — Foundation (must-have before R3 opens, ~12h)

These are generic infra. Every engine below depends on them.

| # | Deliverable | Hours | Source |
|---|---|---|---|
| 0.1 | `take → clear → make` execution scaffold abstracted from existing code | 3 | Existing codebase + research_prior_editions §5 |
| 0.2 | `collections.deque(maxlen=N)` rolling indicators (mean, std, EMA, Welford) | 2 | Frankfurt / TimoDiehm pattern |
| 0.3 | Inline `norm_cdf` (Abramowitz-Stegun) — verified vs scipy locally | 1 | engine_options.md §2 |
| 0.4 | Kill-switch: `|r_t| / EWMA(|r|, 500) > 4.0` halt + drawdown halt | 2 | engine_options.md §3 |
| 0.5 | `traderData` size budget (hard cap, fail-fast, compact JSON, **ban `jsonpickle`**) | 2 | CarterT27 trap + chrispyroberts 100MB wipe |
| 0.6 | Symbol constant module with fail-fast on missing | 1 | creative §4.6 |
| 0.7 | Submission-bundle pre-commit hook (tests + config diff + human `y`) | 1 | creative §4.5 |

**Gate: all Tier-0 tested + passing on existing P4 R1/R2 replay data before moving on.**

### Tier S — Asymmetric one-hour retrofits (4 × 1-4h = ~8h)

Each of these is low effort and high persistence. Do these before building any new engine.

| # | Alpha | Hours | What to do |
|---|---|---|---|
| S.1 | **A6+A7 Probe-trick extensions** | 5 | Symmetric ask-probe + size-sensitivity probe + hidden-lift-price probe. Run as tick-0 of every new-product round. |
| S.2 | **A25 Asymmetric hysteresis** | 1 | Retrofit spread traders: enter `|z|>2`, exit `|z|<0.3`. Not symmetric. |
| S.3 | **A27 Cap-reservation re-audit** | 1 | Audit every `self.pos_cap = X` in codebase. Each cap needs a live justification. If downstream reason (e.g., hedge capacity) goes dormant, raise the cap. |
| S.4 | **A3 No-hedge options default** | 4 | Whalley-Wilmott band calculator. Hedge only when aggregate `|Δ| > band`. Default = off. |

### Tier A — Primary engines (~30h)

The three main engines. Build them in this order — basket is simplest, then options, then signal.

#### A.1 — `BasketArbEngine` (~10h, ref [engine_etf_basket.md](engine_etf_basket.md))

**One-line description.** Pre-strategy cross-product stage that runs before per-product MM loop; shares existing `RiskManager` for final clipping.

**Critical design picks (decided for you):**
1. Welford online mean (not fixed window) → constant memory, no edge bleed on cold start.
2. `hedge_factor = 0.5` on constituents → captures carry on mean premium without full spread-cost leak.
3. **Dual gate**: `|raw_spread| > abs_thr AND |z| > z_thr`. Nobody in public top-team code does this — belt-and-suspenders vs cold-start σ=0 and regime shifts.
4. Close-at-zero exit (Frankfurt + Linear Utility), not linear scale-out.
5. **Residual-position market-making** on the arb book (8% of cap reserved). Free ~5k/day per transcript-1.

**Files to create:**
```
src/engines/basket/
├── __init__.py
├── engine.py              # BasketArbEngine orchestrator
├── spread.py              # signed spread + Welford stats
├── sizing.py              # hysteresis + asymmetric entry/exit
├── hedge.py               # hedge_factor=0.5 policy
└── residual_mm.py         # 8% cap MM overlay
```

**Tests:** 15 pytest cases per blueprint (cold-start, regime break, limit saturation, constituent unavailability, residual-MM inventory clearing).

**P4 config template** (derived by triangulation across 6 top teams):
```python
P4R3_BASKET_CONFIG = {
    "abs_thr": 70,           # Frankfurt used 80; chrispyroberts 60
    "z_thr": 2.0,            # Linear Utility + arbitragelab
    "z_exit": 0.3,           # Linear Utility
    "kill_z": 4.0,           # regime break detector
    "hedge_factor": 0.5,     # Frankfurt
    "residual_mm_cap_pct": 0.08,
    "welford_warmup": 200,   # ticks
}
```

#### A.2 — `OptionsEngine` (~14h, ref [engine_options.md](engine_options.md))

**One-line description.** Residual-IV market-maker per strike with degrading smile fit and Whalley-Wilmott-gated aggregate-book delta hedge.

**Critical design picks (decided for you):**
1. **Hybrid smile**: quadratic prior for warmup (<50 obs/strike), rolling mean±std after. Gate is obs count, not P&L. Avoids chrispyroberts's quadratic-only failure mode on submission day.
2. **Aggregate-book delta**, never per-strike. 3-5× hedge volume reduction vs per-strike hedging.
3. **Whalley-Wilmott band** formula plugs in σ, Γ·S², T, half-spread. For 7-day/1-wide expect hedging OFF most ticks. Aggregate book only.
4. **ATM IV scalping** — enabled by default at ATM strike only, gated on low vol-of-vol. The neg 1-lag autocorr is microstructure (bot re-anchoring to slow fair), not bot-specific; should persist to P4.
5. **Disciplined short-straddle overlay** (<10% of book, IV>RV triggered, kill on jump detect).

**Files to create:**
```
src/options/
├── __init__.py
├── bsm.py                 # BSM pricer with inline norm_cdf
├── iv_solver.py           # bisection [0.001, 1.0], chrispyroberts-style
├── smile.py               # hybrid quadratic→rolling mid-IV
├── hedge.py               # Whalley-Wilmott band
├── risk.py                # jump detector + drawdown halt
├── engine.py              # OptionsEngine orchestrator
└── state.py               # compact JSON traderData
```

**Plus single strategy adapter:** `src/strategies/options_book.py` wiring the engine into the existing `STRATEGY_REGISTRY`.

**Tests:** 6 test modules (BSM round-trip, IV solver bounds, smile warmup→rolling transition, WW band edge cases, engine kill-switch activation, P3 R3 replay ±2% P&L acceptance).

**Explicitly rejected (documented in engine_options.md §2):** Kalman IV, SVI, local vol, textbook gamma-scalp-with-hedge, multi-expiry surface (enable only if P4 adds multi-expiry). `jsonpickle` banned.

#### A.3 — `StatArbEngine` + `CounterpartyIntelligenceEngine` (~12h, ref [engine_statarb_signal.md](engine_statarb_signal.md))

**Two engines — keep them separate.**

**`StatArbEngine`** — for any cross-exchange product (R4 candidate: macarons-family):
- Signed break-even calculator (handles negative tariffs / subsidies symbolically)
- **Thompson-bandit fill-rate probe** to auto-calibrate hidden-taker price (generalizes chrispyroberts's `int(externalBid + 0.5)` to any product)
- **Geometric-buffer stockpile optimizer** — rederives the ~30-unit target that both top-2 P3 teams missed. Param `batch_size = k * conv_cap`, sweep k∈{1,2,3,5} empirically against storage cost.
- Percentile-regime detector (25/75 pct of 100-window), NOT linear regression on external signal
- Arb P&L stream and signal P&L stream kept separate; blend only at risk budget

**`CounterpartyIntelligenceEngine`** — runs from R3 tick 0 across ALL products:
- Per-counterparty rolling 5-feature state: `(cum_P&L, trade_count, win_rate, inventory_cycle_amplitude, entry_percentile_distribution)`
- Synthetic-ID tracking when pre-R5 (anonymized counterparty hashes by behavior fingerprint)
- K-means on features → 3 clusters: informed / MM / noise
- Kyle's lambda per counterparty via pure-python OLS (permanent vs transient impact decomposition)
- Signal API: `is_informed_trading(product, side) → confidence`
- Piggyback sizing: Kelly-adapted, capped at X% of book, with **collision-skip rule** (if another strategy already using the slot, stand aside)

**Files to create:**
```
src/engines/statarb/
├── __init__.py
├── engine.py              # StatArbEngine
├── breakeven.py           # signed tariff-aware BE
├── fill_probe.py          # Thompson bandit
├── stockpile.py           # conv-cap-aware batching
└── regime.py              # percentile-flag detector

src/engines/signal/
├── __init__.py
├── engine.py              # CounterpartyIntelligenceEngine
├── features.py            # per-counterparty rolling state
├── clustering.py          # K-means over 5-D feature vector
├── kyle_lambda.py         # permanent-vs-transient OLS
└── piggyback.py           # Kelly-adapted sizing + collision rule
```

**Critical difference vs public P3 top-team code:**
- chrispyroberts + CarterT27 both used naive string-match `trade.buyer == "Olivia"` — works only after R5 reveals IDs.
- Our `CounterpartyIntelligenceEngine` runs **synthetic-ID tracking by behavior fingerprint from R3 tick 0** — so we identify the informed bot 2 rounds earlier.

### Tier B — Dormant / late-activating (~16h)

Build in background during R3/R4; most activate in R4 or R5.

| # | Alpha | Hours | Trigger |
|---|---|---|---|
| B.1 | **A1 live counterparty signal** (Tier A A.3 output) | — | Active from R3 tick 0 |
| B.2 | **A2 conversion stockpile** (Tier A A.3 output) | — | Activates when R4 cross-exchange product appears |
| B.3 | **A10 end-of-round flattening fade** | 3 | Observe field in last 10k of R3, deploy in R4 |
| B.4 | **A15 cross-edition regression + DP** | 10 | Dormant infra; fires on R5 open |
| B.5 | **A13 put-call parity checker** | 3 | Dormant; activates only if puts appear |

**A15 is the highest ceiling single bet.** Linear Utility generated 2.1M shells in P2-R5 with this exact pattern. Cost is low (10h), payoff is asymmetric. Build it during R3 prep, leave dormant, fire on R5 open.

---

## Critical convergences from top-team code

Patterns seen in 4+ of the 7 top-team repos (the non-contested truth):

1. **`take → clear → make`** execution loop (every top team)
2. **Inline `norm_cdf`** (Abramowitz-Stegun) — scipy blocked
3. **Static integer basket weights** — never learned
4. **Wall-mid pricing** for quoting, not simple midpoint
5. **Bisection IV solver** with `[0.001, 1.0]` bounds — Newton-Raphson (CarterT27) works but is brittle
6. **Compact JSON `traderData`** — `jsonpickle` is a trap (CarterT27)
7. **`collections.deque(maxlen=N)`** for all rolling windows
8. **Position-limit awareness per tick**, with conversion limit tracked separately

---

## Critical divergences — where top teams disagreed and we picked

| Question | Option A | Option B | **Our choice** | Reason |
|---|---|---|---|---|
| Rolling window | Fixed-length (45-100 ticks) | Welford online | **Welford** | No edge bleed on cold start, constant memory |
| Basket hedge | 0 (jmerle: lost 36k) | 1.0 full | **0.5 (Frankfurt)** | Captures carry on mean premium without full spread-cost leak |
| Entry gate | Absolute threshold only | Z-score only | **Dual: abs AND z** | Belt-and-suspenders vs cold-start σ=0 |
| Spread exit | Linear scale-out | Close-at-zero | **Close-at-zero** | Linear leaves 15-25% of reversion PnL |
| IV smile | Quadratic fit every tick | Rolling mid-IV window | **Hybrid: quadratic warmup → rolling** | Quadratic broke mid-round for chrispyroberts; rolling needs warmup |
| Delta hedge | Per-tick | Never | **WW band, aggregate** | Spread cost > gamma P&L in 1-wide books, but catastrophic jumps need some protection |
| Olivia detection | String match `== "Olivia"` (R5 only) | Behavior-fingerprint clustering | **Clustering from R3 tick 0** | 2-round head start |
| Signal blending | Blend at decision layer | Separate P&L streams | **Separate streams, blend at risk budget** | Prevents weak signal from corrupting strong arb |
| Conv batching | 1× cap per tick (reactive) | k× cap stockpile | **3× cap stockpile** | Doubles P&L on cross-exchange products |

---

## The meta-strategy: where we differentiate from top teams

Consolidated from hidden_alpha_analysis.md closing meta-rule.

**Our differentiation budget:**
- **60% to Tier S+A foundations** (the engines above) — must match or exceed top-team baseline
- **30% to live-adaptive alphas** (A1 counterparty clustering, A7 hidden-lift probe, A10 flattening fade, A15 cross-edition regression) — where we go beyond what was in P3 code
- **10% to dormant checkers** (A13 put-call parity, A27 cap audit) — cheap insurance

**Top teams will already have:** basket z-score trader, options IV mean-reverter, cross-exchange arb with fill probe, Olivia string-match in R5.

**Top teams likely won't have:**
1. Counterparty clustering running from R3 tick 0 (not R5)
2. Conversion stockpile with 3× cap batching
3. Aggregate-book delta hedge with WW band (not per-strike, not per-tick)
4. Residual-position MM on the arb book (~5k/day free)
5. Cap-reservation re-audit (every self-imposed cap needs a live justification)
6. Probe-trick applied to every new product (fair-formula + hidden-lift + size-sensitivity)
7. Asymmetric hysteresis (enter 2.0, exit 0.3) on EVERY spread trader
8. Kyle's lambda per counterparty (permanent vs transient impact)

**Where a P3 top-team writeup says "we should have done X" — assume the P4 field ALSO misses it.** Public writeups don't crowd-arbitrage. Alphas A1, A2, A3, A4, A5, A27 are in this category. Cumulatively 500k–1M of R4+R5 P&L sitting in plain sight.

---

## Build order — concrete week-1 plan

Assuming R3 opens in 7 days from now. Parallel team of 2-3 people.

**Day 1-2 (Foundations):**
- Tier 0 items 0.1 through 0.7 (all ~12h)
- Tier S: S.1 probe-trick extensions (5h), S.2 asymmetric hysteresis retrofit (1h), S.3 cap-audit pass (1h)

**Day 3-4 (Primary engine 1):**
- Tier A.1 `BasketArbEngine` (10h) with 15 pytest cases
- Regression test against existing P3 replay data

**Day 5-6 (Primary engine 2):**
- Tier A.2 `OptionsEngine` (14h) with 6 test modules
- P3 R3 replay integration test: must match ±2% of chrispyroberts published P&L

**Day 7 (Primary engine 3, start):**
- Tier A.3 `StatArbEngine` + `CounterpartyIntelligenceEngine` scaffolding (start — complete during R3 run)
- S.4 no-hedge default (4h) integrated into OptionsEngine

**During R3 (live):**
- Counterparty clustering running from tick 0
- Observe flattening behavior for Tier B.3
- Begin Tier B.4 cross-edition DP solver in background

**Before R4 opens:**
- A.3 engines complete
- B.2 stockpile ready
- B.3 flattening fade deployed

**Before R5 opens:**
- B.4 cross-edition regression harness + DP solver ready
- All counterparty clusters stable; identify Olivia-analog candidates
- B.5 put-call parity checker dormant

---

## Acceptance criteria per engine

Before claiming an engine is "done":

**BasketArbEngine:**
- [ ] Passes 15 pytest cases
- [ ] Reproduces chrispyroberts P3 R2 basket P&L within 10%
- [ ] Handles all 3 regimes: cold start, limit saturation, regime break
- [ ] Residual-MM layer reproduces ~5k/day on P3 data

**OptionsEngine:**
- [ ] Passes 6 test modules
- [ ] BSM round-trip accurate to 1e-6
- [ ] Hybrid smile degrades gracefully when obs<50
- [ ] WW band never fires when `gamma_pnl < spread_cost`
- [ ] Reproduces chrispyroberts P3 R3 P&L within 2% on replay

**StatArbEngine:**
- [ ] Signed break-even handles negative tariffs
- [ ] Fill-probe converges to chrispyroberts `int(externalBid + 0.5)` on P3 macaron replay
- [ ] Stockpile `k=3` config reproduces transcript-1 "doubles P&L" claim on replay

**CounterpartyIntelligenceEngine:**
- [ ] Identifies Olivia on P3 R1-R2 data without using IDs (synthetic hash only)
- [ ] Kyle's lambda matches published regression on any test counterparty
- [ ] Piggyback sizing respects collision-skip rule

---

## What we are explicitly NOT building

From hidden_alpha_analysis.md §5, so the team doesn't re-litigate:

- **Gamma scalping.** Math says net-negative in 1-wide spreads; transcript-1 confirms "100× less than #2."
- **Sunlight linear regression.** 99% R² = leakage. Regime-flag, never regress.
- **Variance swaps / AMMs / perpetuals.** Low probability P4 introduces these.
- **Cheap-talk / Bayesian signaling manual.** 3/10 confidence.
- **Complex ML models.** Top-team consensus: "you don't need crazy ML."
- **SVI / local-vol surface fitting.** Overkill for 5-strike chain; quadratic + rolling mid-IV dominates.
- **Kalman for primary hedge-ratio estimation.** Use it as drift monitor only; static OLS for primary.
- **Full delta-hedging in any tight-spread book.** Default-off.

---

## Reference map

Everything above traces to one of:

- [P4_R3-5_STRATEGIC_BRIEF.md](P4_R3-5_STRATEGIC_BRIEF.md) — the strategic playbook (written first)
- [engine_etf_basket.md](engine_etf_basket.md) — basket engine blueprint (6 repos dissected, ~930 lines spec)
- [engine_options.md](engine_options.md) — options engine blueprint (opinionated single architecture)
- [engine_statarb_signal.md](engine_statarb_signal.md) — stat-arb + counterparty intelligence dual engine
- [hidden_alpha_analysis.md](hidden_alpha_analysis.md) — 27 ranked alphas, Tier S/A/B pick list
- [research_prior_editions.md](research_prior_editions.md) — 7 top-team repos cross-referenced
- [research_academic_quant.md](research_academic_quant.md) — Sinclair, SVI, WW, Kelly under rank scoring
- [transcript_1_extracted.md](transcript_1_extracted.md) — P3 8th-place post-mortem
- [../../CLAUDE.md](../../CLAUDE.md) — our own P4-R2 manual-round lessons (M1-M4, F1-F5, P1-P3, W1-W2)

---

*Adoption budget: ~56 hours of engineering. Expected ceiling with full adoption: top-20 global on a three-round fresh tournament. The differentiation is not "we built engines" — top teams do that too. The differentiation is the 30% of our budget that goes to R3-tick-0 counterparty clustering, 3× stockpile batching, aggregate-book WW hedging, probe-trick generalization, and asymmetric hysteresis — the alphas that public P3 top-team writeups consistently report having missed.*

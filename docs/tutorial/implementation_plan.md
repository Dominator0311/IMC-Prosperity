# IMC Prosperity Implementation Plan v2

## Purpose

Build a **production-ready Prosperity trading system** and a **fast offline research/test harness** that together maximize the probability of strong performance across the full competition.

This plan is designed for collaborative execution with AI coding agents such as Codex / Claude Code. It is intentionally modular, reviewable, and robust against overfitting, implementation mistakes, and future round changes.

---

# 1. Strategic objective

We are building two connected systems:

## A. Live trading bot
The code that runs inside IMC Prosperity.

It must:
- parse `TradingState`
- estimate fair value per product
- decide when to take or make liquidity
- manage inventory and position limits
- persist minimal state via `traderData`
- return legal, fast, safe orders

## B. Offline research / testing harness
The local experimentation environment.

It must:
- replay tutorial and future round data
- compare strategy variants
- test fair-value models
- evaluate maker/taker behavior
- track PnL, positions, markouts, and fill quality
- produce parameter sweeps and visual diagnostics

## Why this is the correct approach
Strong Prosperity performance does **not** come from one clever idea. It comes from:
- reliable fair value
- disciplined execution
- strong position control
- fast feedback
- repeated inspection and iteration

The architecture is therefore not “plumbing for its own sake.” It is the minimum system required to search for real edge without fooling ourselves.

---

# 2. Hard constraints that must shape the design

## 2.1 Stateless execution
Assume globals / class variables are unreliable across calls.
Persistent state must be stored in `traderData`.

## 2.2 Orders are short-lived
Unfilled orders are effectively iteration-scoped.
Market making therefore means **re-quoting repeatedly**, not resting passively for long periods.

## 2.3 Hard position limits
If total buy/sell intent breaches limits, the exchange may reject the orders.
Position capacity must be treated as a scarce resource.

## 2.4 Tight runtime budget
The live bot must be lightweight.
Heavy optimization, ML, or large data structures belong **offline**, not in `run()`.

## 2.5 Limited libraries and environment
Keep production code simple and deterministic.

## 2.6 Local backtest is not the truth
Local replay is for speed and diagnosis.
Official-site behavior must be treated as the final authority when bot behavior or matching assumptions matter.

---

# 3. What the tutorial data already tells us

## EMERALDS
EMERALDS behaves like a **stable-anchor product**.

Working hypothesis:
- fair value is effectively fixed around `10000`
- spread is stable
- ideal for testing market making, fair-value taking, inventory skew, and flattening

## TOMATOES
TOMATOES behaves like a **dynamic-fair-value product**.

Working hypothesis:
- constant fair value is wrong
- short-memory predictive structure exists
- ideal for testing rolling fair-value models and adaptive execution

## Strategic implication
The tutorial already gives us two product archetypes:
1. fixed-fair market making
2. dynamic-fair adaptive trading

That is enough to begin implementation immediately.

---

# 4. Core philosophy for this build

## 4.1 Build edge-enabling architecture first, then optimize hard
We are not postponing performance.
We are building the minimum machinery needed to maximize performance correctly.

## 4.2 Simple beats fancy
If two strategies have similar economics, prefer the one with:
- fewer parameters
- cleaner interpretation
- lower runtime cost
- easier diagnostics

## 4.3 Every important change must be explainable
If an agent proposes a change, it must come with:
- clear intuition
- expected effect
- test plan
- review path

## 4.4 Visualization and step-through review are first-class
Aggregate PnL is not enough.
We must inspect actual timestamps, order books, positions, and missed trades.

## 4.5 Capacity is alpha
Reducing position at fair value or near fair value can be good business if it frees room for future better trades.

---

# 5. Major upgrades integrated into v2

These are the highest-value changes integrated from winner-analysis lessons.

## 5.1 Dedicated Fair Value & PnL Marking Inference phase
For each product, explicitly test what fair-value proxy best explains:
- realized markouts
- observed PnL behavior
- decision quality

Candidate fair values:
- constant anchor
- top-of-book mid
- deeper-book mid / wall-mid
- rolling mid
- weighted recent mid
- microprice

## 5.2 Mandatory Backtest Review Protocol
Every meaningful strategy change must be reviewed in two ways:
1. aggregate metrics
2. step-through visual inspection on selected timestamps

## 5.3 Explicit Capacity Recovery / Position Reduction logic
Inventory reduction at fair or near fair is a deliberate strategy component.
Not just risk cleanup.

## 5.4 Generic SignalScanner / FlowAnalyzer module
Instead of hardcoding past informed-trader patterns, build a generic framework that can later detect:
- repeated trade sizes
- trades near extrema
- persistent directional flow
- unusual trade clusters

## 5.5 Manual Challenge workstream
Manual rounds are important enough to justify a parallel system.
A separate plan is provided.

## 5.6 AI Agent Operating Protocol
Agents may accelerate code and experiments, but no major strategy change is accepted without human-readable explanation and replay review.

---

# 6. Project structure

```text
prosperity/
  README.md
  requirements.txt

  data/
    raw/
      prices_round_0_day_-1.csv
      prices_round_0_day_-2.csv
      trades_round_0_day_-1.csv
      trades_round_0_day_-2.csv
    processed/

  notebooks/
    01_tutorial_eda.ipynb
    02_fair_value_inference.ipynb
    03_backtest_diagnostics.ipynb
    04_parameter_review.ipynb
    05_signal_scan.ipynb

  src/
    trader.py
    datamodel.py

    core/
      config.py
      state_store.py
      market_data.py
      fair_value.py
      risk.py
      execution.py
      logger.py
      review_protocol.py
      utils.py

    strategies/
      base_strategy.py
      emeralds.py
      tomatoes.py

    signals/
      flow_analyzer.py
      extrema_detector.py
      trade_size_scanner.py

    backtest/
      replay_engine.py
      fill_model.py
      metrics.py
      reporting.py
      parameter_sweep.py

    scripts/
      run_backtest.py
      run_parameter_sweep.py
      run_review_pack.py
      export_submission.py
      validate_submission.py

  outputs/
    logs/
    charts/
    backtests/
    sweeps/
    review_packs/

  tests/
    test_state_store.py
    test_market_data.py
    test_risk.py
    test_execution.py
    test_emeralds.py
    test_tomatoes.py
```

---

# 7. System design

## 7.1 `src/trader.py`
Thin orchestration layer.

Responsibilities:
1. load state from `traderData`
2. normalize market data
3. dispatch each product to its strategy
4. combine orders
5. clip via risk manager
6. save new state
7. return `(orders, conversions, traderData)`

### Rule
No product-specific logic should live directly in `trader.py`.

---

## 7.2 `core/state_store.py`
Minimal persistence layer.

Must support:
- safe load on empty / malformed input
- compact save
- versioned schema

Persist only:
- recent mids per product
- recent spreads per product
- limited rolling stats
- optional simple counters

Do **not** persist:
- full raw history
- verbose logs
- redundant book snapshots

---

## 7.3 `core/market_data.py`
Normalize order books and provide reusable helpers.

Required helpers:
- best bid
- best ask
- spread
- mid
- top N levels
- book imbalance
- microprice (if computable)
- deeper-book fair-value helpers later

Goal:
All downstream strategy code should consume normalized snapshots, not raw dictionaries.

---

## 7.4 `core/fair_value.py`
Centralized fair-value engine.

Support at least:
- constant value
- rolling mid
- weighted recent mid
- microprice
- optional wall-mid / deeper-book estimator
- fallback logic

Design requirement:
All strategies must use a fair-value interface, not embed ad hoc pricing logic everywhere.

---

## 7.5 `core/risk.py`
Inventory and position manager.

Required functionality:
- current position lookup
- remaining buy/sell capacity
- legal order clipping
- quote size reduction near limits
- inventory skew calculation
- position reduction / capacity recovery rule

This module must treat inventory relief as part of strategy, not just safety.

---

## 7.6 `core/execution.py`
Translate fair value and intent into orders.

Three submodes:
1. **Taker mode** — cross favorable orders
2. **Maker mode** — quote around fair value
3. **Capacity recovery mode** — reduce inventory deliberately when near limits or when freeing capacity is valuable

Execution decisions must be easy to inspect and log.

---

## 7.7 `core/logger.py`
Compact structured diagnostics.

Each event should be parsable offline and include:
- timestamp
- product
- fair value
- top-of-book
- chosen actions
- position
- strategy mode

Must support truncation and verbosity control.

---

## 7.8 `signals/flow_analyzer.py`
Generic pattern detection framework for later rounds.

Initial capabilities:
- repeated trade-size counts
- trades near local highs/lows
- simple directional-flow persistence
- flagged suspicious patterns for review

This is **not** tutorial phase priority 1, but it should exist as a framework extension point.

---

## 7.9 `strategies/base_strategy.py`
Common interface for product modules.

Suggested methods:
- `estimate_fair(...)`
- `generate_taker_orders(...)`
- `generate_maker_orders(...)`
- `generate_capacity_recovery_orders(...)`
- `run(...)`

---

## 7.10 `strategies/emeralds.py`
Fixed-fair-value product strategy.

Initial assumptions:
- fair value `10000`
- stable spread
- maker/taker opportunities around anchor

Initial logic:
1. take clear mispricing
2. quote around fair value
3. skew for inventory
4. reduce position when capacity matters

---

## 7.11 `strategies/tomatoes.py`
Dynamic-fair-value product strategy.

Initial assumptions:
- short-memory predictive structure
- rolling or weighted fair-value estimate better than constant

Initial logic:
1. estimate fair value adaptively
2. take visible mispricing
3. quote around fair with more caution than EMERALDS
4. use stronger inventory discipline

---

# 8. Offline research and testing harness

## 8.1 `backtest/replay_engine.py`
Replay tutorial and future round data step by step.

Goal:
Run the same strategy logic offline for fast iteration.

Important note:
This is a **decision-quality harness**, not a claim of perfect simulation fidelity.

---

## 8.2 `backtest/fill_model.py`
Start simple.

Initial rules:
- marketable taker orders fill against visible book
- passive fill assumptions conservative or disabled initially
- maker fills treated carefully to avoid fantasy PnL

Later, if needed:
- add passive fill heuristics
- add trade-triggered fill assumptions

---

## 8.3 `backtest/metrics.py`
Must compute at least:
- total PnL
- PnL by product
- trade counts
- maker vs taker counts
- average entry edge
- inventory usage
- time near limits
- markout at +1 / +5 / +20 steps

---

## 8.4 `backtest/reporting.py`
Generate visual review artifacts.

Required charts:
- price vs fair value
- PnL over time
- position over time
- trade markers
- maker/taker decomposition
- markout histograms
- parameter comparison plots

---

## 8.5 `core/review_protocol.py`
Formalize the inspection process.

Every important experiment should generate a **review pack** with:
- summary metrics
- key charts
- timestamps for suspicious / interesting behavior
- example step-through slices
- brief interpretation notes

This formalizes the winner-style workflow of repeatedly stepping through the backtest rather than trusting aggregate PnL.

---

# 9. AI Agent Operating Protocol

## 9.1 What agents are allowed to do
Agents may:
- write core modules
- generate helper functions
- build notebooks
- suggest strategy ideas
- run parameter sweeps
- propose diagnostics
- implement review scripts

## 9.2 What agents are not allowed to do unchecked
No major strategy change should be accepted merely because:
- it compiles
- it improves one backtest metric
- it looks sophisticated

## 9.3 Acceptance gate for any meaningful strategy change
Every major change must include:
1. a plain-English explanation of the idea
2. expected economic intuition
3. replay evidence
4. review-pack output
5. note on possible failure modes

## 9.4 Human role
Human review must focus on:
- whether the logic makes sense economically
- whether the change is robust
- whether the code remains understandable
- whether it fits Prosperity constraints

---

# 10. Implementation phases

## Phase 0 — Scope freeze and setup

### Tasks
- create repo structure
- load tutorial files cleanly
- document assumptions for EMERALDS and TOMATOES
- freeze non-goals for this phase

### Non-goals for initial phase
- options module
- conversion module
- basket arbitrage module
- trader-ID-specific logic
- heavy ML

### Done when
- project skeleton exists
- data parses cleanly
- scope is documented

---

## Phase 1 — Production shell

### Tasks
- implement `trader.py`
- implement `state_store.py`
- implement `market_data.py`
- implement `risk.py`
- implement config plumbing

### Why
Removes the highest-probability operational failures first.

### Done when
- no-op trader runs end to end
- state round-trips safely
- risk manager clips correctly

---

## Phase 2 — EMERALDS end-to-end baseline

### Tasks
- implement constant fair value strategy
- taker rules
- maker rules
- capacity recovery logic
- connect to replay engine
- generate first review pack

### Why
EMERALDS is the cleanest environment for proving the architecture.

### Done when
- EMERALDS strategy runs live and offline
- outputs sane trades
- review pack exists

---

## Phase 3 — Fair Value & PnL Marking Inference

### Tasks
For EMERALDS and TOMATOES, test which fair-value proxies best explain behavior:
- constant anchor
- mid
- weighted recent mid
- microprice
- deeper-book estimate where relevant

### Outputs
- notebook comparing proxies
- metrics table
- interpretation note on what to use in live strategy

### Why
Fair-value choice is the main driver of decision quality.

### Done when
- chosen fair-value estimator per tutorial product is justified

---

## Phase 4 — Replay diagnostics and review discipline

### Tasks
- finish metrics
- finish reporting
- step-through review tool or notebook
- build review-pack generator

### Why
This is where architecture turns into an edge-search engine.

### Done when
- every strategy run can be reviewed visually and timestamp by timestamp

---

## Phase 5 — TOMATOES end-to-end baseline

### Tasks
- implement dynamic fair-value module
- compare several simple estimators
- reuse EMERALDS execution skeleton
- build review pack

### Why
Validates that framework supports drifting products, not just fixed anchors.

### Done when
- TOMATOES runs end to end
- dynamic fair-value choices are comparable and reviewable

---

## Phase 6 — Parameter sweeps and robustness testing

### EMERALDS sweep
- quote width
- taker threshold
- skew strength
- flatten threshold

### TOMATOES sweep
- fair-value estimator
- lookback length
- quote width
- taker threshold
- skew strength

### Rule
Prefer **stable parameter regions**, not the single highest backtest peak.

### Done when
- recommended baseline config exists for both products
- robustness notes are documented

---

## Phase 7 — SignalScanner foundation

### Tasks
- repeated trade-size scan
- local extrema trade detection
- simple directional-flow scoring
- logging hooks for suspicious patterns

### Why
This prepares us for future rounds where predictable informed flow may matter.

### Done when
- generic signal framework exists, even if not fully used in tutorial strategies

---

## Phase 8 — Residual Capacity Utilizer (optional enhancement)

### Tasks
- detect unused position budget after main strategy allocation
- optionally use it for small spread-capture or residual local strategy

### Why
Winner-analysis suggests that leftover capacity can sometimes still produce extra PnL.

### Done when
- module exists behind a config flag
- only enabled if evidence supports it

---

## Phase 9 — Hardened submission workflow

### Tasks
- validate imports
- validate runtime assumptions
- validate return signature
- ensure `traderData` stays compact
- allow logging reduction for production
- export final submission safely

### Done when
- pre-submit validation passes
- final export script works reliably

---

## Phase 10 — Documentation and round-readiness

### Tasks
- architecture README
- “how to add a new product” guide
- review protocol doc
- tuning notes
- future-round checklist

### Done when
- new product onboarding is easy
- handoff to humans or agents is straightforward

---

# 11. Core experiments to run

## Experiment A — EMERALDS fair-value sanity
Test whether constant fair `10000` is sufficient and whether any alternative meaningfully improves outcomes.

## Experiment B — EMERALDS quote-width sweep
Measure fill rate, markout, inventory drift, and PnL.

## Experiment C — TOMATOES fair-value bake-off
Compare rolling / weighted / light autoregressive estimators.

## Experiment D — inventory stress test
Compare weak vs strong skew and flattening intensity.

## Experiment E — maker vs taker decomposition
Test maker-heavy, taker-heavy, and balanced modes.

## Experiment F — fair-value marking inference
Test which proxy best explains realized outcome structure.

## Experiment G — suspicious flow scan
Run generic scanners on tutorial trades so the framework exists before live rounds.

---

# 12. Review protocol (mandatory)

For every important strategy revision:

## Step 1 — Metrics review
Check:
- PnL
- markouts
- inventory behavior
- maker/taker mix
- time near limits

## Step 2 — Visual review
Inspect:
- price vs fair value
- trade markers
- position behavior
- suspicious spikes or reversals

## Step 3 — Timestamp step-through
Review a sample of:
- best trades
- worst trades
- missed opportunities
- overfilled / overexposed periods

## Step 4 — Decision note
Record:
- keep
- modify
- discard

No strategy should advance without this review path.

---

# 13. Expected outputs by phase

## After Phase 1
- safe live shell
- state and risk working

## After Phase 2
- EMERALDS baseline bot
- first review pack

## After Phase 4
- replay harness + diagnostics complete enough for serious optimization

## After Phase 5
- TOMATOES baseline bot
- fair-value comparison evidence

## After Phase 6
- tuned baseline configs
- robustness notes

## After Phase 9
- production-safe exportable submission

---

# 14. What not to do too early

Do not prioritize these before the baseline and review loop are working:
- options pricing
- conversion arbitrage
- basket trading
- hardcoded informed-trader rules
- heavy ML
- complicated probabilistic execution models

These can matter later, but they are not the highest-ROI work now.

---

# 15. Success criteria for this stage

This stage is successful if we end up with:
- a reliable Prosperity bot architecture
- explicit fair-value inference process
- strong EMERALDS and TOMATOES baselines
- replay + diagnostics + review discipline
- parameter sweep capability
- a foundation ready for future round-specific alpha

The key outcome is **not** “a clever tutorial bot.”
It is a **complete edge-search platform** that is already trading two product archetypes correctly and can absorb future products quickly.

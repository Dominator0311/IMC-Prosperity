# IMC Prosperity Architecture Doctrine

## Purpose

This document defines the architectural doctrine for our IMC Prosperity codebase.

It exists to keep us aligned on first principles:

- build for correctness before cleverness
- build for reuse before round-specific hacks
- build for diagnosis before optimization
- build for fast iteration without sacrificing safety

The goal is not to create a tutorial bot.
The goal is to create a reusable Prosperity trading engine that can absorb new products, new mechanics, and new strategy modules with minimal rewrites.

---

## Core Thesis

Prosperity is best treated as:

- repeated short-horizon decision making
- under hard inventory constraints
- in a stateless runtime
- with changing round mechanics
- where research speed and interpretability are part of the edge

Therefore the system must be split into two distinct but connected parts:

1. a thin live trading engine
2. a rich offline research and replay environment

The live engine should be small, safe, deterministic, and inspectable.
The offline system should be flexible, analyzable, and experimentation-friendly.

---

## Design Principles

### 1. Thin live path

`Trader.run()` should orchestrate, not think deeply.

It should:

- load state
- normalize market data
- delegate to product/mechanic modules
- clip orders to legal limits
- emit compact diagnostics
- persist next state

It should not contain product-specific logic directly.

### 2. State minimalism

The runtime is effectively stateless apart from `traderData`.

Persist only what is required for next-step decisions:

- short rolling windows
- rolling moments
- simple counters
- product flags
- small detector state

Never persist:

- raw book history
- verbose logs
- large arrays that can be recomputed offline

### 3. Explicit fair value layer

All trading decisions should flow through a fair-value abstraction.

That abstraction may use:

- constant anchors
- top-of-book mid
- weighted mid
- rolling mid
- microprice
- wall-mid or deeper-book signals
- cross-product synthetic values
- theoretical values for options/conversions

Strategies should not hardcode pricing logic ad hoc inside execution rules.

### 4. Inventory is part of alpha

Risk management is not just a safety wrapper.

Position capacity is a scarce resource.
Flattening or reducing inventory at low edge can be profit-maximizing if it frees capacity for future high-edge trades.

### 5. Separate signal from execution

The system should distinguish between:

- what we believe is mispriced
- what position we want
- how we actually execute to get there

This keeps models composable and makes failures easier to inspect.

### 6. Make behavior explainable

If we cannot explain why an order was sent, we cannot trust the engine.

Every important action should be attributable to:

- fair value
- signal
- inventory state
- execution mode
- risk clipping

### 7. Conservative offline truth model

Backtests are decision-quality tools, not perfect exchange replicas.

They should help us:

- compare ideas
- inspect trade quality
- detect obvious bad behavior
- choose robust parameters

They should not seduce us into fake precision.

### 8. Stable systems beat sharp systems

We should prefer:

- broad parameter plateaus over peak settings
- simple models over brittle ones
- interpretable modules over opaque ones

---

## Architectural Layers

### Layer A: Live Trading Engine

Responsibilities:

- consume `TradingState`
- restore minimal persistent state
- compute normalized market features
- compute fair values
- generate signal intents
- translate intents into orders
- enforce position legality
- emit compact `traderData` and logs

Constraints:

- stateless runtime
- short-lived orders
- hard position limits
- bounded `traderData`
- bounded runtime

### Layer B: Offline Research Engine

Responsibilities:

- load tutorial and round data
- replay the market step by step
- run the same strategy code where possible
- compute diagnostics and markouts
- compare fair-value models
- inspect maker/taker performance
- perform parameter sweeps
- generate review artifacts

### Layer C: Analysis and Review Surface

Responsibilities:

- charts
- review packs
- timestamp drilldowns
- notes on keep/modify/discard decisions

This layer is not optional.
It is part of the edge-discovery engine.

---

## Canonical Data Flow

For each live iteration:

1. `state_store.load(state.traderData)`
2. `market_data.normalize(state)`
3. `fair_value_engine.compute(product, normalized_snapshot, local_state)`
4. `signal_engine.compute(product, fair_value, snapshot, state, local_state)`
5. `execution_engine.generate_orders(product, signal, fair_value, snapshot, position_state)`
6. `risk_manager.clip(product, current_position, pending_orders, limits)`
7. `logger.record(...)`
8. `state_store.save(next_state)`
9. return `(orders, conversions, traderData)`

This flow should stay stable even as products and rounds change.

---

## Module Boundaries

### `datamodel`

Purpose:

- local mirror of the Prosperity data structures
- strict compatibility with live submission expectations

Rule:

- do not add strategy logic here

### `core/state_store`

Purpose:

- versioned serialization and deserialization of persistent state

Must guarantee:

- safe load on empty input
- safe load on malformed input
- compact output
- schema versioning

### `core/market_data`

Purpose:

- normalize raw order books and trades into reusable features

Outputs should support:

- best bid / best ask
- spread
- mid
- top-N levels
- imbalance
- microprice
- optional wall detection
- recent trade summaries

Rule:

- downstream code should consume normalized snapshots, not raw dictionaries

### `core/fair_value`

Purpose:

- single interface for all fair-value estimators

Interface shape:

- `estimate(product, snapshot, local_state, config) -> FairValueEstimate`

The result should include both value and metadata, for example:

- price
- estimator name
- confidence or regime label
- fallback used

### `core/signals`

Purpose:

- turn market conditions into trade intents

Examples:

- take visible mispricing
- quote around fair value
- flatten inventory
- long basket / short synthetic
- buy undervalued option
- respond to detected informed flow

Rule:

- signals express intent, not final order syntax

### `core/execution`

Purpose:

- translate signals into concrete orders

Execution modes:

- taker
- maker
- inventory recovery
- conversion
- hedge

Rule:

- execution policy must be inspectable and parameterized

### `core/risk`

Purpose:

- hard legality and soft inventory shaping

Must support:

- current position lookup
- remaining buy capacity
- remaining sell capacity
- per-product clipping
- quote size reduction near limits
- flattening thresholds
- optional cross-product exposure views later

Rule:

- risk manager owns legal clipping
- strategy modules must never assume their orders are final

### `core/logger`

Purpose:

- compact structured diagnostics

Every event should be parseable and include enough context to reconstruct why the decision happened.

### `strategies`

Purpose:

- product- or mechanic-specific behavior modules

Examples:

- stable-anchor market making
- dynamic-fair-value quoting
- basket residual mean reversion
- options mispricing
- conversion arbitrage
- flow-based directional modules

Rule:

- strategies consume core services
- strategies do not reinvent market data, risk, or persistence

### `backtest`

Purpose:

- replay engine
- fill model
- metrics
- reporting
- parameter sweeps

Rule:

- use the same signal and execution code where feasible
- isolate replay-specific assumptions in the backtest layer

---

## The Live Engine Must Preserve These Invariants

### Invariant 1: Legal before profitable

An illegal order set is a broken strategy, regardless of expected PnL.

### Invariant 2: No hidden state dependence

If a decision depends on memory, that memory must come from `traderData`.

### Invariant 3: One product module cannot silently corrupt another

Shared services may be global.
Strategy state must remain namespaced by product or mechanic.

### Invariant 4: Every order has an economic reason

Allowed reasons:

- visible positive edge
- spread capture
- inventory reduction
- hedge necessity
- conversion edge
- signal-based directional positioning

### Invariant 5: A fallback path always exists

If a fancy estimator fails, we should degrade to a simpler one rather than stop functioning.

---

## Fair Value Doctrine

Fair value is the heart of the engine.

We should treat it as a layered system, not a single formula.

### Estimator classes

1. Constant anchors
2. Book-derived fair values
3. Rolling time-series fair values
4. Cross-product synthetic fair values
5. Theoretical fair values for derivatives/conversions

### Resolution order

Per product, choose the most appropriate available estimator and maintain fallbacks.

Example philosophy:

- use anchor if product is structurally fixed
- use book-based microstructure if dominant liquidity is informative
- use short-memory rolling models if product drifts
- use synthetic fair values if instrument is linked to others
- use theoretical value if instrument has explicit pricing structure

### Rule

Execution and risk logic should not need to know how fair value was computed.

---

## Execution Doctrine

Execution should be framed as policy under uncertainty.

### Taker mode

Use when:

- visible quote is clearly favorable versus fair value
- inventory needs urgent relief
- hedge is necessary

### Maker mode

Use when:

- fair value is stable enough
- spread capture is attractive
- inventory is not too skewed

### Capacity recovery mode

Use when:

- current position blocks future opportunity
- inventory is near hard limits
- flattening at low edge is acceptable

### Rule

Signals decide desired behavior.
Execution decides whether that behavior becomes passive or aggressive.

---

## Risk Doctrine

Risk management should be local first, extensible later.

### Phase-1 concerns

- hard per-product limits
- aggregate intended buy/sell checks
- inventory skewing
- flattening discipline

### Later concerns

- multi-product exposure budgeting
- hedge consistency checks
- capital allocation by strategy family
- regime-aware aggressiveness

### Rule

We do not optimize away the risk layer.
We optimize through it.

---

## Persistence Doctrine

Persistent state should be:

- explicit
- versioned
- compact
- reconstructible

Recommended persisted items:

- last fair values
- small rolling windows
- rolling means / variances
- detector flags
- limited recent extrema
- recent inventory regime info

Recommended non-persisted items:

- raw trade tapes
- full order book histories
- charts
- verbose diagnostic logs

---

## Diagnostics Doctrine

The engine should produce enough information to answer:

1. What did we think fair value was?
2. What opportunity did we believe existed?
3. Why did we choose maker, taker, or flattening behavior?
4. What did risk clipping remove?
5. How did the trade perform after 1, 5, and 20 steps?

If we cannot answer these questions, we are not ready to optimize.

---

## Backtesting Doctrine

Backtesting is for structured skepticism.

### Required outputs

- total PnL
- PnL by product
- maker vs taker split
- fill counts
- average edge at entry
- inventory path
- time near limits
- markouts
- timestamp slices for best and worst trades

### Fill philosophy

Start conservative:

- visible marketable orders fill
- passive fills are conservative or disabled at first

Only add more sophisticated fill heuristics when they are justified by data and clearly labeled as assumptions.

### Rule

A high backtest PnL without believable fill assumptions is negative evidence, not positive evidence.

---

## Strategy Lifecycle

A strategy module should move through this lifecycle:

1. hypothesis
2. minimal implementation
3. conservative replay
4. review pack
5. robustness sweep
6. live candidate
7. live simplification if needed

No strategy should skip directly from idea to production because of one attractive chart.

---

## Round-General vs Round-Specific Logic

### Round-general modules

- state store
- market normalization
- fair-value interface
- risk clipping
- execution modes
- logging
- replay engine
- metrics and reporting

### Round-specific modules

- product strategy logic
- conversions
- option pricing
- basket construction
- trader-ID logic
- manual-round workflows

The architecture should maximize reuse in the first group so the second group stays small.

---

## Proposed Repository Shape

```text
prosperity/
  README.md
  ARCHITECTURE_DOCTRINE.md
  requirements.txt

  data/
    raw/
    processed/

  notebooks/
    01_tutorial_eda.ipynb
    02_fair_value_inference.ipynb
    03_backtest_review.ipynb

  src/
    datamodel.py
    trader.py

    core/
      config.py
      state_store.py
      market_data.py
      fair_value.py
      signals.py
      execution.py
      risk.py
      logger.py
      types.py
      utils.py

    strategies/
      base.py
      stable_anchor.py
      adaptive_quote.py

    backtest/
      replay_engine.py
      fill_model.py
      metrics.py
      reporting.py
      sweep.py

    scripts/
      run_backtest.py
      run_review.py
      validate_submission.py

  outputs/
    backtests/
    charts/
    review_packs/

  tests/
    test_state_store.py
    test_market_data.py
    test_risk.py
    test_execution.py
```

We may simplify names later, but the layer boundaries should remain.

---

## Initial Build Order

### Phase 0

- create repo skeleton
- move tutorial data into structured `data/raw`
- establish `README` and doctrine

### Phase 1

- `datamodel.py`
- `trader.py`
- `state_store.py`
- `market_data.py`
- `risk.py`
- `config.py`

### Phase 2

- `fair_value.py`
- `execution.py`
- first strategy for stable-anchor product
- minimal replay script

### Phase 3

- metrics
- reporting
- review pack generation

### Phase 4

- adaptive fair-value strategy
- parameter sweeps
- stronger diagnostics

### Phase 5

- round-specific extensions as needed

---

## What We Will Explicitly Avoid Early

- heavy ML inside `Trader.run()`
- giant state payloads
- opaque parameter piles
- hardcoded one-off hacks with no explanation
- optimistic passive fill assumptions
- product logic mixed directly into `trader.py`
- building every future mechanic before the baseline works

---

## Decision Standard

A change is good only if it improves at least one of these without damaging the others:

- correctness
- reuse
- interpretability
- speed of iteration
- robustness under new rounds

This is the standard we should hold every module to.

---

## Final Doctrine

We are not building a submission file.
We are building a reusable trading engine for a changing simulated market.

That engine should be:

- thin in production
- rich offline
- modular by design
- explicit about state
- strict about legality
- centered on fair value
- inventory-aware
- easy to review

If we stay disciplined on these principles, optimization later becomes easier, not harder.

# System Architecture

> **Scope**: Implementation map of the modules, types, and data flows
> that exist today. Not a design-principles document — see
> [ARCHITECTURE_DOCTRINE.md](../ARCHITECTURE_DOCTRINE.md) for that.

Last verified against commit `d48ec48`.

This document maps the actual codebase so you can navigate the code and
understand how the pieces connect.

---

## Live data flow

Every call to `Trader.run(state)` in `src/trader.py` follows this path:

```
TradingState (from Prosperity container)
  |
  +-- StateStore.load(traderData)              -> EngineState
  |                                               [src/core/state_store.py]
  +-- MarketDataAdapter.normalize_state(state) -> dict[str, NormalizedSnapshot]
  |                                               [src/core/market_data.py]
  |
  |   +-- per product -----------------------------------------------+
  |   | FlowAnalyzer.scan(snapshot, memory)    -> FlowReport | None  |
  |   |                                           [src/signals/flow_analyzer.py]
  |   |                                                              |
  |   | strategy.generate_intent(StrategyContext) -> SignalIntent     |
  |   |   +-- FairValueEngine.estimate()       -> FairValueEstimate  |
  |   |   |                                       [src/core/fair_value.py]
  |   |   +-- SignalEngine.build_market_making_intent()              |
  |   |                                           [src/core/signals.py]
  |   |                                                              |
  |   | ExecutionEngine.generate_orders()      -> list[Order]        |
  |   |                                           [src/core/execution.py]
  |   | ResidualAllocator.augment_orders()     -> list[Order]        |
  |   |                                           [src/core/residual.py]
  |   | RiskManager.clip_orders()              -> list[Order]        |
  |   |                                           [src/core/risk.py]
  |   |                                                              |
  |   | DecisionLogger.record(event)              [src/core/logger.py]
  |   | Trader._update_memory(memory, snapshot)                      |
  |   +--------------------------------------------------------------+
  |
  +-- StateStore.save(engine_state)            -> traderData: str
  +-- return (orders, conversions, traderData)
```

`FlowAnalyzer.scan()` is observational only — it persists flow scores
in `ProductMemory` but never alters strategy behaviour.

---

## Live-path module map

The live path is the set of modules that ship to Prosperity. They are
listed in `LIVE_MODULE_ORDER` in `src/scripts/export_submission.py` in
the exact topological order the exporter uses. Each module may only
import from modules above it in this list (plus `src/datamodel.py`).

| # | Module | Layer | Key exports |
|---|--------|-------|-------------|
| 1 | `src/core/utils.py` | Foundation | `bounded_append`, `weighted_average` |
| 2 | `src/core/types.py` | Foundation | `NormalizedSnapshot`, `ProductMemory`, `EngineState`, `FairValueEstimate`, `SignalIntent`, `QuoteIntent`, `BookLevel`, `TradePrint`, `FlowReport`, `ScannerConfig`, `ResidualConfig`, `ExecutionMode` |
| 3 | `src/core/config.py` | Foundation | `ProductConfig`, `EngineConfig`, `default_engine_config()`, `KNOWN_STRATEGY_NAMES`, `KNOWN_ESTIMATOR_NAMES` |
| 4 | `src/core/logger.py` | Foundation | `DecisionLogger` (bounded event buffer) |
| 5 | `src/core/market_data.py` | Data | `MarketDataAdapter.normalize_state()` |
| 6 | `src/core/fair_value.py` | Pricing | `Estimator` protocol, 7 estimator classes, `ESTIMATORS` dict, `FairValueEngine` |
| 7 | `src/core/state_store.py` | Persistence | `StateStore.load()`, `StateStore.save()` |
| 8 | `src/signals/__init__.py` | Signals | Package init |
| 9 | `src/signals/flow_analyzer.py` | Signals | `FlowAnalyzer.scan()` |
| 10 | `src/core/signals.py` | Signals | `SignalEngine.build_market_making_intent()` |
| 11 | `src/core/execution.py` | Execution | `ExecutionEngine.generate_orders()` |
| 12 | `src/core/risk.py` | Risk | `RiskManager.clip_orders()`, `Capacity` |
| 13 | `src/core/residual.py` | Risk | `ResidualAllocator.augment_orders()` |
| 14 | `src/strategies/base.py` | Strategy | `BaseStrategy` ABC, `StrategyContext` |
| 15 | `src/strategies/market_making.py` | Strategy | `MarketMakingStrategy.generate_intent()` |
| 16 | `src/strategies/__init__.py` | Strategy | `STRATEGY_REGISTRY`, `StrategyFactory` |
| 17 | `src/trader.py` | Orchestrator | `Trader.run()` |

---

## Key types

All defined in `src/core/types.py` unless noted.

| Type | Mutability | Produced by | Consumed by |
|------|-----------|-------------|-------------|
| `NormalizedSnapshot` | frozen | `MarketDataAdapter` | Fair value, signals, execution, risk, flow analyzer |
| `ProductMemory` | mutable | `StateStore.load()` | Fair value estimators, flow analyzer, `Trader._update_memory()` |
| `EngineState` | mutable | `StateStore.load()` | `Trader._run_body()`, `StateStore.save()` |
| `FairValueEstimate` | frozen | `FairValueEngine.estimate()` | `SignalEngine`, execution, logging |
| `SignalIntent` | frozen | `BaseStrategy.generate_intent()` | `ExecutionEngine.generate_orders()` |
| `QuoteIntent` | frozen | `SignalEngine` (nested in `SignalIntent`) | `ExecutionEngine` |

`NormalizedSnapshot` exposes computed properties: `best_bid`, `best_ask`,
`mid`, `spread`, `book_imbalance`, `microprice`.

`ProductMemory` carries: `recent_mids`, `recent_spreads` (bounded
rolling lists), plus `counters`, `flags`, `values` dicts for stateful
detectors.

---

## Fair value estimators

Registered in the `ESTIMATORS` dict at the bottom of
`src/core/fair_value.py`. Each implements the `Estimator` protocol:
`name` attribute and `estimate(snapshot, memory, config)` returning
`FairValueEstimate | None`.

| Name | Class | Primary input |
|------|-------|---------------|
| `anchor` | `AnchorEstimator` | `config.anchor_price` (constant) |
| `mid` | `MidEstimator` | `snapshot.mid` |
| `microprice` | `MicropriceEstimator` | `snapshot.microprice` |
| `rolling_mid` | `RollingMidEstimator` | `memory.recent_mids` |
| `weighted_mid` | `WeightedMidEstimator` | `memory.recent_mids[-4:]` + `snapshot.mid` |
| `ewma_mid` | `EwmaMidEstimator` | `memory.recent_mids` + `config.ewma_alpha` |
| `depth_mid` | `DepthMidEstimator` | Full book VWAP |

`FairValueEngine.estimate()` tries the primary method, then each
fallback in order, then `anchor_fallback`, then `zero_fallback`. It
never returns `None`.

---

## Offline harness

The offline replay and analysis pipeline lives in `src/backtest/` and
`src/scripts/`.

### Replay pipeline

```
CSV files (data/raw/round_N/)
  -> ReplayEngine.from_files()    [src/backtest/replay_engine.py]
  -> list[ReplayStep]
  -> BacktestSimulator.run()      [src/backtest/simulator.py]
  -> SimulationResult             [src/backtest/metrics.py]
       .per_product: dict[str, ProductResult]
       .trade_records: tuple[TradeRecord, ...]
       .mid_series, .fair_value_series, .pnl_series
```

The simulator drives a real `Trader` instance, scoring taker fills
against the visible book and passive fills with a one-step delay against
observed market trades.

### Key offline modules

| Module | Purpose |
|--------|---------|
| `src/backtest/replay_engine.py` | Parse CSVs into `ReplayStep` iterator |
| `src/backtest/simulator.py` | `BacktestSimulator.run()` -> `SimulationResult` |
| `src/backtest/fill_model.py` | `FillModel` with taker and passive fill logic |
| `src/backtest/metrics.py` | `TradeRecord`, `ProductResult`, `SimulationResult` |
| `src/backtest/reporting.py` | Review pack generation (metrics + charts + records) |
| `src/backtest/charts.py` | PnL, position, price/FV, trade marker charts |
| `src/backtest/sweep.py` | Parameter sweep engine |
| `src/backtest/parameter_sweep.py` | Multi-day cross-slice sweep orchestrator |
| `src/backtest/plateau.py` | Plateau detection in sweep results |
| `src/backtest/fair_value_compare.py` | Side-by-side estimator comparison |
| `src/backtest/drilldown.py` | Timestamp-level step-through inspection |
| `src/backtest/provenance.py` | Reproducibility metadata |

### Entry-point scripts

| Script | Purpose |
|--------|---------|
| `src/scripts/run_backtest.py` | Single backtest run |
| `src/scripts/run_review.py` | Review pack with metrics, charts, trade records |
| `src/scripts/compare_fair_values.py` | Phase 3 estimator bake-off |
| `src/scripts/run_parameter_sweep.py` | General parameter sweep |
| `src/scripts/run_phase6_emeralds_sweep.py` | EMERALDS cross-day robustness sweep |
| `src/scripts/run_phase6_tomatoes_sweep.py` | TOMATOES cross-day robustness sweep |
| `src/scripts/run_drilldown.py` | Step-through trade inspection |

Output goes to `outputs/review_packs/`, `outputs/sweeps/`, `outputs/backtests/`.

---

## Submission pipeline

Covered in detail by
[docs/phase_9_submission_checklist.md](phase_9_submission_checklist.md).

- **Export**: `src/scripts/export_submission.py` reads each module in
  `LIVE_MODULE_ORDER`, strips internal imports, hoists stdlib imports,
  and concatenates into one file. Two modes: `--datamodel=platform`
  (real submission) and `--datamodel=inline` (dev smoke test).
- **Validate**: `src/scripts/validate_submission.py` runs AST checks:
  structure (Trader class, run method, 3-tuple return), forbidden
  imports, residual `src.*` imports, file I/O, size budget (soft 72 KiB,
  hard 96 KiB).
- **CI gate**: `scripts/check.sh --submission` runs ruff, black, mypy,
  pytest, export, and validate scoped to the live path.

---

## State persistence

`StateStore` in `src/core/state_store.py` serializes `EngineState` to
compact JSON for the `traderData` string.

- **Budget**: 50,000 characters (configurable via
  `EngineConfig.max_trader_data_chars`).
- **Overflow**: truncate histories to last 8 samples, then drop all
  product memory. Never crash or exceed budget.
- **Corruption**: `load()` returns a fresh `EngineState` on any parse
  failure. Never raises.
- **NaN guard**: `save()` uses `allow_nan=False`; drops all memory if
  non-finite values leak in.
- **Migration**: `_migrate()` hook is a no-op today; plumbing exists for
  future schema bumps.

---

## Cross-references

| Topic | Document |
|-------|----------|
| Design principles | [ARCHITECTURE_DOCTRINE.md](../ARCHITECTURE_DOCTRINE.md) |
| Fair value inference | [docs/phase_3_fair_value_note.md](phase_3_fair_value_note.md) |
| Backtest review protocol | [docs/phase_4_review_discipline_note.md](phase_4_review_discipline_note.md) |
| TOMATOES tuning | [docs/phase_5_tomatoes_baseline_note.md](phase_5_tomatoes_baseline_note.md) |
| Parameter sweeps | [docs/phase_6_robustness_note.md](phase_6_robustness_note.md) |
| Submission packaging | [docs/phase_9_submission_checklist.md](phase_9_submission_checklist.md) |
| Manual rounds | [docs/manual_round_playbook.md](manual_round_playbook.md) |

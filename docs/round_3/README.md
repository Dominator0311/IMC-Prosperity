# R3 "Options Require Decisions" — Handoff Package

**This directory is a self-contained execution package for R3.** A fresh agent with no prior conversation context should be able to execute everything here.

## Goal

Maximize R3 P&L. Submit a Trader bundle for the R3 final simulation plus manual Bio-Pod bids.

**Round dynamics:** R3 trades 2 delta-1 products (HYDROGEL_PACK, VELVETFRUIT_EXTRACT) and 10 European call options on VELVETFRUIT (vouchers at strikes 4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500). TTE at R3 start = 5 days. End-of-round flatten against a hidden fair value. R3 is **fully independent** of R1/R2/tutorial.

## Read these docs in order

1. **[PLAN.md](PLAN.md)** — what to build, why, expected P&L per component.
2. **[EXECUTION_GUIDE.md](EXECUTION_GUIDE.md)** — how to build each item: files to touch, tests to write, done criteria, environment setup.
3. **[BOT_BEHAVIOR.md](BOT_BEHAVIOR.md)** — Tier 2 signal exploits (defer until baseline ships).
4. **[ALPHA_ATLAS.md](ALPHA_ATLAS.md)** — historical statistical analysis (reference only; use PLAN for decisions).

## What's already built vs what needs building

**Already in the codebase** (confirmed by directory audit):
- `src/core/primitives/` — SST, HysteresisSizer, PortfolioContext, PortfolioRiskManager, CrashTelemetry, FillCalibrationHarness, SweepSelector, SignalBus, SignalValidation, PredictiveEstimator, VolumeRobustMid, EngineOrchestrator (all 12 primitives, ~2,600 LOC)
- `src/options/` — BSM + IV solver + smile fitter (~470 LOC)
- `src/engines/` — OptionsEngine, BasketArbEngine, StatArbEngine, CounterpartyIntelligenceEngine (~1,500 LOC; note: engines are generic scaffolding — they need R3 product wiring, not R3 alpha logic)
- `src/backtest/` — SimulatorReplay, FillModel, ParameterSweep, Reporting
- `src/scripts/calibration/` — calibration runners
- `src/scripts/export_submission.py` — flattens to Prosperity-required single-file Trader

**Needs building for R3** (all new code per the plan):
- R3 product config in `src/core/config.py`
- HYDROGEL MM strategy in `src/strategies/round_3/`
- VEV_4000 synthetic MM strategy
- Voucher tiny-liquidity strategies (K=5400, K=5500)
- Aggregate delta manager wiring in orchestrator
- Terminal risk ramp policy
- Tier 2 signal emitters (after baseline)

See [EXECUTION_GUIDE.md](EXECUTION_GUIDE.md) for concrete file-level specs.

## Data location

R3 historical data lives at `ROUND_3/` (repo root, not under `data/raw/`):
```
ROUND_3/prices_round_3_day_{0,1,2}.csv
ROUND_3/trades_round_3_day_{0,1,2}.csv
```
CSV delimiter is `;`. Timestamps run 0 → 999,900 in steps of 100. See EXECUTION_GUIDE for loader pattern.

## Success criteria

Tier 1 (ship gate):
- All Tier 1 items 1–12 in the PLAN queue implemented.
- Leave-one-day-out OOS replay confirms each strategy positive PnL on 2/3 held-out days.
- Submission bundle (`src/scripts/export_submission.py`) produces a single file ≤ 128KB.
- Trader.run() tick latency p99 ≤ 900ms (Prosperity 1s budget with margin).
- No uncaught exceptions in full 3-day replay under `_reraise_exceptions=True`.

Tier 2 (post-baseline):
- Each signal passes 4-test validation harness before enabling.
- Each signal ships with "widen/pause" default, not "cross/fade."

## Expected P&L

Per PLAN v3:
- Tier 1 algorithmic: **+5,500–5,900** conservative (15% fill-rate capture)
- Manual Bio-Pods: **+~4,200**
- Tier 2 bot exploits: **+230–480**
- **Total conservative: +9,960–10,510**
- Aggressive (25% fill): **~+13,400**

HYDROGEL MM + VEV_4000 MM = ~80% of algorithmic P&L. Everything else is infrastructure or lottery.

## Non-goals

Things deliberately NOT being built (see PLAN Part 3 for reasoning):
- IV residual scalper — empirically killed (see PLAN Part 1.4).
- Delta-hedged K=5300/5400 MM — hedge cost > spread capture.
- Short ATM theta — IV ≈ RV, no edge.
- Vertical spread arb, HYDROGEL↔VELVET pairs trade, deep-OTM at-price MM.
- Recreating the external dashboard (prosperity.equirag.com).

Do not revisit these without new empirical evidence.

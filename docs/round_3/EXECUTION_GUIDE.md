# R3 Execution Guide

**Purpose:** turn the PLAN into executable tickets. A fresh agent should be able to read this doc, open the right files, implement, test, and ship without needing to ask questions.

---

## Environment

```bash
# Python 3.12, venv at repo root
.venv/bin/python --version  # should be 3.12+

# Run tests
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
PYTHONPATH=. .venv/bin/python -m pytest tests/unit/ -m unit

# Run replay / backtest (example pattern — adapt paths)
PYTHONPATH=. .venv/bin/python -m src.scripts.run_backtest --data ROUND_3 --day 0 --strategy hydrogel_mm

# Build submission bundle
PYTHONPATH=. .venv/bin/python -m src.scripts.export_submission --output submission_r3.py
```

**Conventions** (from `~/.claude/CLAUDE.md` and repo):
- Type hints everywhere (strict mypy).
- Files under 400 lines; split if larger.
- Immutable dataclasses where possible (`@dataclass(frozen=True)`).
- pytest markers: `@pytest.mark.unit` for fast tests, `@pytest.mark.integration` for replay tests.
- Write tests first (TDD). 80%+ coverage for new core logic.
- Commits: conventional format (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`).

---

## Codebase orientation

```
src/
├── trader.py               # Entrypoint: Trader.run() — do not put strategy logic here
├── datamodel.py            # Prosperity-given types (Order, TradingState, etc.)
├── core/
│   ├── config.py           # Product factory — ADD R3 products here
│   ├── config_core.py      # EngineConfig dataclass
│   ├── fair_value.py       # FairValueEngine + estimator interface
│   ├── execution.py        # ExecutionEngine (order gating, pos limits)
│   ├── risk.py             # RiskManager
│   ├── market_data.py      # Snapshot normalization
│   ├── state_store.py      # traderData serialization
│   ├── signals.py          # SignalEngine (observational)
│   ├── residual.py         # ResidualAllocator
│   ├── logger.py           # DecisionLogger
│   └── primitives/         # R3+ building blocks (all pre-built, import and use)
│       ├── sst.py                  # TakeClearMake scaffold
│       ├── hysteresis_sizer.py
│       ├── portfolio_context.py    # PortfolioContext (cross-product state)
│       ├── portfolio_risk.py       # PortfolioRiskManager (aggregate delta)
│       ├── crash_telemetry.py      # Error counting + kill-switch
│       ├── fill_calibration.py     # FillCalibrationHarness
│       ├── sweep_selector.py       # Bootstrap-CI param selection
│       ├── signal_bus.py           # Pub/sub for signals
│       ├── signal_validation.py    # 4-test harness
│       ├── predictive_estimator.py # Reactive + signal-correction fair
│       ├── volume_robust_mid.py    # VolumeRobustMid estimator
│       └── engine_orchestrator.py  # EngineOrchestrator (composes engines)
├── options/
│   ├── bsm.py              # Black-Scholes + IV solver (Brent method)
│   └── smile.py            # Quadratic smile fitter
├── engines/                # Composed engines (generic; need R3 wiring)
│   ├── options_mm.py
│   ├── basket_arb.py       # NOT USED in R3
│   ├── stat_arb.py         # NOT USED in R3
│   └── counterparty_intel.py  # NOT USED in R3 (buyer/seller ID columns are empty)
├── strategies/
│   ├── base.py
│   ├── round_1/            # R1 strategies (reference only; do not modify for R3)
│   └── round_3/            # CREATE THIS DIRECTORY — home for new R3 strategies
├── signals/
│   └── flow_analyzer.py    # Existing flow analyzer (observational)
├── backtest/
│   ├── simulator.py        # BacktestSimulator
│   ├── fill_model.py       # FillModel (passive/taker)
│   ├── replay_engine.py    # Replay runner
│   ├── parameter_sweep.py  # Sweep runner
│   └── reporting.py        # Result formatting
└── scripts/
    ├── run_backtest.py
    ├── export_submission.py  # Bundles to single-file Trader for submission
    ├── calibration/
    │   └── run_calibration.py
    └── round_3/              # CREATE THIS — sweep and calibration runners for R3
```

---

## Data loading pattern

```python
import csv
from collections import defaultdict
from pathlib import Path

def load_day(day: int, base: Path = Path("ROUND_3")) -> dict:
    """Load R3 day N: returns {ts: {product: {'mid', 'bid', 'ask', 'bv', 'av'}}}."""
    snap = defaultdict(dict)
    with open(base / f"prices_round_3_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            try:
                ts = int(row["timestamp"])
                snap[ts][row["product"]] = {
                    "mid": float(row["mid_price"]),
                    "bid": float(row["bid_price_1"]),
                    "ask": float(row["ask_price_1"]),
                    "bv": float(row["bid_volume_1"]),
                    "av": float(row["ask_volume_1"]),
                }
            except (ValueError, KeyError):
                continue
    return dict(snap)

def load_trades(day: int, base: Path = Path("ROUND_3")) -> list:
    trades = []
    with open(base / f"trades_round_3_day_{day}.csv") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            try:
                trades.append({
                    "ts": int(row["timestamp"]),
                    "symbol": row["symbol"],
                    "price": float(row["price"]),
                    "qty": int(row["quantity"]),
                })
            except (ValueError, KeyError):
                continue
    return trades
```

`buyer`/`seller` columns exist but are empty in R3. Do not rely on them.

---

## Product constants

```python
# Add to src/core/config.py or a new src/core/r3_products.py

HYDROGEL_PACK = "HYDROGEL_PACK"
VELVETFRUIT_EXTRACT = "VELVETFRUIT_EXTRACT"
VOUCHER_STRIKES = [4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500]
VOUCHER_PRODUCTS = [f"VEV_{k}" for k in VOUCHER_STRIKES]

POS_LIMITS = {
    HYDROGEL_PACK: 200,
    VELVETFRUIT_EXTRACT: 200,
    **{p: 300 for p in VOUCHER_PRODUCTS},
}

# TTE at R3 final sim start = 5 days. Timestamps go 0 → 999,900 step 100.
TTE_DAYS_AT_R3_START = 5.0
TICKS_PER_DAY = 1_000_000  # internal units; step = 100

def tte_live(timestamp: int) -> float:
    """Time to expiry in days at given ts within R3."""
    return TTE_DAYS_AT_R3_START - timestamp / TICKS_PER_DAY
```

---

## Ticket-by-ticket spec

### T01 — Fill-model calibration on R3 tape (3h, BLOCKING)

**Why:** every sweep after this depends on the fill model being accurate for R3 microstructure (voucher books have different dynamics than R1/R2 delta-1 products).

**What to build:**
- `src/scripts/round_3/run_fill_calibration.py`
- Uses existing `src/core/primitives/fill_calibration.py` harness
- Sweep `passive_allocation ∈ {0.05, 0.10, 0.20, 0.30, 0.50}` separately for:
  - Delta-1 products (HYDROGEL, VELVET, VEV_4000) — balanced flow
  - OTM vouchers (K=5300+) — one-sided bid-only flow
- Also measure separately: taker fill rate, passive-queue fill rate, 1-tick-improved fill rate

**Reference harness:** follow pattern in `src/scripts/calibration/run_calibration.py`.

**Done criteria:**
- Reports calibrated `passive_allocation` per product class, written to `outputs/round_3/calibration/<timestamp>.json`.
- Documents the chosen fill-model parameters (which we use in all subsequent sweeps) in a note at `docs/round_3/CALIBRATION_RESULT.md`.
- Unit test in `tests/unit/round_3/test_fill_calibration.py` that the harness runs end-to-end on synthetic data.

---

### T02 — HYDROGEL inside-spread MM (2h)

**Why:** +27,360 3-day replay. Dominant algorithmic alpha.

**What to build:**
- `src/strategies/round_3/hydrogel_mm.py`
- Implements a class `HydrogelMarketMaker(BaseStrategy)` from `src/strategies/base.py`
- Uses `SST` primitive from `src/core/primitives/sst.py` with config:
  ```python
  SSTConfig(
      take_width=8,     # cross if opponent beyond fair ± 8
      clear_width=3,    # flatten excess when |pos| > 100
      default_edge=3,   # INITIAL VALUE — tune in T02b sweep
      prevent_adverse=True,
      max_quote_size=10,  # per-side; break bigger into child orders in T13
  )
  ```
- Fair value = `FilteredWallMidEstimator` (already in `src/core/fair_value.py`) with min-volume filter ≥ 10.
- Inventory skew: quote tilts by `min(1.0, abs(pos)/100) × sign(pos)` ticks.

**Done criteria:**
- Unit tests: SST integration, quote generation at pos=0/+50/-50/+180, fair-value fallback.
- Integration test: 3-day replay produces ≥ 75% of the +27,360 theoretical (≥ +20,500) at 100% fill rate with no risk-manager rejections.
- Registered in `STRATEGY_REGISTRY` in `src/strategies/__init__.py`.

**T02b — parameter sweep** (+1h after T02):
- Use `src/core/primitives/sweep_selector.py` (SweepSelector with bootstrap-CI).
- Grid: `default_edge ∈ {1, 2, 3, 4}`, `clear_width ∈ {2, 3, 5}`, `skew_strength ∈ {0.5, 1.0, 1.5}`.
- Selection rule: leave-one-day-out × 3 permutations; pick params whose 95% CI lower bound > baseline CI upper bound.

---

### T03 — Aggregate delta/gamma manager (3h, BLOCKING T04/T06)

**Why:** VEV_4000 and voucher positions compete for VELVET hedge capacity (±200). Must enforce hard caps centrally.

**What to build:**
- Extend `src/core/primitives/portfolio_risk.py` (do not rewrite — add R3-specific policy).
- New class `R3DeltaBudget` in `src/core/primitives/r3_delta_budget.py`:
  ```python
  @dataclass(frozen=True)
  class DeltaCaps:
      soft: int = 80       # early session
      hard: int = 130      # mid session
      terminal: int = 40   # after t = 850_000

  class R3DeltaBudget:
      def net_delta(self, portfolio: PortfolioContext) -> float: ...
      def remaining_capacity(self, ts: int, portfolio: PortfolioContext) -> int: ...
      def enforce(self, intended_orders: list[Order], ...) -> list[Order]: ...
  ```
- Net delta = `VELVET_pos + VEV_4000_pos × 1.0 + Σ(voucher_pos[K] × delta[K])`.
- Engine orchestrator calls `budget.enforce(orders, ts, portfolio)` before execution layer.

**Done criteria:**
- Unit tests: cap enforcement at each session phase; terminal cap triggers at t=850_000; VEV_4000 vs voucher competition resolves deterministically (priority: HYDROGEL > VEV_4000 > vouchers).
- Integration test: 3-day replay never exceeds hard cap, never exceeds terminal cap in last 150K ticks.

---

### T04 — VEV_4000 synthetic-underlying MM (3h, requires T03)

**Why:** +7,546 hedged 3-day replay. Second alpha source.

**What to build:**
- `src/strategies/round_3/vev_4000_mm.py`
- Class `Vev4000MarketMaker(BaseStrategy)` using SST primitive.
- Fair value from VELVET bid/ask with explicit hedge buffer:
  ```python
  hedge_buffer = 0.5 * velvet_spread  # absorb VELVET spread cost
  bid_fair = velvet_bid - 4000 - hedge_buffer
  ask_fair = velvet_ask - 4000 + hedge_buffer
  ```
- Default edge: 3 (inside 21-wide book).
- Soft cap: ±150. Hard cap: ±200, but only if `R3DeltaBudget.remaining_capacity() >= 50`.
- Delta-hedge via VELVET (through delta manager) when `|voucher_pos × 1.0| > 40`.

**Done criteria:**
- Unit tests: fair calculation, hedge-buffer correctness, cap interaction with delta budget.
- Integration test: 3-day replay produces ≥ 75% of +7,546 theoretical (≥ +5,660) with full delta hedging enabled.

---

### T05 — BSM + smile fitter integration (3h, BLOCKING T06)

**Why:** Needed for (a) voucher delta estimates consumed by T03, (b) quote sanity guard in T06, (c) terminal liquidation mark estimates.

**What to build:**
- Wire `src/options/smile.py` into a per-tick fitter called by the main orchestrator.
- New class `SmileCache` in `src/core/primitives/smile_cache.py`:
  ```python
  class SmileCache:
      def update(self, ts: int, S: float, T: float,
                 strike_mids: dict[int, float]) -> None: ...
      def fair(self, K: int) -> float | None: ...
      def delta(self, K: int) -> float | None: ...
      def iv(self, K: int) -> float | None: ...
  ```
- Fit-all quadratic on core strikes {5000, 5100, 5200, 5300, 5400, 5500}. Do NOT use leave-one-out (reviewer confirmed fit-all is more robust in production).
- Expose `is_corrupt(K)` method: returns True if `|book_mid - fair(K)| > 2 * sigma_IV * vega(K)`.

**Done criteria:**
- Unit tests: BSM round-trip (price → IV → price), smile fit convergence, corruption detector.
- Latency: fit + query p99 ≤ 5ms per tick.

---

### T06 — Voucher tiny-liquidity (K=5400, K=5500) (2h, requires T03/T05)

**Why:** Absorb one-sided flow at small caps. Not a P&L engine. +150 shells expected.

**What to build:**
- `src/strategies/round_3/voucher_liquidity.py`
- Class `VoucherTinyLiquidity(BaseStrategy)` with per-strike configuration.
- Rules (K=5400 spread=1, K=5500 spread=1):
  ```
  bid_quote = best_bid               # join, do NOT improve
  ask_quote = best_ask                # join, do NOT improve
  if pos >= soft_cap:
      do_not_bid = True
      ask_quote = best_ask - 1        # improve ask to recycle inventory
  if SmileCache.is_corrupt(K):
      no_quote = True
  if DeltaBudget.remaining_capacity() < 10:
      do_not_bid = True
  ```
- Soft/hard caps: K=5400 ±50/±100; K=5500 ±100/±150.
- **Do NOT implement K=5300 MM.** K=5300 position only arises as byproduct of other strategies.

**Done criteria:**
- Unit tests: quote rules at pos=0/soft/hard, corruption-guard integration, delta-budget interaction.
- Integration test: 3-day replay shows P&L in `[-200, +400]` range after hedging (acceptable; this is inventory absorption, not alpha).

---

### T07 — VELVET hedge infrastructure (2h)

**Why:** Primary hedge leg. Not a P&L bucket.

**What to build:**
- `src/strategies/round_3/velvet_hedge.py`
- Class `VelvetHedgeInfra(BaseStrategy)`:
  - Tight inventory band ±60.
  - Strong skew: skew_strength = 2.0 × min(1, |pos|/60).
  - Target position: `target = −Σ(voucher_pos[K] × delta[K]) − vev_4000_pos`.
  - Bands:
    - `|net_delta| < 40`: passive MM only, no directional intent.
    - `40 ≤ |net_delta| ≤ 120`: skew quotes to move toward target.
    - `|net_delta| > 120`: cross (take) to restore budget.

**Done criteria:**
- Unit tests: band transitions, target calculation, skew behavior.
- Integration test: 3-day replay, VELVET position stays within ±60 except during hedge events.

---

### T08 — Zero-bid lottery + acceptance probe (1h)

**Why:** Cheap optionality on VEV_6000/VEV_6500 if platform accepts price-0 orders.

**What to build:**
- `src/strategies/round_3/zero_bid_lottery.py`
- Class `ZeroBidLottery(BaseStrategy)`:
  - Place `BUY @ 0` on VEV_6000 and VEV_6500 for full position capacity (300 each).
  - On first 10 ticks: log whether order was accepted / rejected (check OrderBook response).
  - If rejected: disable self and emit a `ZeroBidRejected` signal.

**Done criteria:**
- Unit test: order generation at price=0 with correct quantity.
- Integration test: probes acceptance on first tick; replay shows 0 cash cost regardless.

---

### T09 — Sub-intrinsic safety guardrail (1h)

**Why:** Prevent our own asks from being left below intrinsic.

**What to build:**
- Extend `src/strategies/round_3/vev_4000_mm.py` with an ask-floor check:
  ```python
  intrinsic = max(velvet_bid - K, 0)
  our_ask = max(our_ask, intrinsic + 1)
  ```
- Scanner component (very low hit rate; 1/30K per strike): if a competitor ask < `velvet_bid - K`, lift + short-hedge. Implemented as a side function, runs alongside main MM.

**Done criteria:**
- Unit test: ask-floor enforcement.
- Scanner rarely fires; log a `SubIntrinsicHit` signal when it does for observability.

---

### T10 — Terminal risk ramp (2h)

**Why:** End-of-round flatten against hidden FV. Start ramping at t=850K, near-flat by t=950K.

**What to build:**
- `src/core/primitives/terminal_ramp.py`
- Class `TerminalRamp`:
  ```python
  def scale_factor(ts: int) -> float:
      if ts < 850_000: return 1.0
      if ts >= 950_000: return 0.0
      return (950_000 - ts) / 100_000
  ```
- Apply `scale_factor` to all inventory bands (soft and hard caps) on all strategies EXCEPT the zero-bid lottery (0-cost fills are exempt).
- After t=920K, cross to flatten voucher deltas first (via delta manager), voucher notionals second.

**Done criteria:**
- Unit test: scale factor values at t=840K/860K/900K/950K.
- Integration test: 3-day replay with ramp enabled shows |pos| < 20 per product by t=950K (excluding exempt strikes).

---

### T11 — Manual challenge: Bio-Pod bids (0.5h, separate submission)

**Why:** Round objective includes manual Bio-Pod bids. Independent of algo.

**What to do:**
- Check Manual Challenge Overview UI for bid-increment rule.
- **If integer bids accepted:** submit `b1 = 751, b2 = 841`.
- **If multiples of 5 forced:** submit `b1 = 755, b2 = 840`.
- Re-submit any time before round close.
- Log the submitted bids in `docs/round_3/MANUAL_SUBMISSION.md`.

**Rationale:** pure EV optimum is 751/836 at 84.33 per counterparty. Nudge b2 up to 841 to sit above expected crowd cluster at ~835-840; costs 0.11 EV vs optimum. See reviewer analysis.

---

### T12 — Leave-one-day-out OOS validation (3h, SUBMIT GATE)

**Why:** naive OOS contaminates across days; rigorous validation is leave-one-day-out × 3 permutations.

**What to build:**
- `src/scripts/round_3/run_loo_validation.py`
- For each of days {0, 1, 2}: tune parameters on the other 2 days, evaluate on the held-out day.
- Report per-strategy: 3-day pooled PnL, per-day PnL, 95% CI bootstrap.
- Ship gate: each strategy's validation-day PnL must be ≥ 0 in at least 2/3 permutations.

**Done criteria:**
- Validation report produced in `outputs/round_3/validation/<timestamp>/report.md`.
- All Tier 1 strategies pass the gate OR are explicitly disabled in the submission bundle with a documented reason.

---

### T13–T16 — Tier 2 bot-exploit signals (8h total, post-baseline)

See [BOT_BEHAVIOR.md](BOT_BEHAVIOR.md) for full specs. Summary:

- **T13 — Granular quote sizing** (1h): break size-20 orders into 4×size-5. Architectural change to SST primitive.
- **T14 — VELVET toxicity filter** (3h): signal emitter + consumer wiring. Must pass 4-test harness.
- **T15 — Basket-dump detector** (2h): cross-product coincidence signal.
- **T16 — HYDROGEL size-bucket adjustment** (2h): smaller signal, ship last.

Each Tier 2 signal goes through `SignalBus` (existing primitive). Do NOT enable until 4-test validation passes.

---

## Submission pipeline

```bash
# After all Tier 1 items pass validation:

# 1. Regenerate the bundle
PYTHONPATH=. .venv/bin/python -m src.scripts.export_submission \
    --output submission_r3.py \
    --profile r3

# 2. Verify bundle size ≤ 128KB
ls -l submission_r3.py

# 3. Smoke-test the bundle
PYTHONPATH=. .venv/bin/python -c "
import sys; sys.path.insert(0, '.')
exec(open('submission_r3.py').read())
# Trader class should be in globals
t = Trader()
print('OK' if hasattr(t, 'run') else 'MISSING run()')
"

# 4. Upload submission_r3.py to Prosperity UI

# 5. Submit manual Bio-Pod bids in UI (T11)
```

---

## Common pitfalls (learned during this plan's development)

1. **Don't use mid for executable calculations.** Use bid/ask with half-spread cost. Mid-based "arb" opportunities vanish once bid/ask are used (see sub-intrinsic scanner: 73 apparent → 1 actual over 3 days).
2. **Don't trust leave-one-out smile residuals in production.** LOO overstates wing-strike residuals by ~2× vs fit-all. Use fit-all for live quoting.
3. **Don't assume passive MM is positive EV on narrow-spread OTM options.** The hedge cost (VELVET spread × delta) can exceed the voucher spread capture. Apply the rule: `spread_capture > delta × velvet_spread × 0.5`.
4. **Don't use tick-level sigma as input to BSM.** Microstructure noise inflates by ~75%. Use 500–1000-tick sampling for realized vol.
5. **Don't treat warehoused VELVET positions as alpha.** End-of-day markout is −0.82/qty. Any strategy that accumulates VELVET without flattening loses money.
6. **Watch the timestamp unit.** Timestamps go 0 → 999,900 in steps of 100. Terminal ramp at "t=9000" is wrong; correct is t=850,000.
7. **Don't enable the CounterpartyIntelligenceEngine.** It needs revealed buyer/seller IDs; R3 has them blank. Leaving it enabled will either no-op or emit garbage signals.
8. **VEV_4000 delta = 1.0 always**, not from BSM. Don't let a smile-fit delta artifact push it below 1.
9. **VEV_6000/6500 are tick-pinned at 0.5**. Don't try to MM them at positive prices.
10. **The IV residual scalper is dead.** All 4 tested variants lose. Don't rebuild it.

---

## Where to ask for help (if blocked)

- **Strategy design questions** → re-read PLAN.md Part 2 for the canonical spec.
- **Empirical questions** ("is X alpha real?") → run a replay test following the patterns in this session (see `BOT_BEHAVIOR.md` methodology).
- **Primitive behavior** → read the docstring of the primitive in `src/core/primitives/`; they're all documented.
- **Fill-model fidelity** → T01 calibration output drives this.
- **R3 rules ambiguity** → the user (session operator) is the only source; ask explicitly.

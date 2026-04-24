# R3 Alpha Atlas — "Options Require Decisions"

**Data source:** `ROUND_3/` (3 historical days, products verified).
**Verification status:** Derived from first-pass statistical analysis of day-0/1/2 price files. Every number below is reproducible from the CSVs.

---

## Confirmed product universe (R3, fully independent of R1/R2/tutorial)

| Product | Class | Pos limit | Day-0 mid | Spread | Daily σ | Notes |
|---|---|---|---|---|---|---|
| HYDROGEL_PACK | delta-1 | 200 | 9990.96 | **16 wide** | 2.17% (tick) | Stable anchor, wide spread |
| VELVETFRUIT_EXTRACT | delta-1 | 200 | 5246.51 | 5 wide | 2.14% (tick) | Voucher underlying |
| VEV_4000 | call, ITM | 300 | 1246.52 | 21 wide | ≈ S−K | Synthetic S (δ≈1) |
| VEV_4500 | call, ITM | 300 | ~747 | 16 wide | - | Synthetic S (δ≈1) |
| VEV_5000 | call, ITM | 300 | 253.26 | 6 wide | TV=6.75 | 0 trades/day 0 |
| VEV_5100 | call, ~ATM | 300 | TV=21.6 | 4 wide | - | 0 trades/day 0 |
| VEV_5200 | call, ~ATM | 300 | TV=51.0 | 3 wide | - | 3 trades/day 0 |
| VEV_5300 | call, ~ATM | 300 | TV=48.9 | 2 wide | - | 37 trades/day 0 |
| VEV_5400 | call, OTM | 300 | TV=18.5 | 1 wide | - | 64 trades/day 0 |
| VEV_5500 | call, OTM | 300 | TV=8.1 | 1 wide | - | 81 trades/day 0 |
| VEV_6000 | call, deep OTM | 300 | 0.5 pinned | 1 wide | - | Floor, not tradable edge |
| VEV_6500 | call, deep OTM | 300 | 0.5 pinned | 1 wide | - | Floor, not tradable edge |

TTE at R3 start = 5 days. Historical days 0/1/2 = TTE 8/7/6.

---

## Vol reality check (single most important number in this doc)

Tick-level σ is inflated by microstructure noise. Subsampled on VELVET day 0:

| Sampling step | Scaled daily σ |
|---|---|
| 1 tick | 2.14% |
| 10 ticks | 1.82% |
| 100 ticks | 1.80% |
| 500 ticks | 1.20% |
| 1000 ticks | 0.67% |

**True diffusive σ ≈ 0.8–1.2% per day.** Tick-level inflated by ≈75% (classic bid-ask bounce; HYDROGEL AR(1) half-life=189 ticks, VELVET=206 ticks confirms negative autocorrelation).

Implied vol at ATM strikes = **1.27% / √day** (flat across K=5000–5500 on all 3 days).

**Verdict:** ATM calls are **slightly rich vs diffusive RV** (IV 1.27 vs RV ~1.0–1.2). Small but positive theta edge; gamma cost depends on realized intraday path. Not a no-brainer alpha — must be run through our fill calibrator.

---

## The alpha map

### TIER 1 — Size, high confidence, build first

**A1. HYDROGEL_PACK MM** (dominant safe alpha)
- 16-wide spread, mean-reverting (φ=0.996), half-life 189 ticks, μ=9991.
- Zero correlation with VELVET (ρ=0.011) → independent.
- Quote at mid ± 2–3 against 16-wide book → ~10 ticks of theoretical edge per round trip.
- Inventory-skew via SST template. Pos limit 200 is binding at steady state.
- **Expected scale:** largest single P&L contributor. Similar profile to ASH_COATED_OSMIUM in R1.

**A2. VELVETFRUIT_EXTRACT MM**
- 5-wide spread, same MR regime (φ=0.9966, half-life 206).
- Same SST template with tighter default edge.
- Gets re-used as the delta-hedge leg for option positions — double duty.

**A3. Sub-intrinsic voucher opportunism**
- Day 0: **73 timestamps** where VEV_4000 ask < (S − 4000), same count for VEV_4500.
- Buy the call at ask + short-hedge VELVET = near-riskless carry (K=4000 is 1247 ITM; probability of S < 4000 in 5 days at σ=1%/√d is ~0).
- Implementation: scanner engine, top-of-book take, auto-hedge. Low complexity, runs concurrently with everything else.
- **Expected scale:** modest per event (tick-sized profit), but compounds over hundreds of hits across 10k ticks × 3 remaining days.

### TIER 2 — Medium confidence, needs calibration

**A4. Smile-relative-value trader**
- Fitted IV surface is extremely stable: K=5000–5500 all sit at 1.22–1.32% across day 0/1/2. Wings (K=4000, 4500, 6000, 6500) look "high" but are IV-solver artifacts from near-intrinsic pricing, not tradable.
- Fit quadratic in log(K/F), trade 2σ residuals expecting mean-reversion to fit.
- Needs the P4 BSM/IV/smile primitives (already built in `src/options/smile.py`) plus a rolling-window smile fitter.

**A5. ATM theta harvest with delta + gamma management**
- Sell VEV_5200 or VEV_5300 (ATM, highest TV: 50/48 on day 0).
- Delta-hedge aggregate book with VELVET (δ ≈ 0.6 at ATM).
- P&L = theta − gamma × RV². Edge exists only if IV > diffusive RV (barely true here).
- Risk: one sharp VELVET move wipes the theta buffer. Kill-switch on |r|/EWMA > 3.

**A6. Voucher MM on liquid strikes (K=5300, 5400, 5500)**
- Spread 1–2 wide, volume 40–90 trades/day.
- Requires predictive fair via BSM(smile) not just book mid.
- Low size per trade, but 90 trades × ~1-tick edge × 3 days is real.

### TIER 3 — Exploratory / speculative

**A7. Synthetic underlying via VEV_4000**
- Delta ≈ 1.0, 50% more capacity (300 vs 200) for expressing VELVET views.
- Usable when directional signal on VELVET is validated; purely additive to A2.

**A8. Convexity residual (butterfly)**
- Butterflies (5100, 5200, 5300) etc. all non-negative (good — no direct arb).
- But the C(5200)/C(5300) pair has fat TV vs neighbors. Long 5100-5200-5300 fly is positive carry if smile stays U-shaped; short if smile flattens.

**A9. Gamma scalping via VELVET + ATM long calls**
- Long ATM call + short δ·VELVET captures paid-vs-realized variance differential. Only profitable if RV > IV — marginal here.

### TIER 4 — Verified dead ends

- **Vertical spread arbitrage via bid/ask** — 0/10000 crossable opportunities on day 0. The "mid diff = 500.5 vs 500" observation is a mid-price rounding artifact.
- **Deep-OTM voucher trading (K=6000, K=6500)** — mid pinned at 0.5 by tick floor, no liquidity. Hold a token lottery position or skip.
- **Cross-product statistical arb (HYDROGEL ↔ VELVET)** — ρ = 0.011. Truly independent. No pair trade.

---

## How to find MORE alpha (the hunting method, not just the hunt)

Our architecture already supports this; these are the concrete gates.

### Step 1 — Fill-model calibration against R3 data
Current `BacktestSimulator` `passive_allocation` was tuned against R1/R2. Voucher/option microstructure is different (wider spreads, thinner flow). Before any strategy sweep:
- Port one top-team P3 options repo through our sim on R3 data.
- Sweep passive_allocation ∈ {0.05, 0.10, 0.20, 0.30, 0.50}.
- Adopt the value that reproduces their published R3-equivalent P&L within 5%.
- **Gate: no sweep results are trusted until this completes.**

### Step 2 — Smile fitter on R3 historical (3-day OOS)
- Fit rolling-window smile on day 0, score on day 1, refit and score on day 2.
- Parameters: log-moneyness degree (1, 2, 3), window size (500, 1000, 2000 ticks), center-weighting.
- OOS IC target: > 0.2 on voucher mid residuals to justify smile-based trading.

### Step 3 — Signal validation on every proposed alpha
Run the 4-test harness from `src/core/primitives/signal_validation.py`:
- (a) Shuffle: randomize t, IC collapses to ~0 ✓
- (b) Strict-lag: feature at t−k predicting mid at t (not t+k, no leakage) ✓
- (c) Walk-forward OOS: train day 0, test day 1, test day 2 ✓
- (d) Own-quote causality: remove ticks where our simulated orders top the book, IC survives ✓

Any signal missing any of the 4 → research-log only, NOT traded.

### Step 4 — Sweep with the bootstrap-CI selector
`src/core/primitives/sweep_selector.py` already exists. Run it on:
- A1 HYDROGEL MM (edges 1/2/3, skew 0.2/0.5/0.8).
- A2 VELVET MM (edges 1/2).
- A3 intrinsic scanner (threshold 0.0/0.5/1.0).
- A5 ATM theta (size 50/100/200, hedge band 0.3/0.5/0.7).
- Winner must exclude baseline upper CI — "plateau picking" disallowed.

### Step 5 — Composite engine wiring
Use the `EngineOrchestrator` in `src/core/primitives/engine_orchestrator.py` to run all alphas concurrently:
- OptionsEngine owns vouchers (A4, A5, A6, A7, A8) + delta-hedging leg on VELVET.
- StandardMM owns HYDROGEL (A1) and a slice of VELVET (A2).
- IntrinsicScanner (new, ~50 LOC) owns A3.
- PortfolioRiskManager caps aggregate gross/net exposure and delta.

### Step 6 — End-of-round liquidation discipline
"Hidden fair value at round end" is not disclosed. Minimize terminal inventory in final 1000 ticks:
- Linear ramp-down of gross exposure from t=9000 → t=10000.
- Flatten voucher deltas before flattening voucher notionals (theta cost is less than delta slippage).
- This is mechanical; no alpha but protects everything else.

---

## Prioritized build queue

| # | Item | Primitive reuse | Effort | Expected P&L rank |
|---|---|---|---|---|
| 1 | Fill-model calibration on R3 data | `FillCalibrationHarness` | 3h | Gate on everything |
| 2 | A1 HYDROGEL MM (SST template + sweep) | `SST`, `SweepSelector` | 2h | #1 |
| 3 | A2 VELVET MM (same template) | `SST` | 1h | #3 |
| 4 | A3 Intrinsic scanner engine | (new ~50 LOC) | 2h | #4 |
| 5 | Smile fitter + validator | `src/options/smile.py` | 4h | Gate on A4/A5/A6 |
| 6 | A5 ATM theta harvest engine | `OptionsEngine` | 3h | #2 (if calibration confirms) |
| 7 | A4 Smile RV trader | `OptionsEngine` | 4h | #5 |
| 8 | A6 Voucher MM on K=5300/5400/5500 | `OptionsEngine` | 2h | #6 |
| 9 | Composite wiring + terminal-ramp | `EngineOrchestrator` | 3h | Protects above |

Total: ~24h for everything. 10h for Tier 1 + calibration = MVP.

---

## Open questions (don't block Tier 1)

- **End-of-round hidden FV for vouchers:** is it intrinsic (max(S−K, 0)), is it BSM(remaining_TTE, some_sigma), or something else? Materially changes the correct liquidation target. Punt: flatten by t=10000 regardless.
- **Trade fills on top-of-book aggressive orders:** confirmed real in R1/R2 but not yet verified for voucher books. The fill calibration step answers this.
- **Does the voucher book behave differently when VELVET moves fast?** I.e., does quoted spread widen dynamically, affecting MM profitability? Check during calibration.

---

## Not-yet-verified assertions (flag for future checking)

1. The 73 sub-intrinsic hits/day on VEV_4000 may be stale quotes that are auto-filtered before they're hittable. Confirm during fill calibration.
2. "Smile is stable day-over-day" is based on mean IV per strike across 10k ticks; intra-day, smile may wobble meaningfully. Check with rolling 1000-tick windows.
3. "Tick-level RV is inflated by bid-ask bounce" is standard microstructure, but the magnitude (75% inflation) is larger than typical. Could be genuine tick-level noise in the simulator. Fix either way; theta edge is thin.

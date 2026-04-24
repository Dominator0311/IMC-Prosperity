# R3 Product Review and Alpha-Extraction Plan (v3 — post delta-hedge reality check)

**Scope:** every tradable product in R3, what it is, how it behaves, what alpha it offers, and why. All numbers verified against `ROUND_3/` day-0/1/2 CSVs.

**Status:** v3 supersedes v2. Key changes from v2:
- **Voucher complex downgraded.** Delta-hedged passive MM on K=5300/5400 is net-negative after hedge cost. Only K=5400/5500 as tiny passive liquidity; K=5300 dropped. Expected voucher P&L cut from ~+1k to ~+150.
- **HYDROGEL + VEV_4000 confirmed as ~80% of round P&L** under disciplined risk management.
- **Bot-behavior exploits** added as Tier 2 (separate doc: [BOT_BEHAVIOR_NOTES.md](BOT_BEHAVIOR_NOTES.md)).
- **Manual challenge** re-added (dropped accidentally in v2).
- **Aggregate delta cap** specified numerically: soft ±80, hard ±130, terminal ±40.
- **Terminal ramp start moved earlier** to t=850,000 per reviewer #3.

**Ground rules:** R3 is fully independent of R1/R2/tutorial. TTE at R3 start = 5 days (`T_live = 5 − ts/1_000_000`). Voucher pos limits 300 each; delta-1 pos limits 200. Timestamps run 0 → 999,900 in steps of 100. End-of-round hidden-FV liquidation.

---

## Part 1 — Product-by-product review

### 1.1 HYDROGEL_PACK (delta-1, pos 200)

- Mid pinned ≈ 9991 across all 3 days; range ±80; drift < 3 points over 3 days.
- AR(1) φ = 0.99634, half-life 189 snapshots.
- Spread median **16** — very wide. Layer-2 always present.
- Trade flow 1960 LP-buys vs 2118 LP-sells → balanced, MM-friendly.
- **Passive LP replay at ±200 cap: +27,360 over 3 days.** Dominant alpha source.
- LP markout: +7.76 / qty immediate, +6.92 / qty end.
- Trade sizes: **5 unique values {2,3,4,5,6}** → ~5 distinct bots with fixed shot sizes.

### 1.2 VELVETFRUIT_EXTRACT (delta-1, pos 200)

- Mid drifts 5246 → 5248 → 5255; small upward drift.
- AR(1) φ = 0.99664, half-life 206 snapshots.
- Spread median 5. Layer-2 only 27% of time.
- Diffusive σ ≈ 0.96–1.52% per day (overlapping RV at step 500–1000).
- Trade flow 3344 LP-buys vs 4925 LP-sells → public bias toward lifting asks.
- LP markout: +1.71 / qty immediate, **−0.82 / qty end** (warehousing drag).
- **Passive LP replay at ±200 cap: +2,030 over 3 days.** 12× weaker than HYDROGEL.
- **Size-11+ trades carry +1.92 markout** — strongest toxicity signal in the data.
- **Role:** delta-hedge infrastructure, not a standalone P&L bucket.

### 1.3 VEV_4000 (deep-ITM call, pos 300, delta ≈ 1)

- Mid ≈ VELVET − 1000, tracks intrinsic almost exactly.
- Spread median **21** — widest book in R3.
- Trade flow 485 LP-buys vs 455 LP-sells → balanced.
- LP markout: **+9.96 / qty immediate, +10.31 / qty end.**
- **Passive LP replay at ±300 cap: +9,750 unhedged, +7,546 hedged.** The 21-wide spread buries the VELVET hedge cost. Second alpha after HYDROGEL.
- Trade sizes: **3 unique values {1,2,3}** → only 3 bots touch this strike.
- Role: standalone wide-spread MM with VELVET as delta hedge.

### 1.4 The 10 vouchers — complete summary

**Price/flow table:**

| Strike | Class | Spread | Trades/day | Flow direction | Unhedged replay | **Delta-hedged replay** |
|---|---|---|---|---|---|---|
| 4000 | deep ITM | 21 | 172 | balanced | +9,750 | **+7,546** |
| 4500 | ITM | 16 | 0 | — | — | — |
| 5000 | ITM | 6 | 0 | — | — | — |
| 5100 | near-ATM | 4 | 0 | — | — | — |
| 5200 | near-ATM | 3 | 3 | all at bid | +1,360 | **−37** |
| 5300 | near-ATM | 2 | 37 | all at bid | +3,399 | **+324** (rebalanced) |
| 5400 | OTM | 1 | 64 | all at bid | +2,420 | **+530** (rebalanced) |
| 5500 | OTM | 1 | 81 | all at bid | +866 | **+566** |
| 6000 | deep OTM | 1 | 91 | all at bid | +0.50/qty pinned | n/a |
| 6500 | deep OTM | 1 | 91 | all at bid | +0.50/qty pinned | n/a |

**First-principles rule:** passive voucher MM is net-positive only when `voucher_spread_capture > delta × VELVET_spread × 0.5`.

| Product | Spread capture | Delta | Hedge cost | Net edge / fill |
|---|---|---|---|---|
| HYDROGEL | ~7 | n/a | 0 | **+7** ✓ |
| VEV_4000 | ~10–15 | 1.0 | 2.5 | **+7–12** ✓ |
| VEV_5300 | ~0.7 | 0.5 | 2.5 | **−1.8** ✗ |
| VEV_5400 | ~0.5 | 0.3 | 1.5 | **−1.0** ✗ |
| VEV_5500 | ~0.5 | 0.1 | 0.25 | **+0.25** ✓ (marginal) |

**Implication:** K=5300 and K=5400 cannot be hedged profitably. Without hedging, they're long-delta bets on VELVET (worse than just trading VELVET directly).

**Smile structure** (fit-all quadratic in log-moneyness):

| Strike | Mean residual |
|---|---|
| K=5300 | +1.36 (rich) |
| K=5400 | −2.17 (cheap) |
| K=5500 | +0.55 |

**Residual dynamics:** persistent bias (level autocorr 0.65–0.96 at lag 100) but NOT tradeable mean reversion. Confirmed by executable-edge test: IV scalper loses across all variants (causal EWMA / slow EWMA / no baseline / pairs trade) at every horizon and threshold.

---

## Part 2 — The alpha plan

### Plan A — HYDROGEL_PACK market-making (dominant)

Take/clear/make on 16-wide book.

- SST primitive with `default_edge = 2–3`, `take_width = 8`, `clear_width = 3`.
- Sweep `default_edge ∈ {1, 2, 3, 4}`, skew strength ∈ {0.2, 0.5, 0.8}.
- Break passive quotes > size-8 into size-5 child orders (matches bot shot sizes for better queue rotation).
- **Expected contribution: ~+4,100 shells** (15% fill-rate capture of +27.4k replay).

### Plan B — VEV_4000 synthetic-underlying MM (hedge-aware)

Wide-spread MM against VELVET-derived fair with explicit hedge-cost buffer.

- `voucher_bid_fair = VELVET_bid − 4000 − 0.5 × VELVET_spread`
- `voucher_ask_fair = VELVET_ask − 4000 + 0.5 × VELVET_spread`
- Quote at fair ± edge (edge 2–3 inside 21-wide book).
- Soft cap: ±150; hard cap: ±200 only if aggregate delta budget allows.
- Delta-hedge via VELVET when |voucher_pos × delta| > 40.
- **Expected contribution: ~+1,130 shells** (15% fill capture of +7.55k hedged replay, accounting for ~22% hedge cost).

### Plan C — Voucher passive liquidity: K=5400 / K=5500 only (K=5300 DROPPED)

**Not a P&L engine. Inventory absorption at a small acceptable delta cost.**

Not "MM with edge" — "willing to absorb one-sided flow at small caps, with explicit exit assumptions."

**K=5400 (spread 1):**
- Join best bid only (do not improve by 1 — that crosses to ask).
- Do not bid if |net_delta budget| already consumed.
- Post ask only when |pos| > soft_cap (inventory recycle).
- Soft cap: ±50. Hard cap: ±100.
- Stop bidding entirely at pos ≥ soft_cap.

**K=5500 (spread 1):**
- Same rules as K=5400 but larger cap (lower delta per contract).
- Soft cap: ±100. Hard cap: ±150.

**K=5300: dropped from MM list.** Hedged economics are −1.8 per fill. Allow position only as a byproduct of delta-hedging other strikes; do not actively quote.

**Expected contribution: ~+150 shells** (5400 + 5500 combined).

### Plan D — VELVET as hedge infrastructure (not a P&L bucket)

- Tight inventory band ±60 (not ±200).
- Strong skew-to-zero, growing stronger as t → 850,000.
- Aggregate delta target: `target_velvet = −Σ(voucher_pos[K] × delta[K]) − vev4000_pos`.
- Hedge bands: do-nothing if |net_delta| < 40, passive-skew if 40–120, cross if > 120.
- **Expected contribution: ~+150 shells** (reduced from v2's +300 once hedge-crossing costs accounted for).

### Plan E — VEV_6000 / VEV_6500 zero-bid lottery

- Place `BUY @ 0` on both strikes for full capacity.
- First tick: probe whether price-0 orders are accepted. Log result.
- If accepted and hidden end-of-round FV marks at mid ≥ 0.5: up to +300 shells total.
- If rejected or marks at intrinsic (0): zero impact.

### Plan F — Sub-intrinsic safety guardrail

- Scanner: if `voucher_ask < VELVET_bid − K`, buy voucher + short VELVET.
- Executable hit-rate: 1/30,000 per strike over 3 days. Effectively never fires.
- Purpose: prevent our own quoter from leaving asks below intrinsic.
- Not alpha; correctness guard.

### Plan G — Terminal risk ramp (start earlier)

- From **t = 850,000**: begin linear reduction of all inventory bands.
- By t = 950,000: near-flat (|pos| < 20 per product). VEV_6000/6500 0-cost fills exempt.
- Flatten voucher deltas before flattening voucher notionals.
- Moved earlier per reviewer #3: starting at 900K was too late given hedge unwind cost.

### Plan H — Aggregate delta/gamma manager (explicit caps)

Owns shared delta budget across Plans B, C, D.

```
net_delta = VELVET_pos
          + VEV_4000_pos × 1.0
          + Σ(voucher_pos[K] × delta[K])

soft cap:     ±80    (early session)
hard cap:    ±130    (mid session)
terminal:     ±40    (after t = 850,000)
```

Triggers hedge crossings in VELVET when voucher engines push delta beyond budget. VEV_4000 and OTM voucher positions **compete** for the same hedge capacity.

### Plans I–L — Tier 2 bot-exploit signals

Defer until Tier 1 baseline ships. Full spec in [BOT_BEHAVIOR_NOTES.md](BOT_BEHAVIOR_NOTES.md).

- **I — VELVET toxicity filter.** Size-11+ VELVET trade → widen adverse side for 1,000 ts. +100–200 shells.
- **J — HYDROGEL size-bucket adjustment.** Size-6+ HYDROGEL trade → widen adverse side for 500 ts. +30–80 shells.
- **K — Basket-dump detector.** ≥3 vouchers trade same ts same side → pause voucher bidding for 500 ts. +50–100 shells.
- **L — Granular quote sizing.** Break size-20 orders into 4 × size-5. Architectural. +50–100 shells (may be bundled into Plans A–C at build time).

All pass the 4-test validation harness before going live.

### Plan M — Manual challenge: Celestial Gardeners' Guild Bio-Pods

- Reserves uniform at 5-increments on {670, 675, …, 920}, 51 levels.
- Resell price 920. Two-bid rule with cubic crowd penalty on b2.
- **Ship (integer bids): b1 = 751, b2 = 841.** EV ≈ 84.22 per counterparty (vs 84.33 at optimal 751/836).
- **Ship (multiples-of-5 forced): b1 = 755, b2 = 840.** EV ≈ 81.67.
- Rationale for 841 over 836: sacrifices 0.11 of baseline EV to sit above expected crowd cluster at ~835–840.
- Submit via Manual Challenge Overview window before R3 close.

---

## Part 3 — What we explicitly do NOT build

| Rejected alpha | Why |
|---|---|
| IV residual scalper (any variant) | Empirically killed across 4 tested configs. ~0% win rate, negative PnL everywhere. |
| Delta-hedged K=5300 / K=5400 MM | Spread capture < hedge cost. Net −1.8 / −1.0 per fill. |
| **Unhedged** K=5300 voucher MM | Long-delta bet with worse economics than VELVET direct. |
| Short ATM theta (naked) | IV ≈ RV; ambiguous EV, bad gamma. |
| Long K=5400 / short K=5300 pairs | 2/3 days losing, 3-day net −10.68. |
| Smile-driven voucher entries | Adverse selection. |
| Vertical spread arb (4000/4500) | 0 crossable ticks in bid/ask. Mid rounding artifact. |
| HYDROGEL ↔ VELVET pair trade | ρ = 0.011. |
| MM on K=4500 / 5000 / 5100 | 0 trades/day. No flow. |
| VEV_6000/6500 at-positive-price MM | Tick-floored; no spread. |
| Piggybacking informed VELVET trades | n=49, asymmetric downside. Defense > offense on small samples. |

---

## Part 4 — Priority build queue

| # | Item | Tier | Hours | Gate |
|---|---|---|---|---|
| 0 | Visual EDA on external dashboard → EDA_NOTES.md | prep | 1–2 | — |
| 1 | Fill-model calibration on R3 tape | T1 | 3 | Blocks 2–7 |
| 2 | Plan A — HYDROGEL inside-spread MM + sweep | T1 | 2 | — |
| 3 | Plan H — Aggregate delta/gamma manager (caps enforced) | T1 | 3 | Blocks 4, 6 |
| 4 | Plan B — VEV_4000 synthetic MM with hedge-aware fair | T1 | 3 | — |
| 5 | BSM + IV solver + smile fitter (delta estimates + guardrails) | T1 | 3 | Blocks 6 |
| 6 | Plan C — Voucher tiny passive liquidity (K=5400, K=5500 only) | T1 | 2 | — |
| 7 | Plan D — VELVET hedge infrastructure | T1 | 2 | — |
| 8 | Plan E — Zero-bid lottery + acceptance probe | T1 | 1 | — |
| 9 | Plan F — Sub-intrinsic guardrail | T1 | 1 | — |
| 10 | Plan G — Terminal risk ramp (start t=850K) | T1 | 2 | — |
| 11 | Plan M — Manual challenge submission (751/841 or 755/840) | T1 | 0.5 | Submit separately |
| 12 | Leave-one-day-out OOS validation | T1 gate | 3 | Submit gate |
| — | — | — | **Tier 1 total: ~26h** | — |
| 13 | Plan L — Granular quote sizing (size-5 child orders) | T2 | 1 | — |
| 14 | Plan I — VELVET toxicity filter + signal validation | T2 | 3 | — |
| 15 | Plan K — Basket-dump detector + signal validation | T2 | 2 | — |
| 16 | Plan J — HYDROGEL size-bucket adjustment + validation | T2 | 2 | — |
| — | — | — | **Tier 2 total: ~8h** | — |

**Tier 1 items 1–7 = ~18h and cover ~95% of expected P&L.**

---

## Part 5 — Expected P&L budget (v3, disciplined hedging)

Conservative (15% fill-rate capture):

| Source | Replay 3-day | Conservative ship |
|---|---|---|
| HYDROGEL MM | +27,360 | +4,100 |
| VEV_4000 MM (hedged) | +7,546 | +1,130 |
| VEV_5400/5500 tiny passive | +1,096 | +150 |
| VELVET MM (infrastructure) | +2,030 | +150 |
| Zero-bid lottery | 0–300 | 0–300 |
| Manual challenge (Bio-Pods) | n/a | +4,200 (50 counterparties × 84 EV — estimate) |
| **Tier 1 Total** | | **+9,730–10,030** |
| Tier 2 bot exploits | — | +230–480 |
| **Grand Total** | | **+9,960–10,510** |

Aggressive (25% fill rate): Tier 1 algorithmic ×1.67 ≈ +9,200 algo + manual +4,200 = **+13,400**.

**Key change from v2:** voucher complex dropped from +1,000 to +150. HYDROGEL + VEV_4000 now ~80% of algorithmic P&L.

---

## Part 6 — Risk model

Three real risks:

1. **Pricing bug crashes trader container.** Mitigation: CrashTelemetry with kill-switch at 3 errors / 100 ticks.
2. **Aggregate delta exceeds VELVET hedge capacity.** Mitigation: Plan H hard caps (±130 mid-session, ±40 terminal). VEV_4000 and voucher longs explicitly compete for budget.
3. **End-of-round hidden FV diverges from mid.** Mitigation: flatten by t=950,000. Voucher longs exposed to this more than delta-1 products.

No material risk from:
- HYDROGEL ↔ VELVET correlation (ρ = 0.011).
- Smile fit fragility in production (not used for entries, only sanity + delta estimates).
- IV scalper P&L variance (we're not running it).

---

## Part 7 — Known unknowns

1. **Voucher passive fill rate under one-sided flow.** Calibrate separately from delta-1 fills. Our asks may rarely fill.
2. **Zero-bid order acceptance** — resolves on first tick.
3. **End-of-round FV formula** — punt, flatten by t=950,000.
4. **Manual challenge bid-increment rule** (integer vs multiples-of-5) — verify in UI at submission time.
5. **Whether `EngineOrchestrator` handles concurrent engines within per-tick latency budget** — verified at 119KB R3 bundle; retest during calibration.
6. **Whether bot-exploit signals generalize OOS** — gated by leave-one-day-out validation before shipping each Tier 2 signal.

---

## Part 8 — Change log

### v1 → v2 (post initial independent review + empirical IV scalper test)
- Killed IV residual scalper (4 variants all losing).
- Demoted sub-intrinsic to safety guardrail.
- Dropped naked theta harvest.
- Reframed vouchers as one volatility surface.
- Promoted VEV_4000 to core alpha.

### v2 → v3 (post delta-hedge reality check)
- Voucher passive MM on K=5300/5400 dropped: delta-hedged replay negative (−714 / −752 at hedge-once-at-fill).
- K=5400/5500 downgraded to "tiny passive liquidity" (not "core MM").
- Aggregate delta caps specified numerically: ±80 / ±130 / ±40.
- Terminal ramp start moved from t=900K to t=850K.
- Manual challenge re-added with concrete bids.
- Tier 2 bot-exploit signals added (4 items, specs in separate doc).
- Expected P&L: algorithmic down ~20% (voucher diminished); total up ~40% (manual re-added).

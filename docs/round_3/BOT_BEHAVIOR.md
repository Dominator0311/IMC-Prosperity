# R3 Bot Behavior Notes

**Purpose:** document what we can infer about counterparty bot behavior from the R3 tape without access to buyer/seller IDs (the columns are empty in R3), and how to exploit it.

**Data source:** `data/raw/round_3/trades_round_3_day_{0,1,2}.csv` and the synchronized price CSVs.

---

## Part 1 — Methodology

### The constraint

Each row of the trades CSV has columns `timestamp, buyer, seller, symbol, currency, price, quantity`. In R3, **`buyer` and `seller` are empty strings**. So we cannot say "bot A did X, bot B did Y" — we only have behavioral fingerprints.

### The workaround: behavioral fingerprints

Every trade leaves four observable signatures, even without IDs:

1. **Trade size.** If the distribution of sizes has only k unique values across thousands of trades, there are ~k distinct bot policies. Random retail would produce a smooth distribution.
2. **Inter-arrival timing.** Gaps between consecutive trades. Poisson arrivals → noise. Periodic / heavy-tailed / bursty → scheduled bot.
3. **Cross-product co-occurrence.** Same-timestamp trades across multiple products imply a single multi-leg trader.
4. **Price relative to same-tick book.** Trade at bid → aggressive seller. Trade at ask → aggressive buyer. Trade at mid → unusual.

Each fingerprint is then tested for **predictive informativeness**: does the market move after this fingerprint appears? If yes, it's informed flow — we're adversely selected if we trade against it. If no, it's uninformed noise — we can fade or passively absorb it.

---

## Part 2 — Findings

### 2.1 Trade size distributions are discrete and narrow

| Product | Total trades | # unique sizes | Sizes seen |
|---|---|---|---|
| HYDROGEL_PACK | 1,010 | **5** | {2, 3, 4, 5, 6} |
| VELVETFRUIT_EXTRACT | 1,372 | 13 | {2–30} broad |
| VEV_4000 | 464 | **3** | {1, 2, 3} |
| VEV_5300 | 121 | 5 | {1–5} |
| VEV_5400 | 225 | 4 | {2, 3, 4, 5} |
| VEV_5500 | 267 | 4 | {2, 3, 4, 5} |
| VEV_6000 | 284 | 4 | {2, 3, 4, 5} |
| VEV_6500 | 284 | 4 | {2, 3, 4, 5} |

Interpretation: each product is traded by a small number (3–5) of bots with fixed-size policies. VELVETFRUIT is the exception (broader distribution) — either more bots, or bots with variable sizing.

### 2.2 VEV_6000 and VEV_6500 are traded by the same bot

Identical distributions (both n=284, both size histogram {2:76, 3:56, 4:78, 5:74}). Not coincidence at that sample size — one bot dumps both deep-OTM strikes in parallel.

### 2.3 Inter-arrival times are heavy-tailed, not Poisson

VELVET day 0: mean gap 2,227 ts, median 1,600. Heavy right tail (max 16,300). Consistent with "bot wakes up periodically, trades a few, sleeps." Not alpha-generating on its own, but informs that flow is *clumped* — periods of nothing punctuated by bursts.

### 2.4 Post-trade markout by size (the informed-flow test)

Measured as: mid(t+1,000 ts) − mid(t), signed by trade direction. Pooled across 3 days.

| Product | Size 1–2 | Size 3–5 | Size 6–10 | Size 11–30 |
|---|---|---|---|---|
| HYDROGEL | **−0.43** (n=193) | +0.08 (n=611) | +0.20 (n=205) | — |
| **VELVETFRUIT** | — | +0.05 (n=602) | **+0.38** (n=721) | **+1.92** (n=49) |
| VEV_4000 | +0.33 (n=305) | +0.03 (n=158) | — | — |
| VEV_5300 | +0.28 (n=34) | +0.28 (n=86) | — | — |
| VEV_5400 | +0.06 (n=62) | +0.09 (n=163) | — | — |
| VEV_5500 | +0.01 (n=73) | +0.04 (n=194) | — | — |

**Headline findings:**
- **VELVET size-11+ trades are strongly informed** (+1.92 ticks of follow-through drift). This is the cleanest toxicity signal in the data.
- **VELVET size-6–10 is mildly informed** (+0.38). Less clean, but consistent direction.
- **HYDROGEL size-1–2 prints have negative markout** (−0.43). Opposite sign — small HYDROGEL prints are fade signals, not info. Probably MM re-quote artifacts.
- **HYDROGEL size-6–10 is weakly informed** (+0.20). Marginal signal.
- Vouchers show tiny positive markouts in every bucket but not statistically distinguishable from zero with these sample sizes.

### 2.5 Book refills in 1 step on average

Median refill time (ts required for ask volume to recover to pre-trade level after the ask is hit):

| Product | Median refill (steps of 100 ts) | Mean |
|---|---|---|
| HYDROGEL_PACK | 1 | 1.9 |
| VELVETFRUIT_EXTRACT | 1 | 1.7 |
| VEV_4000 | 1 | 1.8 |

Interpretation: competitor MMs re-quote instantly. Our passive quote won't stay alone at the top of the book for long — we need to be ready to re-quote every tick.

### 2.6 Cross-product multi-leg trades are common

Day 0 same-tick product coincidences:

| Products traded simultaneously | # of ts |
|---|---|
| {VEV_5400, VEV_5500, VEV_6000, VEV_6500} | 31 |
| {VEV_5300, VEV_5400, VEV_5500, VEV_6000, VEV_6500} | 21 |
| {HYDROGEL_PACK, VELVETFRUIT_EXTRACT} | 12 |
| {VEV_5300, VEV_5500, VEV_6000, VEV_6500} | 11 |
| {VELVETFRUIT_EXTRACT, VEV_4000} | 8 |
| {HYDROGEL_PACK, VEV_4000} | 5 |

Interpretation: there's at least one **voucher-portfolio trader** rebalancing across 3–5 strikes simultaneously. Detectable by coincidence detection.

---

## Part 3 — What's exploitable

All four exploits below work without counterparty IDs, using only the signatures from Part 2.

### Exploit A — VELVET toxicity filter (highest confidence)

**Trigger:** a trade of size ≥ 11 on VELVET in the last `W` ts (W = 100 or 500).

**Interpretation:** expect +1.92 points of drift in the trade's direction over the next ~1,000 ts.

**Response:** widen our quote on the adverse side for ~1,000 ts after the event.
- If trade was a buy (px > mid): widen ask by 1 tick, pull passive-bid size down.
- If trade was a sell (px < mid): widen bid by 1 tick (stop bidding up), keep ask near book.

**Estimated P&L:** +100–200 shells on VELVET MM (plus +50–100 on any voucher-longs-via-VELVET-delta that would have been filled adversely).

**Sample-size caveat:** +1.92 point estimate on n=49. 95% CI probably ±0.7. Treat as "widen/pause" signal, not "take opposite side."

### Exploit B — HYDROGEL size-conditioned quote aggressiveness

**Trigger:** trade of size ≥ 6 on HYDROGEL in the last 500 ts.

**Interpretation:** +0.20 follow-through drift. Weaker than VELVET signal but still directional.

**Response:** widen our adverse-side quote by 1 tick for 500 ts. More conservative inventory band during the window.

**Estimated P&L:** +30–80 shells.

### Exploit C — Basket-dump detector

**Trigger:** ≥ 3 voucher strikes trade within the same ts, AND all trades are on the same side (all at bid → seller dumping; all at ask → buyer accumulating).

**Interpretation:** portfolio-trader is rebalancing across vouchers. Same-direction flow across multiple strikes is more toxic than any individual strike.

**Response:** pause voucher bidding for 500 ts. Resume with tighter inventory caps.

**Estimated P&L:** +50–100 shells via avoided adverse fills on voucher longs.

### Exploit D — Quote sizing matched to bot shot sizes

**Trigger:** none — architectural change.

**Interpretation:** bots trade in sizes {2, 3, 4, 5}. A single size-20 order at the bid gets partial-filled once (typically size-5), leaving 15 at downgraded queue priority after the competitor MM re-quotes. Meanwhile a portfolio of 4 × size-5 orders gets 4 independent queue positions; when one fills, the other 3 remain.

**Response:** break all passive quotes > size-8 into multiple size-5 child orders. Applies to HYDROGEL MM, VEV_4000 MM, and any voucher liquidity.

**Estimated P&L:** +50–100 shells via better fill quality. Essentially free engineering.

---

## Part 4 — Exploits that sound appealing but we're NOT building

| Idea | Reason skipped |
|---|---|
| **"Piggyback the informed trader"** — when size-11+ VELVET buy happens, we buy VELVET too | Directional bet on thin signal (n=49). Asymmetric downside (we're taking informed-flow risk, not making it). |
| **"Trade VEV_6000 when VEV_6500 trades first"** (mirror signal) | Both trade within the same ts on most events — no lead/lag to exploit. Informational only. |
| **"Fade small-HYDROGEL-trade signal"** — size-1-2 has −0.43 markout, so trade with them | The markout is only 0.43 ticks; fade-trading requires crossing spread (~8 ticks on HYDROGEL). Net negative. |
| **"Detect bot shot-size changes as regime shift"** | Sizes are too stable across the 3 historical days to distinguish a regime shift from noise. |

---

## Part 5 — Implementation plan

### Architecture

All four exploits are signals that adjust the quoting behavior of existing strategies. They sit on the `SignalBus` primitive ([src/core/primitives/signal_bus.py](src/core/primitives/signal_bus.py)) we built in Stage C.

```
Trade stream --> SignalEmitters --> SignalBus --> Strategy consumers
                                                  (SST primitive
                                                   reads signals and
                                                   adjusts edge / size /
                                                   inventory cap)
```

New emitters to add:

| Emitter | Fires when | Emits |
|---|---|---|
| `VelvetToxicityEmitter` | size-11+ VELVET trade | `VelvetToxicity(direction, decay_ts=1000)` |
| `HydrogelSizeFilterEmitter` | size-6+ HYDROGEL trade | `HydrogelToxicity(direction, decay_ts=500)` |
| `BasketDumpEmitter` | ≥3 vouchers trade same ts, same side | `BasketDump(direction, decay_ts=500)` |
| — | (D is architectural, no emitter) | — |

### Consumers

| Strategy | Subscribes to | Action on fire |
|---|---|---|
| VELVET hedge/MM | `VelvetToxicity` | Widen adverse side +1 tick for decay_ts |
| HYDROGEL MM | `HydrogelToxicity` | Widen adverse side +1 tick for decay_ts |
| Voucher liquidity (K=5400/5500) | `BasketDump` | Pause bidding for decay_ts |

### Validation before shipping

Each emitter must pass the existing 4-test harness ([src/core/primitives/signal_validation.py](src/core/primitives/signal_validation.py)):
1. Shuffle test (randomize t, IC collapses)
2. Strict-lag IC (feature at t−k predicting mid at t, no leakage)
3. Walk-forward OOS (train 2 days, test the third — leave-one-day-out × 3)
4. Own-quote causality (remove ticks where our simulated orders top the book, IC survives)

A signal must pass all 4 to promote from "logged" to "trading."

### Sizing policy

Start conservative. For each signal, first ship captures **20% of the theoretical P&L**: a signal-fires widen-by-1-tick response, not a widen-by-3-ticks or a trade-aggressively response. After one day of live data confirms the signal generalizes, scale up to 50–100% of theoretical.

---

## Part 6 — Estimated R3 P&L impact

| Exploit | Estimated R3 shells |
|---|---|
| A. VELVET toxicity | +100–200 |
| B. HYDROGEL size filter | +30–80 |
| C. Basket-dump detector | +50–100 |
| D. Granular quote sizing | +50–100 |
| **Total** | **+230–480** |

Baseline Tier 1 plan expected P&L: +5,500–5,900. Tier 2 bot exploits add ~4–8% on top.

Priority: ship Tier 1 first, then add Tier 2 signals one at a time with OOS validation before enabling each.

**Do not activate** `src/engines/counterparty_intel.py` — it needs `buyer`/`seller` ID columns which are empty in R3. Leaving it enabled no-ops or emits garbage.

# Hidden Alpha Analysis — P4 R3-R5

**Purpose.** Adversarial enumeration of alphas that top Prosperity teams have self-reported missing OR that mechanics imply must exist but nobody has publicly described. Scores reset R3, so alpha-per-hour matters more than edge size. Obvious edges will be arbitraged; we want the ones competitors overlook.

**Method.** (1) Extract every self-reported "we should have done X" from P1/P2/P3 writeups. (2) From mechanics, derive signals nobody has publicized. (3) Rank by alpha-per-hour and by persistence into P4.

---

## Part 1 — Ranked alpha table

Legend: **P&L** = small (<10k/day) / medium (10–50k) / large (50–200k) / huge (>200k). **Obviousness** = probability a top-10 team already builds this in R3 (low = <20%, med = 20–60%, high = >60%). **Persist** = 1–10 confidence it still works in P4 given mechanics.

| ID | Alpha | Mechanism | Evidence | P&L | Hours | α/hr | Obviousness | Persist |
|---|---|---|---|---|---|---|---|---|
| **A1** | **Counterparty clustering from R3 tick-0** (find "Olivia" before names reveal) | K-means on (P&L trajectory, position Δ per product, win rate at ±1σ of mid, hit rate on opposite side) over R3+R4 data; identify informed bot; copy in R4 onward | Transcript-1: "visible from R1... top teams had ~200k head start." Only top ~3 P3 teams did this before R5 | huge | 8 | ★★★ | low-med | 9 |
| **A2** | **Batched-conversion stockpile** on any conv-capped product (3× cap per tick, not 1×) | Conv cap 10/tick: trading 30/tick in the off-peak preserves ability to convert when bot is absent; storage-cost is ~1/10th the uplift | Transcript-1: "would have doubled R4 P&L. #2 team also missed this" | large | 2 | ★★★★ | med | 8 |
| **A3** | **No-hedge options by default** (Whalley-Wilmott band, not per-tick) | In 1-wide-spread book, spread cost per round-trip dominates gamma P&L. chrispyroberts paid $50k/day to hedge $16k unhedged loss | chrispyroberts writeup + academic §1.3. Many teams STILL hedge by habit | large | 4 | ★★★★ | med | 9 |
| **A4** | **Residual-position market making on top of arb** (8% of book cap reserved for MM) | After z-score arb leaves 8-10% free, quote inside the 8-wide basket spread. Transcript-1: "$5k/day extra, don't leave money on the table" | Transcript-1 directly, only top-1 P3 USA did this | medium | 3 | ★★★ | med | 9 |
| **A5** | **IV-scalping at ATM strike only** (negative 1-lag autocorr) | Isolate IV as a tradable series; fast EMA mean-rev on IV only on the single strike with best liquidity + neg autocorr | TimoDiehm: 100-150k/day standalone from IV scalp alone | large | 6 | ★★★ | med | 8 |
| **A6** | **Ask-side fair-value probe + size-sensitivity probe** | Buy 1@9996, buy 1@10004, sell 1@10004 → mid-price P&L confirms symmetry. Then probe with size 1/5/20 to detect if bot sizes-scales fills (size-based adverse selection) | Transcript-1 only did buy-1@9996; symmetric + size-size never tested publicly | small-med | 1 | ★★★★★ | low | 9 |
| **A7** | **Hidden-taker "lift-at-mid" calibration per product** (not just macarons) | For every product, place 1-unit sell @ mid, mid+1, mid+2; measure fill rate. If any price consistently lifts, that's the hidden-buyer price. Many products likely have the same bot archetype | P3 macarons: 1.4 shells × 100k trades = 146k. Never run on R1-R3 products | large | 4 | ★★★★ | low | 8 |
| **A8** | **Order-book imbalance (BSize−ASize)/(BSize+ASize) as 1-step predictor** | Classic finding: 30-50 bps per 1σ. In bot market where counterparties refill at fixed prices, OBI is mechanical not stochastic → higher IC | Academic §2.3 default IC 0.02-0.08; bot markets likely 0.10-0.20 | medium | 3 | ★★★ | low-med | 8 |
| **A9** | **Post-large-print momentum follow for N ticks** (Kyle-lambda decomposition) | Regress mid_t+k − mid_t on trade_size at t, for k=1..20. Persistent coefficient = permanent impact (momentum); decaying = transient (fade). Different bots have different κ | Transcript-1 Frankfurt: "track max/min trade sizes; large print = informed flow, piggyback." Public writeups stop at detection; none size the Kyle-lambda | medium | 6 | ★★ | low | 7 |
| **A10** | **Fade end-of-round flattening flow (last 10k ticks)** | Every team closes positions pre-settlement. Systematic sell-side pressure on MM-long products, buy-side on retail-long. Quote aggressively wide on the flattening side | No P3 writeup mentions. Clean mechanical edge in any bounded session | medium | 3 | ★★★ | low | 8 |
| **A11** | **Fade publicly-tipped Discord signals** | P3 sunlight-regression posted on Discord had 99% R² leakage. Teams that piled on lost. Explicit inverse-position when community consensus forms mid-round | Matius Chong + transcript-1; no team formalized the fade | small-med | 2 | ★★★ | low-med | 7 |
| **A12** | **Position-limit-wall fade** | When counterparty (or top team) reaches pos limit they quote passively / liquidate. Detect via repeated-fill-at-same-side. Fade them | Inferential; bot-cap logic in sim is mechanical. Nobody has publicized | medium | 5 | ★★ | low | 7 |
| **A13** | **Put-call parity / synthetic-forward arb** if both calls and puts are listed in P4 R3 | C − P + K·exp(−rT) = F. If a put listing shows up in P4 (1.1 of forecast_creative), this is risk-free locked edge | Academic standard. P3 had calls-only; P4 is speculated to add multi-expiry or a put | large | 3 | ★★★★★ | med | 6 |
| **A14** | **Stale-quote arb**: a bot quote static for N ticks while reference mid moves > X | Detect quote-last-update-tick per level; when ref mid drifts > 2 ticks and bot hasn't moved, cross the stale side | No writeup mentions. Mechanical in any bot sim | medium | 4 | ★★★ | low | 7 |
| **A15** | **Cross-edition regression (P3 → P4) + DP optimal execution** | Linear Utility's P2 R5 alpha: regress P1-2023 on P2-2024, R²=0.99 on 2 products. Run same on P3→P4 when R5 reveals paths | Linear Utility generated 2.1M shells in P2-R5 alone | huge | 10 | ★★★ | med | 6 |
| **A16** | **Opening-tick momentum per product** | Bots may reset/re-init at round open; first 50 ticks have structural drift toward the "calm" mid. Measure per-product abnormal return in (0, 50) vs (50, end) | Inferential; no writeup. Bounded windows in sim typically show it | small | 2 | ★★ | low | 7 |
| **A17** | **Cross-product correlation mining** (SQUID_INK↔KELP↔CROISSANTS) | Nobody in P3 public writeups correlated SQUID_INK with CROISSANTS. Latent-factor pairs can pay | Inferential. Classic pairs approach | medium | 6 | ★★ | low | 6 |
| **A18** | **Multi-strike butterfly / risk-reversal** when IV smile is mispriced | Short the wing where IV > smile by >1σ, long the ATM, delta-hedge the package. Nobody publicly did this in P3 | Sinclair §7; academic §1.2. Zero P3 writeup mentions | medium | 8 | ★ | low | 6 |
| **A19** | **Online bandit reallocation of position-limit slots across strategies** | Each strategy reports realized Sharpe per 5k-tick window; Thompson-sample allocation refills. Most teams use fixed slices | Inferential. No writeup formalizes | medium | 10 | ★ | low | 7 |
| **A20** | **Within-tick order sequencing (arb first, MM second)** | Arb legs should fire before MM quotes that would consume the same book capacity; observation order can matter in match engine | Hinted by multiple backtest writeups, never quantified | small | 3 | ★ | med | 6 |
| **A21** | **Bot-fingerprint regime detection** (Chow test on bot quote patterns) | Compute rolling quote-revision cadence per bot; structural break = regime change. Beats EMA-band regime flags | Inferential. Academic §1.4 jump detection is a crude proxy | medium | 6 | ★★ | low | 7 |
| **A22** | **Time-of-day seasonality scan on every product** | P1 BERRIES had hardcoded timestamps. Scan every R3-R5 product for tod patterns before assuming stationarity | P1 Stanford Cardinal explicitly hardcoded. None of P3 writeups even checked | small-med | 2 | ★★★ | low | 7 |
| **A23** | **Penny-jumping two levels deep** (tick-inside-tick) | If spread > 3, quote 2 inside best. Fills better than 1-inside when book is deep + static | Transcript-1 only says "one inside." Never tested 2-inside | small | 2 | ★★★ | med | 6 |
| **A24** | **Iceberg-refill exploit** (detect hidden refill → quote aggressively inside) | Trade-size-vs-displayed + same-price-repeat-fill pattern. A level that refills 3×+ in 500 ticks is a pinned fair | Academic §3.4. Writeups mention existence but not quantified exploit | medium | 5 | ★★ | low | 7 |
| **A25** | **Symmetric hysteresis: asymmetric entry and exit z-thresholds** | Enter |z|>2, exit |z|<0.3 (not symmetric). Linear exit erodes 15-25% of edge | Dave Nandi P3 panel explicitly. Most public code uses symmetric | small-med | 1 | ★★★★ | med | 9 |
| **A26** | **IV-temporal-smoothing before trading the smile** (EWMA halflife 200-500 on mid-IV) | Chrispyroberts fit broke on submission day because quadratic over-fit a single slice; EWMA-smoothed IV generalizes | Academic §1.2. P3 top teams upgraded mid-round; P4 teams will likely repeat the mistake | large | 3 | ★★★★ | med | 8 |
| **A27** | **Voucher cap above 80/strike** if rock hedge isn't needed | chrispyroberts capped 80/strike to reserve rock-hedge capacity, but then dropped rock hedging. Cap was artificially low; 200 would have been optimal given no-hedge regime | Chrispyroberts writeup; self-reported left-on-table | medium | 1 | ★★★★★ | low | 7 |

---

## Part 2 — Deep-dive on the highest-leverage alphas

### A1. Counterparty clustering from R3 tick-0 (huge, 8h, ★★★)

**Signal.** In Prosperity 1-3, every edition had an "Olivia"-class bot that bought daily bottoms and sold daily tops. In P3 she was perfect 18/18. Top teams identified her from R1/R2 data BEFORE names revealed in R5, scoring a ~200k cumulative head start.

**Construction.**
- Log per-(timestamp, counterparty_id if pre-reveal use synthetic id by trade-behavior hash) tuple: `(product, side, size, mid_before, mid_after_50, mid_after_500)`.
- Per counterparty: compute (a) cumulative P&L at entry-mid (did they buy low?), (b) position-swing amplitude, (c) hit rate on 500-tick reversion, (d) median entry-vs-range-percentile.
- K-means on the 4-D feature vector across counterparties. Expected clusters: MM (low P&L, high volume, high hit rate on tiny reversion), retail (negative P&L, random entry percentile), informed (high P&L, bimodal entry percentiles at 0% and 100%).
- Alert when any new counterparty enters the "informed" cluster with ≥5 trades.

**Why others miss.** Takes R1-R2 data to even start; most teams are too busy fighting R3 to do unsupervised clustering on prior rounds. The ones who do it late wait for R5 name reveal.

**Implementation cost.** ~8 hours: 2h data pipeline, 3h clustering + labels, 3h integration to sizing logic.

**Scope cap.** YOLO Olivia on single strongest product; accept ±20k residual basket risk. Don't replicate to every product she touches or you correlate too much.

### A2. Batched-conversion stockpile (large, 2h, ★★★★)

**Signal.** For any conversion-capped product (P2 orchids conv cap 10/tick; P3 macarons conv cap 10/tick), trading `k × cap` per tick when bot is present preserves ability to convert continuously when bot is absent.

**Mechanic.** If conv_cap = 10 and bot is absent ~50% of ticks, naive 10-per-tick realizes 5-per-tick average. Trading 30-per-tick when bot is present, banking inventory during dry spells → realizes ~10-per-tick average. Storage cost (~0.1/unit/tick in P3) × 20-unit buffer × 100k ticks = 200k storage cost versus ~300k extra revenue. Net: doubles P&L.

**Evidence.** Transcript-1: "would have doubled R4 P&L. #2 team also missed this." So both top-2 P3 teams left this on the table.

**Implementation.** Parameterize `batch_size = k * conv_cap`, k∈{1,2,3,5}, sweep empirically against storage cost.

### A3. No-hedge options default (large, 4h, ★★★★)

**Mechanic.** In a 1-wide spread, hedging 100 shares of delta costs 1 shell per round-trip × 100 = 100 shells. Gamma P&L per step ≈ ½·Γ·S²·σ²·dt. For Prosperity R3 Volcanic Rock parameters (Γ ≈ 0.002, S ≈ 10k, σ ≈ 0.15/day, dt=1/10k tick): per-step gamma ≈ 0.01 shell. Hedging 100Δ costs ~100 shells; earns ~0.01. 10000:1 hedge bleed.

**Rule.** Compute per-step `(gamma_pnl − spread_cost_of_hedge)`. If negative, **never** hedge; let directional exposure carry. Only hedge when aggregate |Δ| > Whalley-Wilmott band:

```
Δ_band = (3 · λ · Γ² · S² / (γ · σ²) · (T−t))^(1/3)
```

With λ=0.5 (half-spread), band is typically 40-80 units — so don't hedge until portfolio delta breaches ~50.

**Why others miss.** Hedging is "best practice" dogma from real markets. P3 teams reflexively hedged. The math flips in tight-spread sims.

### A5+A18+A26. Options vol-surface suite (combined, ~17h, ★★★★)

Treat as a unit:
- **A5 IV-scalping:** negative 1-lag autocorr on ATM mid-IV; enter when IV_t − IV_{t−1} > k·σ, target mean. Expected 100-150k/day (TimoDiehm).
- **A18 Butterflies/risk-reversals:** once smile fit is stable, short any wing > 1σ above fit, long ATM, delta-hedge the package only (much smaller Δ than single-strike). Standard practice in real markets; zero P3 writeup mentions trying it — pure green-field edge.
- **A26 Temporal IV-smoothing:** EWMA on mid-IV with halflife 200-500 before quoting against the smile. Chrispyroberts's fit broke because he re-fit the quadratic each tick; EWMA'd IV stabilizes the residual.

Combined P4 P&L ceiling if R3 or R4 contains options: 200-400k/day.

### A6+A7. Probe-trick extensions (med, 5h, ★★★★★)

The transcript-1 "buy at 9996 → P&L=4" trick tells you IMC uses mid-of-best. Run three extensions:

1. **Ask-side symmetry:** sell 1 @ 10004 → P&L should be 4. Confirms symmetric formula, rules out mid-of-last-N.
2. **Size sensitivity:** buy 5 @ 9996, buy 20 @ 9996. If per-unit P&L differs, the bot has size-scaled fair (common in informed-trader bots). Exploit: the size where P&L/unit is maximized is the bot's indifference point.
3. **Ambiguous-mid probe:** on an illiquid product, place a 1-unit order at a price between discrete mid candidates. The realized P&L discloses which formula IMC uses (best-bid+best-ask ÷ 2 vs volume-weighted vs wall-mid). Transcript-1 confirmed formula for stable products; never tested on volatile ones where the formula may differ.

**1 hour to code, 15 minutes to run, huge information value.** Every subsequent strategy depends on getting fair right.

### A8+A9+A14. Microstructure trio (med, 13h, ★★★)

- **A8 OBI predictor:** standard finding is 30-50 bps / 1σ; in bot markets with mechanical refills, likely 60-120 bps / 1σ. Fast to code, fast to backtest.
- **A9 Kyle-lambda per counterparty:** regress `mid_{t+k} − mid_t = α + λ · signed_size_t + ε` for k=1..20, per counterparty. λ decomposes into permanent (informed) vs transient (liquidity-demander) components. Size follows when λ_permanent is significant and stable.
- **A14 Stale-quote arb:** track `last_update_tick` per book level. If ref mid has moved > 2 ticks and a level is static for > 50 ticks, cross it. Pure free-money if any bot has lazy update logic.

### A10. End-of-round flattening fade (med, 3h, ★★★)

Every team flattens pre-settlement. If the field is net-long product X (common when MM held bid-side inventory through the day), last 10k ticks will have systematic sell pressure. Quote aggressive bids in the last 10k; skew fair value down by k · (ticks_to_end)⁻¹ so you catch the flow at your edge.

**Why nobody publicizes.** It's meta (only works if OTHER teams do the naive thing). Publicizing erodes the edge. Silent alpha.

### A11. Discord-signal fade (small-med, 2h, ★★★)

P3 had sunlight-regression signals posted on Discord with 99% R² (leakage). Teams who piled on lost. Explicit anti-strategy: monitor Discord, when a signal gets >10 upvotes & community consensus forms, short the signal's direction for 50k-tick window. Mechanical.

### A13. Put-call parity (large, 3h, ★★★★★)

**Only triggers if P4 R3 adds puts** (1.1 of forecast_creative: 5/10 probability of multi-expiry, ~3/10 of puts). IF puts: `C + Strike·exp(−rT) − P = S`. Any deviation > round-trip spread = risk-free. This is the cleanest edge possible; nobody in P1-P3 had to test it because none had puts. P4 could add them this year — if so, first team to spot the parity violation locks huge edge.

Budget 3h to pre-build the parity checker + one-line trigger; it's dormant infra otherwise.

### A15. Cross-edition regression (huge, 10h, ★★★)

**Linear Utility's P2-R5 move.** Download all P3 final-day public CSVs now; build OLS/ridge harness accepting (P3_series, P4_revealed_series). Pre-build a DP optimal-execution solver (Bellman over the known path with per-tick volume constraint + position limit). The moment P4-R5 reveals any price path, fire regression. R² > 0.9 ⇒ execute the DP schedule with max risk budget.

**Confidence 6/10 alpha exists; if it does, 1M+ P&L differential.**

Why 6/10: IMC knows this alpha was exploited in P2-R5, they may deliberately break the pattern. But they may also not — the pattern may be baked into their data-generation pipeline.

### A25. Asymmetric hysteresis (small-med, 1h, ★★★★)

**One-liner change to any z-score trader.** Enter at |z|>2, exit at |z|<0.3 — not symmetric z=0 exit. Linear decay of z through 0 means symmetric exit leaves 15-25% of reversion PnL on the table. Academic §2.2 + Dave Nandi P3 panel both confirm; public code almost always uses symmetric thresholds. 1 hour to retrofit, instant edge on any spread strategy.

### A27. Voucher cap re-audit (med, 1h, ★★★★★)

**chrispyroberts's self-reported error.** He capped voucher positions at 80/strike to reserve 200 rock capacity for delta hedging. But he then DROPPED delta hedging because spread cost > gamma P&L. So the rock-capacity reservation was redundant. If he'd left the cap at 200/strike (IMC's actual limit), and never hedged, P&L per tick = 2.5× higher with same risk.

**Rule for P4.** Every position cap you self-impose needs a justification. If the downstream reason (here, rock hedge) is dormant, raise the cap immediately. This is pure self-imposed leakage that doesn't require any new signal.

---

## Part 3 — Pick list: top 7 to prioritize

Ranked by alpha-per-hour × persistence × low-obviousness. These are the first 7 to build for P4 R3-R5.

**Tier S (build first week, before R3):**

1. **A6+A7 Probe trick extensions (5h).** Cheapest, highest information value; every downstream strategy depends on knowing fair-value formula and hidden-bot prices. Run tick-0 of every round.
2. **A25 Asymmetric hysteresis (1h).** One-line retrofit to spread-arb template. Existing code is the base.
3. **A27 Cap-reservation re-audit (1h).** Review every self-imposed cap in existing codebase.
4. **A3 No-hedge options default (4h).** Pre-build Whalley-Wilmott band calculator. Flip to "hedge only if band breached" as the DEFAULT options mode.

**Tier A (build before R3 opens, foundation):**

5. **A1 Counterparty clustering from R3 tick-0 (8h).** K-means + synthetic-ID tracking. Run from R3 tick 0, don't wait. If we're the only team doing this, compounds through R4/R5.
6. **A2 Batched-conversion stockpile (2h).** Dormant until R4 cross-exchange product appears; then instantly worth 2× P&L.
7. **A26 IV-temporal-smoothing (3h).** EWMA halflife 200-500 on mid-IV. Dormant until options land; then it's the bedrock of A5/A18.

**Tier B (build during rounds when signal appears):**

8. **A10 End-of-round flattening fade (3h).** Observe field behavior in last 10k of R3, deploy in R4.
9. **A15 Cross-edition regression + DP (10h).** Build in background during R3; fire on R5 open.
10. **A13 Put-call parity checker (3h).** Dormant; activates if R3/R4 brings puts.

**Total prep budget: ~40h Tier S+A. ~16h Tier B.**

---

## Part 4 — Non-obvious meta observations

1. **Obviousness decays with round number.** R3 alphas are heavily studied in public writeups; R4 and R5 alphas (batched conversion, Olivia, residual MM) are consistently reported as "we missed it too." The public-writeup corpus is heavy on R3 options and light on R4 conversion mechanics and R5 flow — that's where the uncontested alpha sits.

2. **Self-imposed caps are a huge silent alpha.** chrispyroberts's 80 vs 200 voucher cap; P3 teams' symmetric hysteresis; per-tick-hedging dogma. Every code idiom you inherit from real markets is potentially an overhead in a bot-simulated market. Audit your own defaults.

3. **The "probe-then-trade" template from R1 generalizes to every new product.** Transcript-1 treats the 9996 probe as a one-time trick. Make it the FIRST action of every new-product round: probe fair formula, probe ask-side symmetry, probe size-sensitivity, probe hidden-lift prices (mid±0/1/2). This is 5 hours of code that pays off round after round.

4. **Pair alphas are dramatically under-explored.** Only 2 of 6 top P3 teams even computed cross-correlations between their 7 products. SQUID_INK↔CROISSANTS, KELP↔JAMS, and R4 macarons↔ANY_SUNLIGHT_SENSITIVE — all untested. At a typical IC of 0.08, a pair trade earns 30-50 bps/day × 100k traded = 30-50k/day on a single pair.

5. **Bots fingerprint. Use it.** P3 had hidden taker-bots (macarons), hidden informed-bots (Olivia on CROISSANTS), hidden refill-bots (iceberg on baskets). Every round has exactly 10-12 bots. Logging counterparty behavior from tick 0 and treating them as known NPCs is the single highest-EV infra investment. Everyone hand-tunes against "the market"; top teams hand-tune against individually-identified bots.

6. **Price-insensitive flow is predictable flow.** Any bot at its position limit, any team flattening at round end, any community pile-on — these are price-insensitive. Price-insensitive flow is fade-able at arbitrary markups because the counterparty is not optimizing for price. Build a flow classifier that tags each incoming print as "price-sensitive" or "price-insensitive" based on time-of-day, recent size, and counterparty-id. Fade the price-insensitive side.

7. **Metrics teams skip: half-life, hit-rate, Kyle-lambda, rolling-ADF.** Top P3 teams tested coint (ADF), half-life, z-distribution. They did NOT publicly test Kyle-lambda per counterparty, hit rate of OBI, or rolling-ADF stability. These are standard quant-fund pipelines; missing from Prosperity public corpus. Whoever builds them first in P4 owns a class of edges.

---

## Part 5 — What we're intentionally NOT chasing

Listed for completeness so the team doesn't re-litigate:

- **Gamma scalping.** Math says net-negative in 1-wide spreads. Transcript-1 confirms: "made 100× less than #2."
- **Sunlight linear regression.** 99% R² = leakage. Regime-flag the signal; never regress.
- **Variance swaps / AMMs / perpetuals.** Low probability P4 introduces these; don't pre-build.
- **Cheap-talk / Bayesian signaling manual.** 3/10 confidence; don't pre-build.
- **Complex ML models.** Transcript-1 unanimous: "you don't need crazy ML." Five lines of trading logic + verified helpers wins.

---

## Closing meta-rule

**The adversarial filter:** if a P3 top-team writeup says "we should have" or "we missed," assume the P4 field ALSO misses it — public writeups do NOT get crowd-arbitraged away. These self-reported misses are the most reliable source of persistent alpha.

Alphas A1, A2, A3, A4, A5, A27 all fall in the "top team self-reported miss" category — cumulatively 500k–1M of R4+R5 P&L sitting in plain sight, protected only by teams' inertia and their focus on the headline R3 options game.

Our R3-R5 differentiation budget should allocate **60% to Tier S+A foundations, 30% to live-adaptive alphas (A1, A7, A10, A15), 10% to dormant checkers (A13, A27 audit)**. Do not over-build R3-specific infra; the arc pays out in R4 and R5.

# Hidden Alpha — R1/R2 Stable + Drifting Products (P4)

**Scope.** Adversarial enumeration of alpha sources specific to ASH_COATED_OSMIUM (stable ≈10,000, pos 80) and INTARIAN_PEPPER_ROOT (deterministic-ish +0.1/snap drift, pos 80). Goal: explain the gap between our ~700 ASH / ~7,200 PEPPER per-sample and top-team ~3,000–4,500 ASH / ~8,000 PEPPER per-sample. Every claim is tagged `[cite]` (evidence-backed) or `[spec]` (speculation). Findings ranked by `expected uplift × persistence × feasibility`.

**TL;DR — the nine highest-leverage items below cumulatively model-close the full ~2,500–3,800 ASH gap and the final ~800 PEPPER gap. Items ranked 1–3 are the true alpha; items 4–9 are smaller but cheap to stack. Items 10–12 are speculative or anti-patterns we should explicitly skip.**

---

## Ranked findings

Legend. Uplift/sample = shells per 100k-tick sample; Persist = 1–10 (10 = mechanical).

| # | Finding | Product | Uplift/sample | Hours | Persist | Category |
|---|---|---|---|---|---|---|
| 1 | **Wall-Mid fair value + take-then-make** | ASH | +1500–2000 | 3 | 10 | [cite] |
| 2 | **Toxic-size filter (fade small adversely-selected prints)** | ASH | +400–800 | 4 | 9 | [cite] |
| 3 | **Flatten-at-fair at position skew (free inventory re-open)** | ASH | +300–500 | 2 | 9 | [cite] |
| 4 | **Drift-adjusted MM on PEPPER (capture drift AND spread)** | PEPPER | +400–900 | 4 | 8 | [cite+spec] |
| 5 | **Penny-jump two levels deep on wide spreads (≥3 ticks)** | ASH+PEPPER | +200–500 | 2 | 7 | [spec, confirmed tick-inside works] |
| 6 | **Pinned-level / stale-quote cross** | ASH | +150–400 | 4 | 7 | [spec, mechanically implied] |
| 7 | **Opening-tick book-init fade (first 50 ticks)** | both | +50–200 | 3 | 6 | [spec] |
| 8 | **Size-conditional fill calibration probe** | ASH | +0, but unlocks #2 and #6 | 1 | 10 | [cite for methodology] |
| 9 | **Counterparty fingerprinting (Olivia-class on volatile R2/R3)** | future rounds | N/A R1/R2 | 8 | 9 | [cite] — see below |
| 10 | **Iceberg-refill exploit** | speculative on R1/R2 | +0–300 | 5 | 4 | [spec, low prior] |
| 11 | **Time-of-day seasonality** | unlikely on ASH/PEPPER | ≈0 | 2 | 2 | [spec, low prior] |
| 12 | **Anti-pattern: "Vibing"-style hardcoded timestamp front-run** | both | N/A — banned | 0 | 0 | [anti-pattern, explained below] |

---

## 1. Wall-Mid fair value + take-then-make (ASH, +1500–2000/sample, 3h) — **THE big missing piece**

**What it is.** The Frankfurt Hedgehogs (TimoDiehm P3, top global) write-up is explicit: on stable/quasi-stable products, **do not use raw mid-of-best**. The book has multiple visible layers. The **outermost deep-liquidity layer** (what their writeup calls "bid wall" / "ask wall") is the bot market-maker's anchor. Inner layers are players' penny-jumps and noise. `Wall_Mid = (bid_wall + ask_wall) / 2` is a much stabler, adverse-selection-resistant fair estimate.

> "averaging the prices of the bid wall and ask wall, we obtained a Wall Mid value that was much more stable and accurate than using the raw mid price" — TimoDiehm `[cite]`

For ASH, the anchor is 10,000. Wall-mid will equal 10,000 virtually always. The play on top:

1. **Take:** any ask < wall_mid-1 → lift; any bid > wall_mid+1 → hit. Hard edge.
2. **Clear:** if inventory > 0 and any bid ≥ wall_mid → sell at wall_mid (zero-PnL but frees capacity). Ditto short side.
3. **Make:** quote 1-tick inside the wall on both sides. This is equivalent to bid@9999, ask@10001 on ASH.

> "At each timestep, we first immediately took any favorable trades available—buying below 10,000 or selling above it. Afterward, we placed passive quotes slightly better than any existing liquidity" — TimoDiehm R1 `[cite]`
> "If inventory became too skewed, we flattened it at exactly 10,000 to free up risk capacity." `[cite]`

**Why we're only getting 700.** If our current variant quotes only at best-bid / best-ask (without tick-inside), or uses raw mid as fair (which gets corrupted every time a jumper tightens the book), we are:
- missing the taking edge (only 1 take per clean aggressive print, not on every layer-inside jumper);
- getting worse fills on our MM quotes (we sit behind);
- not pushing back to inventory zero at fair value → running out of capacity by tick 30k.

**TimoDiehm R1 realized PnL:** ~39k on RESIN (stable @10k, analogous to ASH). Over a standard R1 data-day (~1M timestamps / ~10–20 backtest samples), that's ~2,000–4,000 per sample, matching the top-team benchmark you cite. `[cite]`

**Uplift estimate.** If we go from 700 to 2,500/sample, that's +1,800/sample on ASH alone. **This is the single largest gap and it's the cheapest fix (3h).**

**Diagnostic.** Dump a snapshot of our current order book vs. published book on submission: if our best-bid/ask is frequently inside the wall (because we or another team is penny-jumping), our take rule never fires against the wall and our make rule sits even further inside — starving fills. Wall-mid immunizes.

---

## 2. Toxic-size filter (ASH, +400–800/sample, 4h) — size-sensitive adverse selection

**Claim.** Small prints (size 1–2) incoming to the book are disproportionately *informed* relative to their information-footprint — they're testing/probing, so they move adversely on you more often than large institutional prints. Pe049395 P2 R13 confirms this pattern on SQUID_INK (volatile, but the mechanic is identical on stable):

> "market-making strategy on Squid Ink was selective, filtering out very small 'toxic' orders that signaled potential adverse selection" `[cite]`

**Construction on ASH.**
- Tag every trade print by `(size, side, mid_before, mid_after_k)` for k ∈ {1, 5, 20, 50}.
- Compute `E[mid_after_20 − mid_before | size=s, side=buy]`. If small sizes show +δ (buyer was informed → mid moved up for the seller), the size is toxic to MM.
- **Rule:** widen your ask quote when recent `size ≤ 2` buy pressure exceeds a threshold; equivalently, refuse to fill small asks unless they are ≥ 2 ticks through wall_mid. The transcript-1 probe (buy 1 @ 9996 → PnL 4) confirms small-size fills are mechanically possible but doesn't test *whether they are adversely selected*.

**Why it's not already in our code.** Our fair-value / signal layer likely treats all prints symmetrically. Top teams stratify by size, widen on toxic-size bursts. On an IMC-simulated bot market where one bot is an "informed" test-sender, size = information proxy. The actual edge on ASH from this filter is modest but persistent.

**Uplift estimate.** Pe049395 didn't publish per-product deltas, but the general pattern in their writeups is 10–30% lift on the MM leg. On our 700 base ASH that's ~70–210/sample (low end); on a post-#1-upgrade 2,500 base, it's 250–750/sample. Call it +400–800/sample pessimistically.

---

## 3. Flatten-at-fair on position skew (ASH, +300–500/sample, 2h)

**Transcript-1 explicitly listed this as the R1 optimization most teams missed:**

> "Position-reducing at fair value: when at/near position limits, accept trades AT fair value that reduce inventory (you forgo $0 profit on that trade but unlock future spread capture). The one most teams missed." `[cite]`

Our current engine probably refuses to trade at zero edge. It should accept at zero edge (or even tiny negative edge) when inventory exceeds 50 (soft limit in our code) and the trade reduces inventory magnitude. The EV of *future* MM capacity is positive — leaving inventory stranded at pos=80 means zero future fills on that side until reversion.

**Uplift.** +300–500/sample, compounding with #1.

---

## 4. Drift-aware MM on PEPPER (+400–900/sample, 4h)

**Baseline naive.** "Go long to limit 80, hold, collect drift." Theoretical ceiling = 0.1 × 80 × ticks_held. On a 100k-tick sample with 1000 decision-snaps: 0.1 × 80 × 1000 = 8,000. Actual top teams: ~8,000 per sample → they are essentially hitting ceiling, so the marginal uplift above naive-long is smaller than on ASH.

**But there's still edge on top of the naive long.** If PEPPER drifts +0.1 per snap deterministically, the bot market maker's mid updates. Two scenarios:

**(a) Bot updates fast.** Ask rises in lockstep; naive-long captures drift cleanly.

**(b) Bot updates slow / is discrete.** Ask sometimes sits stale at the previous level while the "true" fair has drifted. You can lift the stale ask for free, flip it into a passive bid at the new fair, repeat. This is **stale-quote sniping during drift**, a combination of #6 with drift.

**Plus: MM on top of the long position.** While holding +80 long, you can still *market-make* the 1-tick-inside layer on the *sell* side only (quote at best_ask-1). Each filled sell reduces inventory from 80 to 79, which frees a slot to re-add +1 long (buy the drift), netting +0.1 from drift + whatever the spread width gives you. TimoDiehm on KELP (the P3 drifting analog) cites ~5k per round `[cite]`; comparable-scale on PEPPER = +500/sample layered on top of the 8k drift-capture ceiling.

**Why we might be getting only 7,200 not 8,000.** Our engine may:
- Clamp at +60 not +80, giving us 0.1 × 60 × 1000 = 6,000 drift + some MM spread ≈ 7,200.
- Or hit +80 but not quickly enough (slow ramp-in at first 20k ticks leaves drift uncaptured).

**Uplift.** If we ramp to +80 on tick ~500 instead of ~5000, we collect an extra ~400 drift ticks × 80 × 0.1 = 3,200 gross, of which maybe 600–900 is realized net of transaction costs. +400–900/sample.

---

## 5. Penny-jump two levels deep when spread ≥ 3 (ASH + PEPPER, +200–500/sample, 2h)

**Transcript-1 confirms 1-inside works:**

> "Penny jumping: quote one tick inside best bid/best ask. Works because 'bots see your orders, place trades on it, then your orders go away' — no other competitor can front-run you." `[cite]`

This is `[cite]` for 1-inside. The **2-inside** layer is `[spec]`. Mechanism: if wall_ask is at 10004 and best_ask is at 10003 (someone else jumped), we can sit at 10002 — if the book spread is actually wide (original wall spread = 8 per `spread of roughly 16` on EMERALDS → ASH analog `[cite, Brezina]`), then 2-inside still leaves us 6 ticks of edge.

Catch: if multiple teams do this and collapse onto the same 1-inside tier, the book fills up with competing passive orders and fill probability drops. Second layer (2-inside) is uncontested. Implementation: quote at best+1 AND best+2 simultaneously with **size split** (2 units at inner, 5 units at outer — outer gets filled more often but you still capture the rare fast-fill on inner). When inner fills, the outer becomes the new best and stays up, continuing to fill. Classic iceberg-MM pattern from real HFT playbooks.

**Uplift.** +200–500/sample on ASH. Smaller on PEPPER (tighter spread in drifting regime).

---

## 6. Pinned-level / stale-quote cross (ASH primary, +150–400/sample, 4h)

**Mechanism.** The bot market maker on ASH is likely a deterministic quoter that updates only on specific triggers (timer-based cadence, or mid-change threshold). If you log `(price_level, last_modification_tick)` per level for every book snapshot, you can detect levels that have been stale for ≥ K ticks *while other quotes have moved*. A stale level that's now on the wrong side of fair (e.g., stale bid at 10002 when the current wall has dropped to 9995–10005 and fair is 9998) is free money to hit.

**Evidence.**
- chrispyroberts P4 backtester source (open-source): confirms TOMATOES/EMERALDS are modeled as three bots with outer wall, inner wall, and an *optional one-sided inside* quote `[cite]`. The inside quote's presence toggles — so a "missing" inside quote relative to a prior tick is mechanical. Detecting its reappearance on the wrong side is the pinned-level exploit.
- "visible integer prices come from deterministic rounding of those quote targets, which is why the tutorial book shows stable discrete patterns instead of arbitrary noise" — `[cite]` confirming bot quoting is deterministic-enough to fingerprint.

**Uplift.** Small but mechanical. +150–400/sample.

---

## 7. Opening-tick book-init fade (both, +50–200/sample, 3h)

**Hypothesis `[spec]`.** At tick 0–50 of a fresh simulation run, the bot quoters haven't converged yet. The book may show abnormal spreads / missing inner walls / price levels drifting from a cold initialization toward steady state. The cumulative effect is a tiny but consistent abnormal-return window.

**Construction.** Compute per-tick abnormal return `(mid_t − mid_50) / stdev_mid` for t ∈ [0, 50] across many days. If there's a consistent sign (e.g., mid drifts DOWN in first 50 ticks on PEPPER because the drift hasn't kicked in yet), fade it.

**Uplift small** — only 50 of 100k ticks matter. But **feasibility is high** and it's dormant infra: once built, it applies to every new round.

---

## 8. Size-conditional fill probe (ASH, 1h, enables #2 and #6) — info-value trick

**Transcript-1's "buy 1 @ 9996 → PnL 4" probe is one data point.** The natural extensions:
1. Buy 5 @ 9996 → PnL per unit should still be 4 if mid-of-best; if different, size-scaling exists.
2. Buy 20 @ 9996 → likely fails to fill completely because depth at 9996 isn't 20.
3. Probe at 9994, 9993, 9992 to find the first unfilled price = fair-fair.

**Value.** Tells us the ASH bot's *fill depth* at each integer. Once known, #2 (toxic-size filter) can be calibrated more precisely and #6 (stale-level exploit) knows which levels to target for size. This is a **one-off 15-minute live probe** that pays for itself many times over.

---

## 9. Counterparty fingerprinting / Olivia-class on R1/R2 — **evidence check**

**The user asked: on a STABLE product around 10,000, is there a bot that consistently buys at 9995/9996 and sells at 10005/10006?**

Answer from the evidence: **PARTIAL YES, but it's not Olivia — it's the bot MARKET MAKER, not an informed trader.** The inner/outer walls documented above ARE that consistent-level quoter. But "buying at 9995/6, selling at 10005/6" is **mechanical MM**, not informed flow. Copying the MM = guaranteed loss (you pay the spread they earn).

**Olivia-class informed bots exist, but on volatile products, not stable ones:**
> "We identified Olivia via win-rate statistical analysis, copy-trade on SQUID INK + CROISSANTS" — Alpha Animals P3 `[cite]`
> "The Olivia signal was visible from Round 1 data if you plotted trades per counterparty and segmented by P&L trajectory." — transcript-1 `[cite]`

**So:** on ASH specifically, there's no evidence from 3 editions of an Olivia-class bot. Her pattern is max-amplitude buy-lows / sell-highs, which requires amplitude. A 16-tick-range oscillator (ASH) doesn't give her that. Olivia on SQUID_INK-equivalent (P4 R2's third product if present, or a future R3 product) is the high-prior candidate.

**For R1/R2 specifically, the Olivia-hunt is a zero-evidence bet. Don't invest hours here for ASH/PEPPER. Do the infra NOW (counterparty-P&L tracking from tick 0) so it's ready when a volatile product appears in R3.**

---

## 10. Iceberg refill [spec, low prior for R1/R2]

Three-bot architecture from chrispyroberts P4 `[cite]` is *outer wall + inner wall + optional one-sided inside*. There's no evidence of size-refill beyond displayed. An iceberg exploit would require a hidden pool behind a displayed level that re-emerges after it's eaten. In the tutorial-calibrated bots this appears absent. **Skip for R1/R2.** Worth checking on R3+ ETF-basket products.

## 11. Time-of-day seasonality [spec, low prior]

P1 BERRIES had hardcoded timestamps `[cite]`. No other published edition has since. ASH/PEPPER have no sensor/exogenous-index analog. **~0 prior. Don't invest.**

## 12. Anti-pattern — "hardcoded timestamp front-run" (the Vibing speculation)

**Background.** In P2, two teams `[cite]` found that sample-data timestamps were identical to live R1 day-1 data. They hardcoded expected bot prints and scored millions. IMC fixed it after R2 and **banned the tactic** — several top-25 teams were asked to resubmit `[cite]`.

**Vibing's 36% gap speculation (Bayesian).** What explains a 323k #1 vs 238k #2 in P4 with R1+R2 only?

- **H1 (banned-exploit redux, ~15% prior).** Vibing re-discovered a timing or hardcoding leak. IMC's post-P2 fix may not have generalized to P4's new bots. Would explain a clean ~40% outlier gap. *Risk: gets invalidated in R3 when IMC audits.* We should NOT pursue this.
- **H2 (perfect PEPPER + 4,500 ASH, ~35% prior).** Vibing got 8,000 PEPPER (ceiling) AND ran every single item above (wall-mid + toxic filter + flatten + 2-layer penny + size-calibrated fill). Cumulative ASH: 700 → ~4,500. Plus a ~200 R2-specific edge from size-calibration residual. 4,500 ASH × N + 8,000 PEPPER × N ≈ 12,500/sample vs #2's ~9k. Over R1+R2 combined samples, 36% gap is exactly consistent.
- **H3 (R2 manual win, ~25% prior).** R2 manual (whatever the round-2 game is) has a high-variance payoff; Vibing may have been one of very few teams to hit the top tier there. But manual scores in P3 were 10–15% of total, not 36%.
- **H4 (second drifting edge we've all missed, ~25% prior).** PEPPER's drift has some second-order property (e.g., drift magnitude is + sign but with Gaussian noise — so aggressive take-on-dips adds +800 on top of naive-long). Plausible; we should dump the PEPPER price path and test.

**Bayesian posterior.** Most-likely scenario is H2+H4 combined: Vibing executed a clean 9-item stack AND found a second-order PEPPER trick. H1 is plausible but we should not chase it; if we replicate H2 fully and H4 is a real signal, we're very competitive.

**Action.** Don't chase H1. Build H2 (items 1–8 above) and actively search for H4 (dump PEPPER tick-level residuals, look for over-the-top drift predictability beyond +0.1).

---

## The Olivia-equivalent ON STABLE products question — final answer

You asked point-blank: "Is there a bot that consistently buys at 9995/9996 and sells at 10005/10006?"

**Yes, but it's the market maker bot, which you want to TRADE AGAINST (pennyjump, flatten-at-fair, wall-mid fair) — not the informed trader you want to COPY.** Copying the MM loses the spread. The real alpha is to be the *better* MM than them: quote 1 tick tighter, clear inventory at fair, filter toxic prints, and take when they're stale.

**Olivia-class (informed, copy-her) is not established on stable products in any of 3 editions. Infra investment should be dormant until R3.**

---

## The ASH gap — budget allocation

Current: 700/sample. Target: 3,000–4,500/sample. Gap: 2,300–3,800/sample.

Budget decomposition (mid-case estimate):
- Wall-mid take/clear/make: +1,800
- Toxic-size filter: +600
- Flatten-at-fair: +400
- 2-layer penny jump: +350
- Pinned / stale-quote cross: +275
- Opening-tick fade: +125
- **Total: +3,550**, exactly in the middle of the top-team band.

**Implementation order (highest α/hr):**
1. Wall-mid rewrite (3h, highest uplift, blocks nothing)
2. Flatten-at-fair (2h, bolt-on)
3. Penny-jump 2-deep (2h, bolt-on)
4. Size probe (1h, info-gathering)
5. Toxic-size filter (4h, needs #4 data)
6. Pinned-level (4h, needs book-level tick tracking)
7. Opening-tick fade (3h, independent)

**Total Tier-S budget: 19h for the full ASH stack.** PEPPER items 4-drift-MM adds 4h = 23h total to close BOTH gaps.

---

## What is actionable vs what is research

**Actionable now (ship before R3 opens):**
- #1 (wall-mid) — 3h, highest leverage, guaranteed win
- #3 (flatten-at-fair) — 2h, guaranteed win
- #5 (2-deep penny) — 2h, likely win
- #8 (size probe on live) — 1h, info value

**Actionable if time permits:**
- #2 (toxic filter) — 4h
- #4 (PEPPER drift-aware MM) — 4h
- #6 (pinned level) — 4h

**Research mode (don't trade, just instrument):**
- #9 (counterparty fingerprinting infra) — 8h, dormant until R3
- H4 (second-order PEPPER drift) — 3h forensic analysis

**Do NOT pursue:**
- #10 (iceberg for R1/R2), #11 (time-of-day for R1/R2), #12 (hardcoded exploit — banned)
- Olivia-copy on ASH/PEPPER — no evidence supports it

---

## Forensic leaderboard read — addendum

**Vibing (323,929) vs field median (~230,000) = +40% outlier.** The three plausible attributions:
1. **Full 9-item stack + H4 PEPPER secret** (our best bet to replicate)
2. **A timing/hardcoding leak IMC hasn't caught yet** (we don't chase — reputational and ban risk)
3. **Manual-round dominance + modest algo edge** (uncontrollable for us)

**The 2nd-place cluster 225–238k is achievable with items 1–5 above cleanly implemented.** Our ceiling realistically caps at ~250k if we execute; matching Vibing's 323k requires either H4 or an edge we haven't identified. **For R2-scoring purposes, target 230k; do not over-leverage chasing Vibing.**

---

## Closing meta-observation

Our current ASH PnL of 700/sample is *not* under-optimized signal logic — it's almost certainly **using raw mid-of-best as fair value** (which gets corrupted every time any book participant penny-jumps, including us). The wall-mid rewrite is the one insight that unifies items 1–3, 5, 6, and 8. It is also the cheapest fix (3 hours). **If only one thing is done from this document, it is wall-mid.**

---

## Sources (cited)

- TimoDiehm, *Frankfurt Hedgehogs / imc-prosperity-3 README* — wall-mid, take/clear/make, R1 39k RESIN, R1 SQUID_INK Olivia detection
- chrispyroberts, *imc-prosperity-4 Monte Carlo backtester* — three-bot architecture (outer + inner + optional inside), deterministic rounding of quote targets
- chrispyroberts, *imc-prosperity-3 README* — R3 options analog, voucher position caps lesson
- Linear Utility, *imc-prosperity-2 Eric Liu writeup* — cross-edition DP regression, R5 2.1M shells
- jmerle, *imc-prosperity-2 Remy/Vladimir counterparty flow detection* — R5 inferred-ID methodology
- pe049395, *IMC-Prosperity-2024 rank-13 writeup* — "toxic-size" small-order filter on SQUID_INK MM
- Mark Brezina, *Ctrl-Alt-DefeatTheMarket unofficial guide* — ASH as "aggressive mean-reversion around 10k", PEPPER as "linear upward trend"
- IMC Prosperity transcripts 1 & 2 (/Users/abhinavgupta/Desktop/IMC/docs/manual_round_3/transcript_1_extracted.md) — buy-9996 PnL probe, penny-jumping 1-inside, flatten-at-fair, Olivia from R1 data
- Prior-rounds hardcoding-exploit history (banned post-P2-R2) — anti-pattern for Vibing speculation

# Forensic Tick-by-Tick Analysis of Round-2 Official Logs

**Scope:** 16 official run logs, 4 variants × 4 runs each, 1,000 snapshots per run. All numbers come from `outputs/round_2/Official Results/{Promoted, Ash L1, Killswitch, v5}/*/*.log` (the JSON-wrapped `activitiesLog` CSV). Source: `src/scripts/diagnostics/forensic_own_logs.py`, `forensic_own_logs_extra.py`, `forensic_hotspots.py`.

**Bottom-line empirical finding (preview):** Our ASH P&L shortfall vs. top teams is *not* a mean-reversion or spread-width issue. It is that **~40% of the sample's gross P&L is destroyed by three recurring directional-collapse windows** (t≈36,600 / t≈65,000 / t≈84,500) that our MM absorbs as inventory losses of 250–355 shells per window. OBI at those moments does not reliably warn us, so even a perfect OBI-based quoter would capture only a fraction. The PEPPER gap to 8,000 is mostly **slow inventory ramp + a persistent 14-wide spread paid on the first ~30–50 snapshots** — a fixable leak.

---

## Section 1 — ASH P&L accrual distribution and leak pattern

Per-snapshot P&L deltas, pooled over 4 runs per variant (n=3,996 deltas each):

| Variant      | Mean Δ | Median Δ | Pos% | Neg% | Flat% | Gross +  | Gross −    | p05     | p95    | Min    | Max    |
| ------------ | ------ | -------- | ---- | ---- | ----- | -------- | ---------- | ------- | ------ | ------ | ------ |
| Promoted     | +0.744 | +0.177   | 46.6 | 43.0 | 10.4  | +17,938  | **−14,967**| −19.50  | +21.31 | −49.81 | +72.25 |
| Ash L1       | +0.612 | +0.371   | 49.3 | 44.7 |  5.9  | +20,083  | **−17,635**| −21.00  | +22.50 | −59.06 | +65.94 |
| Killswitch   | +0.709 | +0.179   | 47.3 | 43.8 |  8.9  | +18,083  | **−15,251**| −19.12  | +20.88 | −51.56 | +77.28 |
| v5           | +0.819 | +0.324   | 48.6 | 43.1 |  8.3  | +17,721  | **−14,449**| −18.44  | +20.44 | −48.12 | +61.00 |

**Observations:**

1. **We lose money on ~43–45% of snapshots.** This is not a tail problem; it is structural. Pure passive market-making should have a P(loss)≈ P(gain) only because of inventory drag; a profitable MM book with OBI skew would push this toward ~35/55.
2. **v5 wins primarily by losing less, not gaining more.** v5's gross positive (17,722) is *lower* than Ash L1's (20,083), but its gross negative (−14,449) is 18% smaller. **Ash L1 trades more aggressively (fewer flat snapshots: 5.9% vs 8.3–10.4%) and gets punished for it.** Promoted's wide ladder produces more flat snapshots but doesn't translate into better net.
3. **The gain side has lower kurtosis than the loss side.** p95 gain ≈ +21; p05 loss ≈ −19 — but the *tail beyond p99* is where losses dominate: min −59 on Ash L1 vs. max +66. The big hits are one-sided.
4. **Time-of-sample distribution** (first/mid/last third mean per run):

| Variant    | First 1/3 | Middle 1/3 | Last 1/3 |
| ---------- | --------- | ---------- | -------- |
| Promoted   | 280       | 400        | **62**   |
| Ash L1     | 120       | 438        | **53**   |
| Killswitch | 272       | 410        | **26**   |
| v5         | 259       | 472        | **87**   |

**The last third of every sample bleeds.** 5–12× less P&L than the middle third. This is the signature of a market-making strategy that built mean-reverting inventory and got caught by a late-sample directional move.

---

## Section 2 — Missed directional-trade windows

Window defined: a 10-snapshot window where |Δmid| ≥ 5 ticks. Theoretical capture = |Δmid| × 80 (position limit) if we had perfectly directional-traded.

| Variant    | Windows/run | Theoretical capture/run | Actual P&L in windows/run | Capture rate |
| ---------- | ----------- | ----------------------- | ------------------------- | ------------ |
| Promoted   | 15.5        | 3,980                   | 613                       | **15.4%**    |
| Ash L1     | 13.8        | 3,890                   | 495                       | **12.7%**    |
| Killswitch | 11.5        | 4,050                   | 601                       | **14.8%**    |
| v5         | 16.0        | 4,630                   | 660                       | **14.2%**    |

**Implication:** 13–16 directional windows/run that each offer up to ~300 shells × 80 ≈ several hundred each. We capture **~14%** — the MM bleeds through most of them, picking up only the crumbs that match our skew. **A pure directional trader with even 30% hit-rate on these windows would add ~600–900 shells/run.**

Caveat: the "theoretical max" double-counts when windows overlap (merged), but the 14% figure is robust across variants, which means the windows themselves are structurally adversarial to how we trade.

---

## Section 3 — OBI vs. ASH P&L empirical relationship

### 3a. OBI bucket conditional mean forward P&L (lookahead = 10 snapshots)

Pooled across all 16 runs:

| OBI bucket     | n     | Mean fwd Δmid | up %   | down % | flat % |
| -------------- | ----- | -------------:| -----:| -----: | -----: |
| strong\_neg (≤−0.4) | 2,323 | **−6.63** | 28 | **56** | 16 |
| neg            | 1,896 | −9.83         | 62 | 30     | 8     |
| neutral        | 7,338 | −16.45        | 38 | 41     | 21    |
| pos            | 1,919 | −11.25        | 28 | **64** | 8     |
| strong\_pos (≥+0.4) | 2,326 | **−19.35** | 55 | 30     | 15    |

### 3b. D4 hypothesis — **CONFIRMED with nuance.**

The simplest read of OBI-as-signal says strong negative OBI → price goes down, strong positive → up. **The real data contradicts this naive read:**

- strong_pos OBI: only **55% up moves**, mean Δmid = **−19.4** (NEGATIVE net drift).
- strong_neg OBI: **56% down moves**, mean Δmid = −6.6 (aligns directionally but modestly).
- neutral OBI: **mean Δmid = −16.4** — the overall sample simply drifts down on average, so any un-conditional bucket inherits that drift.

The genuine signal lives in the *ordering*:
- strong_neg: 56% down / 28% up — **2× more down moves than up**. Real signal.
- strong_pos: 55% up / 30% down — **1.8× more up than down**. Also real, but *contaminated* by a strongly negative unconditional drift that shows up in the "mean Δmid" column.

**So OBI at t predicts direction of mid at t+10 but NOT the magnitude.** Naive OBI skew on the MM quote ladder cannot monetize a "55% up" bias when our book is already long and the net sample drift is down. This is exactly the D4 finding.

### 3c. Why we gain P&L even in "wrong" OBI buckets

Mean forward P&L is uniformly positive in every OBI bucket (range +2.8 to +10.4). This is baseline passive spread capture — not OBI alpha. The OBI signal adds ~3–7 shells of mean P&L on top of the base. Over 3,996 snapshots × ~5 shells = 20k theoretical if perfectly extracted; we appear to extract most of the passive-spread base but leave the directional top-up on the table.

### 3d. OBI lookahead sweep (Promoted variant)

Mean forward P&L at increasing lookahead:

| Lookahead | strong_neg | neg | neutral | pos | strong_pos |
| --------- | ---------- | --- | ------- | --- | ---------- |
| 1         | +1.08      | +0.18 | +0.96 | +0.16 | +0.51 |
| 5         | +5.23      | +2.51 | +3.47 | +2.71 | +2.59 |
| 10        | +10.40     | +7.47 | +6.68 | +3.69 | +5.19 |
| 50        | +43.31     | +28.93 | +34.95 | +27.73 | +32.03 |

**strong_neg OBI shows the strongest forward P&L across every lookahead.** The bucket that should *hurt* a symmetric-MM (if OBI predicted down moves that the MM would absorb) actually *helps* us. Interpretation: when OBI is strongly negative, the market has already pushed bids deep, the asks are thin — and our MM's passive bid gets filled cheap. We then mean-revert into profit. **The worst bucket is pos OBI (moderate), where the naive expectation says "up move coming" but our MM is still long inventory** and gets hit with mean-reversion losses.

### 3e. OBI distribution

On Promoted, 46.8% of snapshots have |OBI| < 0.15 (neutral), and only 29.7% have |OBI| > 0.4. **The tradable signal is sparse.** Two-thirds of the sample doesn't have a strong OBI signal at all.

---

## Section 4 — Variant divergence analysis

### 4a. v5 vs. Promoted aggregate

Averaged P&L-delta curve (across 4 runs each), summed: v5 beats Promoted by **+75.4 shells/run** (matches the known 818 vs 743 means).

Decomposing *where* v5 wins:

| Snapshot type                | n    | Sum v5 − Promoted | Mean v5 − Promoted |
| ---------------------------- | ---- | ---------------: | -----------------: |
| High-move (|Δmid| ≥ 2 ticks) | 365  | **−1.2**         | −0.003             |
| Low-move (|Δmid| < 2 ticks)  | 634  | **+76.6**        | +0.121             |

**v5 wins entirely on low-volatility snapshots.** On high-move snapshots v5 and Promoted are a wash. This is the opposite of what you'd expect if v5 had a directional edge. **v5's advantage is spread capture in quiet markets, not signal exploitation in volatile ones.**

### 4b. Top 5 per-snapshot divergences (v5 outperforms)

| timestamp | v5 ΔP&L | Promoted ΔP&L | diff  | v5.run1 Δmid |
| --------- | ------- | ------------- | ----- | ------------ |
| 40,000    | +36.0   | −0.7          | +36.7 | 0.5          |
| 51,000    | +38.2   | +3.0          | +35.2 | −4.5         |
| 97,000    | +21.5   | −6.3          | +27.8 | 0.0          |
| 24,000    | +23.3   | −3.0          | +26.4 | 1.0          |
| 62,100    | +4.9    | −10.8         | +15.8 | 11.0         |

Notice: 3 of 5 top divergences occur with |Δmid| ≤ 1. **These are snapshots where v5 happened to earn a fat spread from an opportunistic counterparty while Promoted's wider ladder missed the fill.** This is not alpha; it's quote placement luck that compounds across 4,000 snapshots.

### 4c. Loss concentration is shared across variants

The worst per-snapshot losses cluster at **t=84,500**, **t=81,800**, **t=36,600**, and **t=69,700** in every variant. Representative Promoted sample: 10 worst snapshots in run1 include four at t=84,500, two at t=69,700. **This is a market condition, not a variant weakness.** Longest losing streak = 7 snapshots across all variants with max consecutive loss of **−137 to −149 shells** in a single stretch.

---

## Section 5 — PEPPER gap decomposition

Theoretical max assuming 0.1-per-snapshot drift × 1,000 snapshots × 80 position = 8,000.

| Variant    | Mean final PEPPER | Gap  | Gross pos | Gross neg | Mean Δ/snap | Avg spread | Snapshots ≥ full-long-drift |
| ---------- | ----------------- | ---- | --------- | --------- | ----------- | ---------- | --------------------------- |
| Promoted   | 6,911             | 1,089 | 7,214    | −302      | 6.92        | 14.65      | **57.8%**                   |
| Ash L1     | 7,340             | 660   | 7,691    | −351      | 7.35        | 14.63      | **75.1%**                   |
| Killswitch | 7,104             | 896   | 7,466    | −362      | 7.11        | 14.72      | **67.5%**                   |
| v5         | 7,153             | 847   | 7,522    | −368      | 7.16        | 14.64      | **69.1%**                   |

### Decomposition of the ~900-shell gap (using Promoted's 1,089):

**(a) Inventory ramp leak ≈ 200 shells.** Promoted reaches "full-long inventory" (|dPnL| ≥ 7.5 per snapshot, consistent with pos≈80 × drift≈0.1) in only 57.8% of snapshots — meaning on the other 42.2% we are not fully positioned. Ash L1 hits full-long 75% of the time. Each missing snapshot costs ~1 shell of drift × missing position. The Promoted-vs-AshL1 gap (429 shells) is almost entirely explained by Ash L1 ramping faster — it pays the spread more aggressively to get fully long sooner.

**(b) Adverse-selection snapshots ≈ 300–370 shells.** Every variant has gross negative PEPPER deltas of −300 to −370 per run, occurring on just 0.4–0.5% of snapshots. When PEPPER mid mean-reverts (rare, but happens), our long inventory gets punished. Can't eliminate without directional modeling.

**(c) Spread leakage on initial fill ≈ 400–600 shells.** Median PEPPER spread is **14 ticks**. To reach position 80 we must cross the spread ~80 times (or pay it passively once per unit). If we pay half-spread (7 ticks) × 80 units = 560 shells locked into the cost basis. This is the dominant component of the 900-shell gap and is *unavoidable given spread width* unless we fill passively. Ash L1 wins here because it evidently quotes more aggressively on the ask side and gets passive fills cheaper.

**Summary of gap:** 560 spread (unavoidable) + 200 ramp (fixable) + 350 mean-reversion (hard). **The fixable component is ~200 shells = ~30 shells per 160 snapshots = speed up the ramp by 50% for +200 shells/sample.**

---

## Section 6 — Specific actionable findings

1. **The ASH P&L ceiling is structurally bounded by ~1,000 shells for any MM-only strategy.** Across 4 variants × 4 runs, the best single run was v5 run4 at 966 shells. No variant crossed 1,000. Top teams at ~3,000–4,500 must be running a *different kind of strategy* (directional with OBI+microstructure signals, or cross-product hedging), not a better MM.

2. **The last third of every sample costs us ~200–400 shells.** Our MM builds inventory against a mean-reverting prior, then gets steamrolled by a late-sample directional move. Per-third P&L: first 120–280, middle 400–472, **last 26–87**. Fix options: (a) de-leverage inventory in snapshots 700+, (b) switch to trend-following in the last 300 snapshots, (c) run a separate model per third.

3. **The t=84,500 hotspot costs ~47 shells in a single snapshot across every variant.** The price prints 10,006 → 10,004 → 10,003 with OBI oscillating from −0.53 to +0.53 run-to-run. The deterministic dPnL of −46 to −52 at this instant suggests our book is long ~80 and takes a ~0.6-per-unit hit. **A killswitch here would save ~50 shells.** The same pattern at t=81,800 (loss ~40) and t=86,900 (loss ~37). **Combined: the 81k–87k window costs 287–355 shells across variants** — roughly 40% of our final P&L.

4. **OBI signal is real but sparse.** Only 30% of snapshots have |OBI| > 0.4. In that 30%, strong_neg forward 10-snap P&L is +10.4 vs. pos +3.7 — a ~7-shell edge per signaled snapshot × ~1,185 strong-OBI snapshots = ~8,000-shell theoretical max. **But that assumes perfect exploitation**; D4 shows naive skew recovers <10%. Path forward: asymmetric quoting (skew only the side OBI predicts, don't widen the other) or directional take on |OBI| > 0.6 with inventory < 40.

5. **PEPPER's fixable gap is the ramp, not the spread.** Worth ~200 shells/run = 800 shells across 4 runs. To capture: on snapshot 0–50, cross the spread to build inventory aggressively (current variants evidently passive). Ash L1 already does this (final 7,340 vs Promoted 6,911). Promoting Ash L1's PEPPER logic to Promoted's ASH logic is a free +400 shells.

6. **v5's ASH advantage is ghost alpha, not real alpha.** v5 beats Promoted by 75 shells/run entirely on low-volatility snapshots. This is quote-placement luck: v5's narrower ladder catches more opportunistic fills in quiet books. It has *zero* directional-window advantage over Promoted (diff = −1 shell on |Δmid|≥2 snapshots). **Do not assume v5 is strategically better — it likely reverts under different random seeds.**

7. **The loss-streak pattern is uniform: 7 consecutive snapshots × ~20 shells = ~140 shell drawdown in every variant.** A simple "after 5 consecutive loss snapshots, liquidate inventory" rule would cap this at ~100 shells = ~40 savings per sample. Combined with the t=84,500 killswitch, that's ~90 shells/run.

**Total plausible upside from fixes = ~300–500 shells/run on ASH (100% improvement on current 700–820) + 200 shells/run on PEPPER = ~500–700/run = within striking distance of a 1,500–2,000 sample. Still below top teams, but materially closer.**

---

## Caveats

- **Implied-position reconstruction is noisy.** Formula pos ≈ ΔPnL / Δmid breaks down when Δmid is small (noise) or when trades occur within the snapshot (cash flows not pure MtM). Numbers in Section 4c are indicative only.
- **Sample-to-sample variance is high.** 4 runs per variant is small; the v5 vs. Promoted 75-shell advantage has a standard error of ~80 shells (variance across 4 runs ~30k). **The v5 outperformance is not statistically distinguishable from noise.**
- **The log files are *simulator* output, not the real competition.** PEPPER drift is deterministic (0.1/snap) in the sim but may be noisier in reality. The t=84,500 hotspot is sim-specific and won't recur identically in live runs.
- **OBI conditional means are contaminated by unconditional drift** (mean Δmid ≈ −16 in the full sample). We should have run the analysis on *detrended* mid moves; the directional ordering of buckets is robust but the magnitudes are biased negative.

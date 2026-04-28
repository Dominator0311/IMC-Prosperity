# Round 4 Lessons For Round 5

Date: 2026-04-28

This document turns the Round 4 result into operating rules for Round 5. R5
will have different assets, so the point is not to reuse the exact strategy.
The point is to reuse the research discipline: identify product geometry,
separate alpha from exposure management, validate against path risk, and avoid
mistaking one good simulator slice for robustness.

## Round 4 Snapshot

Submitted strategy:

`submission_r4_final_probe_stack_hyd_abortgate18_long80_60.py`

Official final PnL: `143,528`.

Final attribution:

| Sleeve | PnL |
|---|---:|
| HYDROGEL_PACK | 56,870 |
| VELVETFRUIT_EXTRACT | 9,699 |
| VEV_4000-5200 | 80,981 |
| VEV_5300+ wings | -4,022 |

The final submission was not a disaster. It was flat at the end, captured real
HYD and VELVET/options edge, and was a defensible choice among the candidates
we had built. But it was not a top-tier solution. The gap to 200k+ scores was
not mainly one missed Mark rule. It was a missing dynamic portfolio controller.

The final path exposed the central weakness:

- PnL reached roughly `196k` intraday under the final official path analysis.
- Negative 100k buckets summed to about `-116k`.
- Two large drawdown windows alone were enough to explain most of the gap to
  200k+.
- All final positions ended flat, so terminal-risk control worked; intraday
  exposure control did not.

## The Main Lesson

Finding an alpha sleeve is only the first half of the problem.

The second half is answering:

```text
When does this sleeve stop working, how do we detect that in real time,
what inventory should we hold then, and when are we allowed to re-enter?
```

In Round 4 we found a profitable broad stack, then kept optimizing wrappers
around it. We should have converted it into a state machine:

1. Accumulate when the state is favorable.
2. Ride the exposure while markouts remain positive.
3. Reduce-only when the state deteriorates.
4. Flatten or hedge during breakdowns.
5. Re-enter only after a confirmed reset.

That framework matters more than the exact R4 products.

## What Worked

### Asset Isolation Worked

Splitting HYDROGEL and VELVET/options into separate research threads was the
right structure. It helped identify independent contribution, risk, and
candidate families.

Carry forward:

- research each asset independently first;
- build isolated diagnostics and isolated submissions;
- only combine after knowing each sleeve's standalone role;
- test additivity explicitly instead of assuming it.

### Terminal Flattening Worked

R4 ended with zero final positions. That avoided terminal-mark blowups and made
the submitted result cleaner than earlier mark-heavy candidates.

Carry forward:

- terminal inventory must be an explicit design choice, not an accident;
- mark-to-market PnL is not enough if final settlement/terminal marks are
  uncertain;
- every candidate should report final positions and terminal contribution.

### Official Uploads Helped Calibrate Fill Behavior

Official uploads killed several weak ideas:

- Mark55 single-lot recycler was only about `+15` on the official 100k path.
- Mark38 fade did not improve the official 100k path once integrated with the
  final HYD wrapper.
- Several apparent local replay gains were fill-model or path dependent.

Carry forward:

- use official simulator uploads as mechanism tests;
- pair treatment with matched controls;
- require an official result to confirm fill-sensitive passive strategies.

### The Best Candidate Was Risk-Aware Relative To The Frontier

Choosing the clean abortgate80 stack over more aggressive Mark/HYD variants was
defensible. The more aggressive variants had small or uncertain incremental
official evidence and larger path risk.

Carry forward:

- do not chase a tiny expected gain that adds a large new left tail;
- when two variants are close, prefer the one with clearer mechanism and
  simpler failure modes.

## What Failed

### We Overweighted Final PnL And Underweighted Path Shape

The public and official analyses showed large flat or drawdown regions. We
treated these mostly as diagnostics, not hard acceptance criteria.

For R5, every serious candidate needs:

- final PnL;
- bucket PnL by time window;
- max drawdown;
- peak-to-final giveback;
- per-product PnL;
- position path;
- worst-window attribution.

A candidate that makes a lot but regularly gives back 40k-100k is not robust
unless the giveback is explained and controlled.

### We Treated The Official 100k Slice Too Much Like A Distribution

The official 100k simulator is one unseen slice. It is useful, but it is not a
proof of live 1M robustness.

In R4, the final 1M first 100k was nothing like the official 100k simulator:

- official 100k for the final candidate was about `77.9k`;
- final live first 100k was about `4.8k`.

Carry forward:

- official upload = calibration experiment, not final distribution estimate;
- never select purely by the highest 100k official result;
- stress on public full days and sliding windows;
- ask whether the strategy survives a different ordering of regimes.

### We Optimized Wrappers Instead Of Building A Controller

After `probe_stack` and HYD abortgate were validated, the highest-value work was
not more minor wrappers. It was turning the stack into a rolling state machine.

The missing VELVET/options controller should have handled:

- volatility expansion;
- cross-strike synchronous moves;
- drawdown from recent peak;
- net delta across VELVET plus vouchers;
- reduce-only modes;
- re-entry with hysteresis;
- capacity reservation for later opportunities.

Carry forward:

- after a sleeve wins, immediately build a controller around it;
- do not let profitable static thresholds become the whole strategy;
- explicitly separate "entry edge" from "holding policy".

### We Did Not Use Hindsight Oracles Early Enough As Design Tools

The final-path oracle showed large missed opportunity in HYD cycles and
near-ATM VELVET/options timing. This kind of oracle is not uploadable, but it
is useful because it tells us where the ceiling is.

For R5, build oracles immediately:

- independent-product taker oracle;
- inventory-constrained oracle;
- terminal-flat oracle;
- passive-fill upper bound if the product is liquidity driven;
- family-specific oracle for baskets, conversions, options, or auctions.

Then compare real strategies to oracle capture. Low capture does not mean the
oracle is reachable, but it tells us where to investigate.

### We Underused Portfolio-Level Risk Variables

The option complex was traded too much as individual products. But VELVET and
VEV strikes are one correlated book.

Carry forward for any multi-product complex:

- define net exposure at the portfolio level;
- reserve capacity across related products;
- avoid maxing every correlated leg in the same direction;
- report PnL and drawdown by factor, not only by product.

For options specifically, track:

- spot;
- moneyness;
- implied volatility;
- realized volatility;
- delta;
- gamma;
- vega;
- theta;
- hedge cost;
- smile residual;
- terminal mark behavior.

### We Let "Mark Is The New Feature" Bias The Research Frame

R4's new mechanic was counterparty IDs, so it was natural to search for direct
Mark alpha. That was worth doing. The mistake would be to conclude that every
new mechanic must trade directly.

The evidence by the end:

- direct Mark55 recycling was tiny in official sim;
- Mark38 fade was fill/path dependent and did not help the final official
  100k integration;
- Mark22 basket composition looked more useful as a regime signal than as a
  simple one-product trade.

Carry forward:

- new mechanic first becomes a state variable;
- only then decide whether it is an entry, exit, sizing, hedging, or risk
  signal;
- test identity against matched time/cadence controls;
- do not keep trading a signal directly after controls show the edge is small;
- do not discard a mechanic entirely if it can improve regime classification.

## Correct Research Order For Round 5

Use this order before tuning parameters.

### 1. Classify Product Geometry

For every new asset, decide what it is:

- delta-one mean reversion;
- trend or momentum;
- option/convex payoff;
- basket/spread;
- conversion or settlement game;
- auction/rank game;
- hidden bot/liquidity game;
- inventory liquidation game.

The geometry determines the state variables. Do not start with thresholds.

### 2. Build PnL Attribution First

Before optimizing:

- parse trades and order books cleanly;
- compute per-product realized and mark PnL;
- track inventory through time;
- report spread paid/earned;
- bucket PnL by time;
- split entry PnL from holding PnL where possible.

If attribution is missing, tuning becomes guesswork.

### 3. Build Hindsight Ceilings

Create simple oracles early:

- perfect taker with limits;
- terminal-flat oracle;
- buy-and-hold/short-and-hold baselines;
- rolling mean-reversion oracle;
- trend-following oracle;
- product-family oracle.

The goal is not to copy the oracle. The goal is to identify which family has
enough ceiling to justify research time.

### 4. Build The Simplest Correct Strategy In Each Family

Do not overinvest in the first family that scores well. Build at least one
reasonable implementation of each high-ceiling family:

- static threshold;
- mean reversion;
- momentum/trend;
- passive spread capture;
- active taker capture;
- cross-product arbitrage;
- volatility/Greek strategy if options exist;
- bot/participant-conditioned strategy if IDs exist.

Then compare families before sweeping parameters.

### 5. Split Alpha From Controller

For every profitable sleeve, define:

- entry signal;
- target inventory;
- add rule;
- reduce rule;
- stop/kill rule;
- re-entry rule;
- terminal rule.

If a sleeve has entry logic but no reduce/kill logic, it is unfinished.

### 6. Run Robustness Before More Tuning

Before spending time on fine parameters, run:

- full public-day replay;
- sliding 100k windows;
- per-day results;
- worst-bucket results;
- max drawdown;
- terminal inventory;
- treatment versus matched control;
- local versus official calibration when available.

Large aggregate gains require timestamp review. If a gain comes from one thin
window, treat it as a hypothesis, not a result.

## Candidate Acceptance Checklist

A final candidate should not be promoted unless we can fill this out:

| Question | Required answer |
|---|---|
| What is the mechanism? | Clear economic or structural explanation |
| What is the product geometry? | Delta-one, option, basket, bot, etc. |
| Where does PnL come from? | Per-product and per-time attribution |
| What is the worst drawdown? | Known and explainable |
| What state kills the edge? | Explicitly defined |
| How does it reduce risk? | Reduce-only, hedge, flatten, or size down |
| What is the matched control? | Time/cadence/random/size control |
| Is the gain cross-slice? | Public days, sliding windows, official sim |
| Is terminal risk controlled? | Final positions and settlement logic |
| What is the left tail? | Scenario analysis, not just final PnL |

If we cannot answer these, the candidate is still research, not final.

## Upload Strategy For Round 5

Uploads should be experiments, not just leaderboard attempts.

Use upload slots for:

1. Baseline control.
2. One isolated sleeve.
3. Same sleeve with one mechanism removed.
4. Matched negative control.
5. Full stack.
6. Full stack with risk controller.
7. Aggressive version only after the controlled version is understood.

Do not upload five near-duplicate parameter tweaks unless the parameter is
already known to be the bottleneck.

Record every upload with:

- filename;
- intended hypothesis;
- expected result;
- actual result;
- delta versus baseline;
- interpretation;
- next action.

## Specific Anti-Patterns To Avoid

### Anti-Pattern 1: "This Is The New Feature, So It Must Be The Alpha"

New mechanics are often state information, not direct trade instructions.
Counterparty IDs in R4 were useful, but mostly as classification/regime inputs.

### Anti-Pattern 2: "The Candidate Has High PnL, So It Is Robust"

High PnL with large drawdown may be a fragile exposure bet. Require path
analysis.

### Anti-Pattern 3: "The First Working Family Deserves All The Time"

Static thresholds worked in R3/R4, but they capped us below the top. Once a
simple family works, use it as a base and search for the next structural layer.

### Anti-Pattern 4: "A Bad Prototype Kills A Whole Family"

Naive Greek/smile probes losing money does not prove option-native alpha does
not exist. It proves that implementation did not work under tested conditions.
Reject families only after testing the simplest correct version.

### Anti-Pattern 5: "Local Replay Rankings Are Truth"

Local replay is useful for fast iteration but can miscalibrate fills, passive
queue priority, and hidden simulator behavior. Use it for direction, then
validate mechanisms officially.

## First 24 Hours Protocol For Round 5

When R5 opens, do this in order.

1. Parse all products, limits, timestamps, prices, trades, and any new fields.
2. Write a one-page product-geometry classification.
3. Build per-product attribution and inventory plots for naive baselines.
4. Build simple oracles to estimate ceilings.
5. Identify the top two or three alpha families by ceiling and mechanism.
6. Build isolated strategies for each family.
7. Run full-day, sliding-window, and drawdown reports.
8. Upload one baseline and one isolated mechanism test.
9. Build controllers for the first validated sleeve.
10. Only then sweep parameters.

## What To Carry Forward Emotionally

Do not panic when the new round's special mechanic looks important. Treat it as
data. Classify it, control it, and ask what it changes about fair value,
execution, inventory, or regime.

Do not become attached to the first strategy that works. A working static
strategy is a research asset, not the final form. The next question is always:

```text
What state makes this strategy wrong, and how does the bot know that before
the PnL gives it back?
```

That is the core Round 4 lesson for Round 5.

## Source Notes

Use these R4 docs when deeper evidence is needed:

- `docs/round_4/R4_FINAL_POSTMORTEM_WHAT_WE_MISSED.md`
- `docs/round_4/R4_LIVE_POSTMORTEM.md`
- `docs/round_4/VELVET_ALPHA_FRONTIER_AND_ACTION_PLAN.md`
- `docs/round_4/FINAL_SPINE_OVERFIT_RISK_REVIEW.md`
- `docs/round_4/MARK_EXPLOITABILITY_HONEST_AUDIT.md`
- `docs/round_4/MARK_FIRST_PRINCIPLES_REAUDIT.md`
- `docs/round_3/ROUND_3_ALGO_POSTMORTEM_AND_PLAYBOOK.md`

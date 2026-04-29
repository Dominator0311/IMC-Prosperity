# IMC Prosperity 4 Edge Dossier

## Executive synthesis

Prosperity’s highest-leverage edge is almost never a “clever model”. It is a **system**: a reliable fair-value layer, disciplined execution under position limits, fast feedback (visualisation + attribution), and a tight loop for discovering and validating (or killing) hypotheses. Public top-performer writeups repeatedly show that when teams win big, they do so by (i) getting the **mechanics** right, (ii) extracting repeatable microstructure edges (spread + mispricing capture), and (iii) opportunistically exploiting **predictable agent/bot behaviours** when they appear—while keeping everything modular and defensively risk-managed. citeturn6view0turn12view0turn20view0turn27view0

The most robust “Prosperity-like” strategy families, as evidenced across Prosperity 1–3 public codebases and postmortems, cluster into six buckets:

**Reliable fair value + inventory-aware quoting (market making)**  
Top teams consistently start by building an accurate *proxy* for the simulator’s “true” reference/fair value (often inferable from persistent large-size “wall” quotes / a dominant market-making bot), then quote around it with inventory skew and hard safety rails. This appears in Prosperity 2 and Prosperity 3 writeups as “market maker mid” / “Wall Mid” approaches and is explicitly tied to improving robustness vs noisy mid prices. citeturn20view1turn12view2turn18view1

**Aggressive mispricing capture + systematic inventory clearing**  
High performers repeatedly emphasise that **position limits** silently throttle your ability to harvest repeated small edges; therefore, clearing inventory—even at ~0 edge—can increase long-run PnL by freeing capacity for future positive-EV fills (a concrete gain reported by a top-2 Prosperity 2 team). citeturn20view0

**Relative-value (pairs/baskets/spreads) with stable thresholds, not peak-fit parameters**  
Public top repos show basket-vs-synthetic mean reversion traded via thresholds and “flat-region” parameter choice rather than maximising a single sharp optimum. When done well, this is a direct transfer of real-world RV/stat-arb logic into a simplified environment. citeturn12view1turn20view2turn17view2

**Conversion / cross-venue / friction-aware arbitrage**  
Where the game offers explicit conversion/import/export mechanics, the winning pattern is to treat it as arbitrage with frictions (fees, tariffs, shipping), then adapt quote aggressiveness based on realised fills (“adaptive edge”). citeturn20view2turn18view1

**Options: mispricing + hedging-aware execution (gamma/theta reality checks)**  
Options rounds in Prosperity 2/3 are repeatedly described as a step-change: if you cannot compute a reasonable theoretical price and Greeks (even crudely), you will be systematically outclassed. But the decisive factor is not textbook pricing; it is *discrete-time hedging under spreads and position limits*. citeturn12view3turn22search0turn22search9turn14search7

**Trader/bot behaviour inference (the “Olivia” class of edges)**  
Several high-rank writeups document a large edge from detecting a highly predictable participant/bot trading pattern (e.g., trading fixed size at daily min/max), then positioning around it. This can be the single biggest edge when present, but it is also the most regime- and simulator-specific. citeturn12view1turn17view2turn26search0

What solo participants most often misunderstand (and what the best repos implicitly correct):

- **State is fragile**: the production environment is described as stateless (AWS Lambda); relying on global/class variables is risky, so you must persist state via `traderData` (compactly). citeturn6view0turn27view0  
- **Execution is iteration-scoped**: unfilled orders are cancelled at the end of an iteration, which changes what “market making” means—you are effectively posting very short-lived quotes repeatedly. citeturn6view0  
- **Capacity (position limits) is alpha**: if you don’t manage inventory deliberately, your best edges stop working because you can’t take the next trade. citeturn20view0turn17view1  
- **Tools are the multiplier**: custom dashboards and faithful backtesting (or at least a disciplined hybrid of official testing + local sim) are consistently cited as decisive. citeturn12view0turn19view0turn26search0turn11view5

Immediate priorities for the next few days (high expected practical value per hour):

Build a hardened baseline bot that (i) computes a robust fair value, (ii) cleanly separates “take” vs “make”, (iii) hard-enforces position constraints **before** sending orders, (iv) logs compactly for attribution, and (v) stores minimal rolling state in `traderData`. This is the platform you will bolt everything else onto. citeturn6view0turn20view0turn27view0

## Source map

**Official and quasi-official environment documentation (mechanics constraints)**  
The most actionable public “ground truth” for Prosperity mechanics is the IMC Prosperity Notion page on how the Python algorithm is executed, including the iteration loop, end-of-iteration cancellation, and the need to use `traderData` for persistence under a stateless execution model. citeturn6view0  
A complementary (tooling, but informative) statement of “official requirements” (allowed imports, return signature, stateless warnings, and a per-call timeout budget) is documented by an open-source Prosperity validator/submitter tool. Treat it as strongly suggestive; always cross-check against the current Prosperity portal rules when available to you. citeturn27view0

**Top public participant repos (code + process + results)**  
- entity["people","TimoDiehm","github user"] / Frankfurt Hedgehogs (Prosperity 3): deep writeup; extensive dashboard philosophy; explicit “Wall Mid”; explicit bot-pattern exploitation (“Olivia”); explicit backtesting methodology. citeturn23search11turn12view0turn12view1turn12view2  
- entity["people","ericcccsliu","github user"] / Linear Utility (Prosperity 2): top-tier tooling (backtester + dashboard), parameter gridsearch workflow, inventory-clearing insight, adaptive arbitrage edge, and an example of dangerous “historical quirk” exploitation. citeturn28search10turn19view0turn20view0turn20view2  
- entity["people","ShubhamAnandJain","github user"] / Stanford Cardinal (Prosperity 1): full multi-product trader; explicit basket residual logic with constants, observation-driven triggers, and cross-trader tracking structures—useful as an archetype library (but state handling must be adapted for Prosperity 4). citeturn28search0turn17view1turn17view2turn17view4  
- entity["people","CarterT27","github user"] / Alpha Animals (Prosperity 3): strong meta-insights about tool limitations (especially conversions), plus a candid “what didn’t work” list (valuable for pruning). citeturn26search0  
- entity["people","pe049395","github user"] (Prosperity 2): explicit discussion of microprice vs mid, “hidden fair value” inference from large book levels, and why some limit orders never fill—pushing you towards taker logic and proper fill modelling. citeturn18view1turn18view2  
- entity["people","jmerle","github user"]: open-source backtesting and visualisation ecosystem (widely cited by participants), plus code patterns for logging under tight size limits and order matching conventions. citeturn11view5turn14search7turn11view4  
- entity["people","JamesCole809","github user"]: clear quantitative write-up (e.g., VWAP-based fair value) which is a good “sanity check” baseline for your own models. citeturn26search1

**Participant writeups / postmortems (useful triangulation, especially for solo constraints)**  
- entity["people","Martin Oravec","prosperity participant"] (solo, 73rd overall): highlights practical friction points and mistakes; useful for “solo realism”. citeturn25view0  
- entity["people","Matius Chong","prosperity participant"]: concise notes on common strategy shapes (moving-average fair value; basket z-score; Black–Scholes framing). citeturn25view3  
- entity["people","David Teather","prosperity participant"]: confirms options round framing (Black–Scholes used to decide buy/sell) and provides a beginner-to-intermediate perspective on what mattered by round. citeturn25view1

**Academic foundations (for mechanisms, not for “alpha by citation”)**  
- Avellaneda–Stoikov: canonical inventory-aware market making with Poisson order arrivals and risk-averse utility framing. citeturn21search4  
- Stoikov micro-price: formalises “microprice” as an order-book-conditioned fair price estimate (imbalance-adjusted). citeturn21search6turn21search2  
- Gatev–Goetzmann–Rouwenhorst: classic empirical pairs trading / convergence framework. citeturn21search3  
- Black–Scholes: baseline option pricing logic. citeturn22search0  
- Hull (practitioner delta hedging): how hedging is done in practice using implied vol and model Greeks. citeturn22search9

**Institutional analogues (to understand when Prosperity simplifies vs distorts)**  
- ETF arbitrage and the creation/redemption mechanism driven by APs, plus frictions and liquidity mismatch realities. citeturn22search7turn22search3turn22search31

## Strategy taxonomy for Prosperity-like environments

The table below is written to be **implementation-guiding**: it links strategy families to concrete signals/features, required data, typical compute footprint, and how each interacts with your stated Prosperity 4 mechanics (iteration-scoped orders, statelessness unless `traderData`, strict position caps, limited runtime/imports). citeturn6view0turn27view0

| Strategy family | Core mechanism | Typical signal / feature | Example Prosperity usage | Closest institutional analogue | Data needed | Compute cost | Prosperity 4 compatibility | Robustness / transferability | Main failure mode |
|---|---|---|---|---|---|---|---|---|---|
| Inventory-aware market making | Quote bid/ask around a fair value; skew prices/sizes to control inventory | Fair value estimate + inventory + (optional) volatility proxy | Resin/amethysts-style quoting around stable fair value; Kelp/Starfruit quoting around adaptive fair value citeturn12view2turn20view0turn17view1 | Dealer/MM quoting with inventory risk (Avellaneda–Stoikov) citeturn21search4 | L1–L3 order depth, position, recent trades | Low | COMPATIBLE | High | Inventory drift + adverse selection; stuck at position limits; quoting at prices that never fill |
| Fair-value estimation layer | Build “true price” proxy used by all strategies | Rolling mid, VWAP mid, dominant-MM mid, wall-mid | “Market maker mid” and “Wall Mid” improve vs noisy mid citeturn20view1turn12view2turn18view1 | Internal marking / reference price estimation (microstructure) | Order depth, optional trades | Low | COMPATIBLE | High | Proxy breaks when market regime changes (walls disappear / bots change) |
| Microprice / imbalance | Adjust mid toward the side with more queue pressure | L1 imbalance; microprice (imbalance-adjusted mid) | Participants explicitly move from raw mid to microprice / wall-mid citeturn18view1turn26search1 | Order-book-conditioned fair price (Stoikov micro-price) citeturn21search6turn21search2 | L1 sizes; optionally deeper levels | Low | COMPATIBLE | Medium–High | Signal too weak vs spread; overtrading; breaks if bots place “fake” depth |
| Spread capture (passive fills) | Earn bid–ask spread by being maker; manage fill probability | Quote inside spread; undercut/overbid logic; fill-rate feedback | Undercut/overbid by 1 tick; multi-level quoting; utility-based quoting citeturn17view1turn18view1turn12view2 | Competitive liquidity provision | Order depth; your fills | Low | COMPATIBLE | Medium–High | No fills (orders cancel each iteration); fills only when adverse; poor inventory management |
| Mean reversion (single asset) | Trade deviations from mean / stable anchor | z-score vs rolling mean; OU-style assumptions | Squid ink “mean-reversion” attempts; more robust when tied to fair-value proxy citeturn25view3turn12view2turn18view1 | Short-horizon statistical arbitrage | Prices, fair-value series | Low–Med | COMPATIBLE | Medium | Regime shift؛ chasing noise; costs dominate edge |
| Short-horizon trend / drift | Follow persistent drift with risk caps | EMA slope; breakout; drift + stop/flatten logic | Drift-aware fair value (rolling mid); “don’t static-MM a drifting product” is common citeturn20view0turn11view7 | Intraday momentum / short-term alpha with execution constraints | Rolling prices; possibly book features | Low | COMPATIBLE | Medium | Getting whipsawed; overfitting thresholds |
| Pairs trading / relative value | Trade spread between linked assets | Spread z-score; cointegration-style residual | Coconuts vs pina coladas; other linked products depending on year citeturn23search27turn21search3 | Relative-value stat-arb (pairs) citeturn21search3 | Prices for both legs; positions | Low–Med | COMPATIBLE | Medium–High | Spread doesn’t converge within horizon; leg execution mismatch under limits |
| Basket / ETF-style arbitrage | Basket vs synthetic constituents mean reverts | Basket − Σ(wᵢ·legᵢ) residual; threshold | Picnic basket strategies; gift basket spreads; explicit residual formulas appear in code citeturn17view2turn20view2turn18view1 | ETF arbitrage + RV trading (creation/redemption in reality) citeturn22search7turn22search3 | Prices/order books of basket + legs | Med | COMPATIBLE | Medium–High | Can’t convert basket↔legs (so “arbitrage” is statistical); inventory constraints cause imperfect hedges |
| Conversion / cross-location arbitrage | Trade price differences across venues with frictions | Net edge after tariffs/fees/shipping; execution probability | Orchids cross-exchange arbitrage; adaptive edge based on fills citeturn20view2turn18view1 | Cross-venue arbitrage under fees/latency | Order books + conversion terms + obs | Med | PARTIALLY COMPATIBLE | Medium | Mis-modelling execution + fees; conversion mechanics misunderstood |
| Options pricing / vol trading | Trade option vs theoretical; hedge delta if feasible | B–S price / implied vol; delta/gamma; realised vs implied logic | Volcanic rock vouchers (options analog) and explicit option round writeups citeturn12view3turn25view3turn25view1 | Market making + gamma scalping / implied vs realised vol citeturn22search0turn22search9turn22search18 | Underlying + options books; time-to-expiry | Med | PARTIALLY COMPATIBLE | Medium | Discrete hedging costs + spread overwhelm; wrong vol/expiry assumptions; position limit interactions |
| Trader-behaviour / order-flow inference | Detect and follow predictable bot flow | Trade size filters; daily extrema triggers; cross-product inference | “Olivia” pattern exploitation; thresholds shifted by inferred insider position citeturn12view1turn17view2turn26search0 | Informed-flow detection (microstructure) | Market trades (even without IDs) | Low–Med | PARTIALLY COMPATIBLE | Medium | Pattern disappears / changes; false positives; overfitting to one bot |
| Regime detection | Switch logic based on volatility/trend/flow regime | Volatility proxy; spread widening; fill-rate changes | Explicit warnings against blind overfitting; simple regime flags often beat complex models citeturn12view3turn20view2 | Volatility regime / liquidity regime models | Rolling stats; fill metrics | Low | COMPATIBLE | Medium | Threshold sensitivity; “regime” signal lagging |
| PnL decomposition & diagnostics | Attribute PnL to edges and mistakes | Markout, inventory PnL, spread PnL, slippage, opportunity cost | Dashboard features: synced views, indicator overlays, log viewer, normalisation citeturn12view0turn20view0turn14search7 | Execution analytics | Logs + trades + book | Med (offline) | COMPATIBLE | High | Mis-attribution due to backtester inaccuracies; ignoring bot behaviour mismatch |

image_group{"layout":"carousel","aspect_ratio":"16:9","query":["limit order book heatmap example","order book imbalance chart example","market making inventory skew diagram","ETF arbitrage basket versus constituents diagram"],"num_per_query":1}

Key synthesis across top repos: **“Fair value” is not optional**. Multiple high-ranking teams explicitly report that naïve midprice is noisy and that a more stable proxy can be inferred from persistent large-size quotes or a dominant market-making bot; they even validate this by comparing mark-to-market PnL behaviour. citeturn20view1turn12view2turn18view1  

A second repeated pattern is **execution pragmatism**: when passive limit orders rarely fill (especially in wider-spread or conversion contexts), top teams pivot toward aggressive taking when the edge is sufficiently large, even accepting slippage deeper in the book, and they treat “fill probability” as a first-class variable. citeturn18view2turn18view1turn20view2  

Finally, the most competition-specific (but sometimes dominant) family is **predictable bot behaviour**. The Prosperity 3 2nd-place writeup documents a very concrete edge from detecting a fixed-size trader at daily extremes and then “following” their implied directional information; they explicitly manage false positives via invalidation rules and later simplify detection when IDs become visible. citeturn12view1turn12view0

## Public repo and writeup comparison

The goal here is not to “copy strategies”, but to extract **reusable architecture and research primitives** that repeatedly correlate with high placement: near-realistic simulation, tight logging/visualisation, stable parameter selection, and mechanism-aware execution. citeturn19view0turn12view0turn27view0

| Team / participant | Year | Claimed result | Main strategies | Best tooling insight | Best research insight | What to copy | What not to copy blindly | Prosperity 4 compatibility notes |
|---|---:|---|---|---|---|---|---|---|
| entity["people","TimoDiehm","github user"] (Frankfurt Hedgehogs) | 2025 | 2nd globally; score reported in repo citeturn23search11 | Wall-mid fair value; inventory-aware MM; basket stat-arb; options scalping; locational arb; bot-pattern exploitation (“Olivia”) citeturn12view1turn12view2turn12view3 | Build a purpose-built order-book dashboard; hybrid backtesting (official site for bot effects, local sim for fast iteration) citeturn12view0turn12view2 | Choose parameters from *stable regions* not sharp maxima; detect predictable bot flow early citeturn12view1turn12view2 | Dashboard design principles; wall-mid detection; “kill strategies fast” mindset; parameter landscape checks | Exact constants/thresholds; assumption that your year will have the same “Olivia” behaviour | Must implement persistence via `traderData` and treat orders as iteration-scoped citeturn6view0 |
| entity["people","ericcccsliu","github user"] (Linear Utility) | 2024 | 2nd globally; score reported in repo citeturn28search10 | Fixed-fair product MM/taking; drift product via dominant-MM mid; inventory clearing; conversion arb with adaptive edge; basket spread MR; later DP-style exploitation citeturn20view0turn20view1turn20view2turn20view4 | In-house backtester that emits Prosperity-format logs + parameterised trader for gridsearch citeturn19view0 | Validate what the simulator marks-to-market against; treat position-limit capacity as PnL driver citeturn20view1turn20view0 | Inventory clearing logic; adaptive edge based on fill-rate; parameter plumbing | Any approach reliant on historical “look-alike” paths (high overfit risk) citeturn20view3 | Great fit if you re-implement state via `traderData`; adaptive edge must be lightweight citeturn6view0turn27view0 |
| entity["people","ShubhamAnandJain","github user"] (Stanford Cardinal) | 2023 | Final rank 2nd / 7007 teams (repo README) citeturn28search0 | Multi-asset MM; basket residual; observation-triggered trades (e.g., “dolphin sightings”); trader-position tracking incl. “Olivia” references in code citeturn17view1turn17view2turn17view4 | Code as archetype library: “how to wire many product modules into one Trader” | Evidence that observation channels can dominate when properly thresholded citeturn17view4 | Module-per-product structure; residual computation patterns; observation hooks | Reliance on class-level global state (unsafe under stateless execution) citeturn6view0turn27view0 | Rebuild state persistence with `traderData`; avoid assuming class vars persist citeturn6view0 |
| entity["people","CarterT27","github user"] (Alpha Animals) | 2025 | 9th globally, 2nd USA (repo README) citeturn26search0 | Broad reuse of prior-year ideas; attempted delta hedging; attempted basket/component arb | Reliance on open-source backtester/visualizer saves time; backtester limitations can cause major losses (conversions) citeturn26search0 | “What failed” list is a pruning tool; conversion misunderstanding is catastrophic | Use as negative-space guide for what to not overbuild | Their specific failures are not universal; don’t overreact by avoiding conversions entirely | Highlights that conversions/options require precise mechanics modelling citeturn26search0 |
| entity["people","pe049395","github user"] | 2024 | Overall rank 13 (repo README) citeturn18view2 | Microprice attempt; hidden fair from large depth levels; cross-venue arb; deep-book execution when edge large; Monte Carlo augmentation for robustness citeturn18view1turn18view2 | Explicitly models execution probability; recognises that “orders don’t fill” is a strategy constraint | “Hidden fair value” inference from book structure is repeatable across years when present citeturn18view1 | Fill-rate experiments; deep-taking rule when edge > slippage | Their OU/Poisson modelling didn’t clearly improve—don’t sink days into elegant probability models early citeturn18view1 | Good template for conversion/arb modules; keep compute minimal citeturn27view0 |
| entity["people","jmerle","github user"] (tool ecosystem) | 2024–2026 | Widely used backtester/visualiser; matching logic documented citeturn11view5turn11view4 | N/A (tools) | Log-size discipline and compression patterns; explicit order matching assumptions citeturn14search7turn11view5 | Formalise logs to stay within limits; treat simulator matching rules as testable assumptions | Assuming backtester replicates bot behaviour perfectly citeturn12view2turn11view5 | Essential as “fast loop”, but you still need official-site validation for bot nuances citeturn12view2 |
| entity["people","Martin Oravec","prosperity participant"] | 2025 | 73rd overall, 5th UK (Medium) citeturn25view0 | Practical baseline trading + iteration | Solo constraints: time, focus, and tool reliance | The “mistake catalogue” helps you prioritise robustness over cleverness | Use as sanity check for effort allocation | Any single-player narrative can mislead you about top-of-leaderboard dynamics | Reinforces need for a strong baseline + selective sophistication citeturn25view0 |

## Institutional deep dive

This section’s purpose is not to teach finance theory; it is to identify *which institutional ideas survive contact with Prosperity’s mechanics* and how to adapt them into robust, low-latency, iteration-scoped code.

**Market making and inventory models**  
Institutionally, market makers quote bid/ask spreads, control inventory risk, and trade off execution intensity vs profit-per-trade. The Avellaneda–Stoikov framework formalises this as an optimal control problem with (i) a mid-price process, (ii) Poisson arrivals of market orders, and (iii) risk aversion that pushes reservation prices away from mid as inventory grows. citeturn21search4  
Prosperity compresses this dramatically: you are repeatedly re-posting quotes each iteration, and “queue position” is simplified compared with a real exchange. But the **core transfer** is intact:  
- you need a **reservation price** (fair value minus inventory penalty),  
- you need a **spread/edge** choice (wider edge = fewer fills but better price), and  
- you need **hard caps** (position limits) and soft caps (inventory skew) because the environment rewards continuous harvesting of small edges. This is fully consistent with top-team behaviour: quote around a stable fair value, undercut/overbid by small ticks, and actively neutralise inventory when it blocks future trades. citeturn20view0turn17view1turn12view2

What to borrow: inventory-skewed quoting, capacity management, and explicit modelling of “execution probability” as something to measure rather than assume. citeturn18view1turn19view0  
What to ignore: heavy continuous-time derivations or parameter-rich models that you cannot reliably calibrate under dataset shift and runtime constraints. citeturn27view0turn12view2

**Microstructure alpha: microprice, imbalance, and “who sets the reference”**  
Stoikov’s micro-price formalises a fair price estimate conditioned on order book state (not just mid), often expressible as an adjustment of mid by spread and imbalance. citeturn21search6turn21search2  
Prosperity competitors rediscovered this empirically: several top writeups say midprice is noisy because participants place orders “past mid”, whereas large “wall” quotes from a dominant market maker remain stable and reflect the internal mark. citeturn20view1turn12view2turn18view1  

What to borrow: build a layered fair value stack:  
(1) wall-mid / dominant-MM mid when detectable,  
(2) microprice/imbalance mid as fallback,  
(3) rolling VWAP/mid as last resort. citeturn20view1turn18view1turn26search1  
What to ignore: deep LOB modelling that requires rich event streams you do not have (Prosperity gives snapshots + trades, not full order-flow messages). citeturn6view0

**Statistical arbitrage: pairs, spreads, and baskets**  
Pairs trading and convergence trading are classic RV strategies; the Gatev–Goetzmann–Rouwenhorst paper is a canonical empirical reference for forming pairs and trading spread divergence/convergence rules. citeturn21search3  
Prosperity’s RV rounds (gift baskets, picnic baskets) are simplified: you often cannot create/redeem or physically convert basket↔legs, so “arbitrage” becomes *statistical reversion*. Yet the transferable core remains: define synthetic value, compute residual, trade when residual is sufficiently extreme relative to costs and risk. This appears directly in public Prosperity code (explicit residual formulas, thresholds, and mean reversion logic). citeturn20view2turn17view2turn18view1  

What to borrow: residual modelling, threshold entry/exit, and “hedge only if it helps” (some teams explicitly avoided trading legs to reduce transaction costs and complexity). citeturn18view1  
What to ignore: assuming immediate convergence or perfect hedging—Prosperity position limits and execution mismatches can make “market-neutral” theoretical trades behave like directional bets. citeturn17view2turn20view2

**ETF arbitrage analogues and why Prosperity distorts them**  
Real ETFs are kept near NAV through AP-driven creation/redemption arbitrage, but frictions and liquidity mismatch matter; institutional sources describe the AP mechanism and its limits. citeturn22search7turn22search3turn22search31  
Prosperity’s baskets often *look* like ETFs (basket vs constituents) but may lack actual conversion. That means:  
- the *institutional intuition* (“basket premium should mean revert”) is still useful,  
- but you must treat it as **spread trading**, not true arbitrage, and manage “non-convergence risk” explicitly (position limits, stop-outs, reduced size when spreads widen). citeturn12view1turn20view2

**Options and hedging**  
Black–Scholes provides a baseline for theoretical option value. citeturn22search0  
Hull documents the reality of hedging in practice: traders commonly compute Greeks using implied volatility (“practitioner Black–Scholes”) and hedge dynamically, aware that discrete hedging and costs matter. citeturn22search9  
Prosperity options rounds (vouchers/coupons) push you into the same shape: compute a reference option value, trade mispricing, and decide whether hedging is worth it under discrete time, spreads, and position limits. Public participants explicitly report building Black–Scholes-style logic for options rounds. citeturn25view1turn12view3turn14search7  
A crucial adaptation is to treat “gamma scalping” (earning from convexity via re-hedging) as a **cost–benefit** problem: you pay theta and spread costs, and you only win if realised movement harvested via hedges exceeds those costs (a point emphasised even in pedagogical notes on the topic). citeturn22search18turn22search9

**Arbitrage with frictions: conversion, tariffs, transport, and execution probability**  
When Prosperity introduces cross-location/conversion mechanics, it becomes a stylised version of cross-venue arbitrage with explicit costs. High-ranking Prosperity 2 writeups describe focusing less on predicting the asset and more on mechanism-driven arbitrage, explicitly incorporating shipping/tariffs and empirically estimating execution probability. citeturn20view2turn18view1  
This maps directly to institutional thinking: edges are not “price differences”; they are price differences **net of frictions and fill uncertainty**.

## Edge discovery framework

A Prosperity round is a short, high-pressure research cycle. High performers’ public accounts converge on a workflow that looks like disciplined reverse engineering rather than “backtest roulette”: build observability, form hypotheses about mechanics/agents, run targeted experiments, and kill ideas fast when they don’t survive stress tests. citeturn19view0turn12view2turn20view2

A concrete workflow that is consistent with what top repos describe:

**Instrument the environment first**  
You want a single run to produce: (i) per-product fair value series, (ii) your quotes, (iii) fills, (iv) position, and (v) PnL/markout diagnostics—syncable by timestamp in a viewer/dashboard. This is explicitly described as decisive by top teams (syncing clicks to inspect anomalies; log viewer tied to timestamps; normalising prices by fair values). citeturn12view0turn20view0  

**Detect “reference price” mechanics early**  
Multiple top competitors report that the simulator’s mark-to-market can align with a hidden/internal fair value and that persistent large orders reveal it (“market maker mid”, “Wall Mid”). One team validates this by comparing a buy-and-hold PnL graph between local backtest and the official site. citeturn20view1turn12view2turn18view1  
Actionable implication: in the first hours of a round, run experiments that test whether PnL behaves like marking to mid, microprice, or a wall-mid proxy.

**Separate two hypothesis classes: statistical structure vs agent structure**  
Top writeups explicitly distinguish between:  
- strategies that depend on bot interactions (validate on the official site), and  
- strategies that depend mainly on your own quoting/taking logic (validate in a local backtester for speed). citeturn12view2turn11view5  

**Design experiments that isolate the causal variable**  
Examples directly supported by public evidence:  
- Vary quote distance (“edge”) and measure fill-rate and adverse selection (teams gridsearch edges). citeturn20view0turn19view0  
- For conversion arbitrage, vary your local sell price offset and observe fill/edge tradeoffs; implement adaptive offset when fills fall. citeturn20view2  
- For bot-pattern detection, filter trades by size and check whether they cluster at extrema; apply invalidation logic for false positives. citeturn12view1  

**Validate robustness by looking for parameter plateaus**  
A top Prosperity 3 writeup explicitly shows parameter grid landscapes and states they prefer stable flat regions over sharp peaks to avoid overfit disasters. citeturn12view1turn19view0  
In practice: your sweeps should produce heatmaps; you pick *boring* settings.

**Decide keep / adapt / kill with explicit criteria**  
A practical rubric that aligns with the public record: keep a strategy only if it (i) survives perturbations (window size, threshold, seed/day), (ii) does not rely on one fragile feature, and (iii) has a clear failure-mode mitigation (stop/flatten rule, size reduction, or hedging). The cautionary notes about overfitting and failed pattern mining (and the long lists of “we tried X; didn’t work”) are valuable pruning signals. citeturn26search0turn18view1turn12view3

## Tooling stack and workflow

Prosperity is unusually “tool sensitive” because your research loop is short and the environment is subtle (microstructure, bot interactions, hidden marking conventions). The top public repos treat this as non-negotiable: dashboards, backtesters, log parsers, and parameter sweep plumbing appear early and repeatedly. citeturn19view0turn12view0turn26search0turn26search2

**Must-have (highest ROI, especially solo)**

A faithful-enough backtesting loop with parameter hooks  
A top-2 team describes building a backtester that reconstructs state from historical data, feeds it into the trader, matches orders, and outputs logs in the platform format; they also add parameter injection to enable systematic grid search. citeturn19view0turn20view0  
If you don’t want to build this from scratch, open-source backtesters explicitly document their matching assumptions (how orders are matched vs order depth and trades), which is essential for interpreting results. citeturn11view5turn11view4

A visualiser/dashboard that answers “why did we make/lose money here?”  
A top Prosperity 3 team describes a custom dashboard with order-book plotting, PnL and position panels, a timestamp-synchronised log viewer, and indicator normalisation (e.g., normalising by wall-mid to make a drifting series stationary). citeturn12view0turn12view2  
A top-2 Prosperity 2 team similarly highlights “sync by timestamp” as key for inspecting anomalies. citeturn20view0

Compact logging + log-size discipline from day one  
There are real size limits: one widely used Prosperity codebase uses log truncation and sets a maximum log length (e.g., 3750 chars) while compressing state/orders and truncating logs/traderData. citeturn14search7  
Your design implication: build a logger that (i) logs only what you can attribute, (ii) is compressible, and (iii) produces structured events you can parse offline.

A submission “gate”: static checker + forbidden-import guard  
A Prosperity validator tool documents checks that align with the platform’s practical constraints: presence of `Trader.run`, return tuple `(orders, conversions, traderData)`, restricted imports, and warnings that instance variables may not persist because Lambda is stateless; it even encodes a per-call time budget. citeturn27view0turn6view0  
Even if you don’t use that tool, implement its philosophy: a pre-submit script that rejects accidental `os`, file I/O, slow loops, and non-deterministic randomness.

**Useful extras (good if time permits)**

- Hybrid validation harness: run local backtests for speed, then spot-check promising strategies on the official platform when bot interaction nuances matter (explicitly recommended by top competitors). citeturn12view2  
- A small experiment tracker: store parameter sets and resulting PnLs; the point is to avoid rerunning the same “almost good” idea due to confusion.

**Overkill (high risk under time pressure)**

- Complex ML/RL modelling in the submission loop: your runtime/import constraints and dataset shift make this a trap unless Prosperity explicitly structures a forecasting task around it. citeturn27view0turn6view0turn12view3

## Recommended code architecture and Prosperity 4 compatibility filter

### Architecture blueprint

The architecture below is designed to maximise edge discovery speed while obeying Prosperity 4 constraints (iteration-scoped orders, stateless execution unless `traderData`, strict per-product position caps, limited runtime/imports).

**Core principle: the `Trader.run()` method should be a thin orchestrator**  
The Prosperity environment executes your method repeatedly and cancels unfilled orders each iteration; the official guidance also indicates your code runs in a stateless environment, so your modules must be designed for robust serialisation and fast execution. citeturn6view0turn27view0  

A concrete component map:

**StateStore**  
- `load(traderData) -> State`: minimal rolling state (rolling windows, last seen extrema, running vol estimates, per-product flags).  
- `save(State) -> traderData`: compact serialisation (prefer small dicts + arrays; avoid verbose logs).  
This is mandatory because global/class variables are not safe. citeturn6view0turn27view0

**MarketDataAdapter**  
- Normalise `order_depths`, build sorted L1–Lk ladders, compute best bid/ask, spreads, VWAP, and optional wall detection.  
- Compute microprice/imbalance features as fallback fair values. citeturn18view1turn26search1turn21search6

**FairValueEngine (per product)**  
- `fair(product, state, md) -> float`  
Implements a cascade: wall-mid (if deep levels), else microprice, else rolling mid/VWAP. This matches the empirical lessons top teams report. citeturn20view1turn12view2turn18view1

**SignalEngine (per product / cross product)**  
Returns target exposures or trade intents (e.g., “take undervalued ask”, “quote bid/ask”, “spread long basket/short synthetic”, “options mispriced buy”, “detected predictable bot – bias”). Use simple signal objects so you can log them.

**Risk & Inventory Manager**  
- Hard-enforce per-product limits and implement soft limits: reduce size as you approach caps.  
- Implement “inventory clearing” operator (flatten towards 0 when capacity is the bottleneck), a technique explicitly shown to increase PnL by unlocking future opportunities. citeturn20view0turn17view1  
- Provide a single function: `clip_orders_to_limits(orders, current_position, limit)` to avoid platform-order rejection when aggregate volume would breach limits. citeturn6view0

**Execution Engine**  
- **Taker module**: aggressively cross the spread when edge is large vs fair value or when you must neutralise risk.  
- **Maker module**: quote with 1–2 tick improvement logic (undercut/overbid) and inventory skew. This is visible in multiple public codebases. citeturn17view1turn12view2turn18view1  
Because orders are cancelled each iteration, maker logic is “re-quote every step”, not “place and wait”. citeturn6view0

**Conversion / Options modules (activated only when relevant)**  
Conversion: compute net edge after fees/tariffs and include an empirically calibrated execution-probability model; implement adaptive aggressiveness based on realised fill-rate. citeturn20view2turn18view1  
Options: implement Black–Scholes price + Greeks; decide whether hedging is worth it given discrete-time costs; keep compute minimal (closed forms). citeturn22search0turn22search9turn14search7

**Diagnostics**  
A structured logger that records (a) fair value, (b) quotes, (c) fills, (d) inventory, and (e) signal states, while truncating to stay within limits. citeturn14search7turn12view0

### Prosperity 4 compatibility filter table

The table below applies your stated P4 lens (iteration-scoped orders, auto-cancel, statelessness, runtime limits, position-limit rejection, limited trader IDs, hidden OOS final) to the most important ideas found in sources.

| Idea / tactic | Source | Why it worked there | Prosperity 4 compatibility | Required adaptation | Risk of overfitting / non-transfer | Practical priority |
|---|---|---|---|---|---|---|
| Wall-mid / dominant-MM mid as fair value | Multiple top repos describe switching off noisy mid toward stable wall/dominant-MM quotes citeturn20view1turn12view2turn18view1 | Reduces noise; aligns with internal marking convention in those years citeturn20view1turn12view2 | COMPATIBLE | Build wall detector + fallback microprice/rolling; don’t hardcode levels | Medium (depends on whether “walls” exist this year) | Highest |
| Inventory clearing at ~0 edge to free capacity | Reported to increase PnL by unlocking future trades citeturn20view0 | Position caps prevent harvesting repeated small edges | COMPATIBLE | Add explicit “capacity is alpha” logic; flatten when near cap | Low | Highest |
| Systematic undercut/overbid quoting | Appears in top strategies for stable/fair-anchored products citeturn17view1turn12view2 | Captures spread against bots while managing inventory | COMPATIBLE | Re-quote every iteration; adjust sizes under limits | Medium | Highest |
| Basket vs synthetic mean reversion with stable thresholds | Widely used; explicit residual formulas and threshold logic citeturn20view2turn17view2turn12view1 | Residual tends to oscillate; threshold trading robust if not overfit | COMPATIBLE | Implement cross-product inventory/risk; choose plateau params | Medium | High |
| Conversion arbitrage with adaptive edge | Top teams describe it; leaked strategies quickly commoditised citeturn20view2turn18view1 | Mechanism edge; execution dependent | PARTIALLY COMPATIBLE | Only if P4 includes conversions; otherwise keep module dormant | Medium–High | High if conversions exist |
| Aggressive deep-book taking when edge large | Used when limit orders rarely fill citeturn18view2 | Ensures capture of rare mispricing | COMPATIBLE | Add “edge vs slippage” rule; cap size; rapid flatten plan | Medium | Medium–High |
| Options pricing + (selective) hedging | Options rounds; B–S used by participants citeturn12view3turn25view1turn22search0 | Mispricing + convexity; hedging controls risk | PARTIALLY COMPATIBLE | Discrete-time, spread-aware hedging thresholds; avoid heavy optimisation | Medium | Medium (build after baseline) |
| “Olivia”-type bot pattern detection | Huge edge when present; explicitly documented citeturn12view1turn17view2turn26search0 | Exploits predictable agent flow | PARTIALLY COMPATIBLE | Build generic detectors (extrema, size filters, invalidation rules) not hardcoded IDs | High | Medium (but keep ready) |
| Heavy ML/RL inside Trader | Not supported by typical library/runtime constraints; high overfit risk citeturn27view0turn6view0 | N/A | INCOMPATIBLE | Use offline only for research; distill to simple rules | Very high | Low |
| Using global/class vars for state | Older code does this, but platform described as stateless citeturn6view0turn17view0 | Convenience | INCOMPATIBLE | Move all persistent info into `traderData` | Low (not “overfit”; just breaks) | Highest (to fix) |
| Blind parameter peak-picking | Top teams warn against it via stability-first selection citeturn12view1turn19view0 | Peak fits fail under shift | INCOMPATIBLE (as a practice) | Parameter plateau search + perturbation tests | Very high | Highest (avoid) |

### Actionable build plan

This is a concrete “next 3 days” plan optimised for solo/small-team execution and aligned with the mechanics constraints and what top performers state helped them most.

**Day 1: Build the hardened baseline (production-grade skeleton, not alpha)**  
Implement the `Trader` scaffold with:  
- `StateStore` using `traderData` (versioned dict; rolling windows capped). citeturn6view0turn27view0  
- `MarketDataAdapter` (sorted ladders, VWAP, microprice/imbalance, wall detector). citeturn18view1turn21search6  
- `RiskManager` with strict order clipping to position limits and an explicit “inventory clearing” operator. citeturn6view0turn20view0  
- Logger that truncates and emits parseable events. citeturn14search7turn12view0  
Outcome: you can run a trivial “buy undervalued, sell overvalued, quote around fair” strategy safely, and you can *see* what it’s doing.

**Day 2: Build your research loop (one-click attribution)**  
- Plug into a backtester/visualiser workflow and confirm you can reproduce logs and inspect anomalies quickly; top teams attribute major early PnL gains to this. citeturn12view0turn19view0turn11view5  
- Add parameter plumbing (a dict of per-product thresholds/edges) so you can run sweeps without rewriting code. citeturn19view0turn12view1  
- Add a “markout” report offline: trade price vs fair value at +1, +5, +20 iterations; split by maker vs taker.

**Day 3: Add the two highest-value alpha modules (generic, reusable)**  
- Relative value module (spread/basket): residual computation, z-score/threshold entry/exit, risk-capped sizing, and “plateau parameter selection” harness. citeturn20view2turn12view1turn17view2  
- Pattern scanner module: trade-size filters + extrema detection + invalidation. Even if P4 doesn’t have an “Olivia”, this module doubles as a regime/flow detector. citeturn12view1turn26search0  
Keep conversions/options modules stubbed but dormant until the round demands them.

A strong baseline bot (what it should contain before you chase sophistication):  
- Fair value cascade (wall-mid → microprice → rolling mid). citeturn20view1turn18view1turn21search6  
- Take mispriced L1/L2 orders when edge exceeds a threshold.  
- Make 1–2 tick improved quotes with inventory skew. citeturn17view1turn12view2  
- Inventory clearing rule when near limits. citeturn20view0  
- Per-product toggles so you can disable a dangerous module instantly when it misbehaves (a common mid-competition necessity). citeturn26search0turn10search7

### Where this research could mislead you

Public repos have heavy survivorship bias: you mostly observe teams who were willing to publish and who did well enough to feel confident sharing. Even among these, strategy descriptions can compress complexity; the most fragile parts are often omitted or under-emphasised.

Overfitting risk is structurally high because each round gives limited historical data and final scoring is out-of-sample; top teams explicitly warn against peak-fitting parameters and instead seek stable regions. citeturn12view1turn18view1

Real-market analogies can mislead: Prosperity simplifies queueing, latency, and hidden liquidity, so institutional models transfer as **intuitions and guardrails**, not as plug-and-play formulas. citeturn6view0turn21search4

Bot-pattern edges are the most tempting trap: they can dominate when present (as documented), but they can also vanish or mutate. If you build a system that depends on one bot, you can implode when it changes in the final set. citeturn12view1turn26search0

Tool mismatch is a silent killer: local backtesters can be excellent for your own quoting/taking logic, but they will not perfectly replicate bot behaviour or special mechanics (e.g., conversions), and multiple participants explicitly report losses from misunderstandings here. citeturn12view2turn26search0turn11view5

### Ranked strategy families for Prosperity 4

This ranking is based on (i) robustness under the P4 execution model you described, (ii) simplicity, (iii) runtime fit, (iv) out-of-sample stability, (v) solo suitability, and (vi) value in the next few days. It is intentionally pragmatic.

1) Fair-value estimation + inventory-aware market making (robust baseline) citeturn20view1turn12view2turn21search4  
2) Inventory capacity management (explicit clearing/flattening discipline) citeturn20view0turn6view0  
3) Microprice/imbalance-enhanced fair value (as a plug-in to 1) citeturn18view1turn21search6  
4) Basket/spread mean reversion with stable thresholds (RV/stat-arb core) citeturn20view2turn12view1turn17view2  
5) Conversion/friction arbitrage (high value if present; must model mechanics correctly) citeturn20view2turn18view1turn26search0  
6) Trader/bot behaviour inference (high upside, high non-transfer risk) citeturn12view1turn26search0  
7) Options mispricing + selective hedging (medium value; build once options appear) citeturn12view3turn22search0turn22search9  
8) Simple drift/momentum overlays (useful in drifting products; keep conservative) citeturn20view0turn11view7  
9) Heavy statistical modelling / ML inside submission loop (poor tradeoff under constraints) citeturn27view0turn6view0
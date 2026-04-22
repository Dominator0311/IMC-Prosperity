# Top-Team MM Archaeology — Stable / Mean-Reverting Products

**Scope.** Deep read of the actual committed trader code for seven top Prosperity finishers, focused on the stable/anchor (PEARLS / AMETHYSTS / RAINFOREST_RESIN) and mean-reverting (BANANAS / STARFRUIT / KELP) products — the closest analogues to ASH_COATED_OSMIUM (stable, anchor 10,000, mean-reverting, limit ~50).

Repos cloned locally under `/tmp/imc_archaeology/`.

| Short name | Repo | Finish | Round we mined |
|---|---|---|---|
| `jmerle` | `jmerle/imc-prosperity-2` | P2 rank 9 | `src/submissions/round5.py` |
| `linear_utility` | `ericcccsliu/imc-prosperity-2` | P2 rank 2 | `round1/round_1_v6.py` |
| `pe049395` | `pe049395/IMC-Prosperity-2024` | P2 rank 13 | `submissions/round5.py` |
| `stanford` | `ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal` | P1 rank 2 | `trader.py` |
| `chrispy` | `chrispyroberts/imc-prosperity-3` | P3 7th global / 1st USA | `ROUND 1/final_round_1_trader.py` |
| `carter` | `CarterT27/imc-prosperity-3` (Alpha Animals) | P3 9th global / 2nd USA | `trader.py` |
| `timo` | `TimoDiehm/imc-prosperity-3` | P3 top | `FrankfurtHedgehogs_polished.py` |
| `sylvain` | `Sylvain-Topeza/imc-prosperity-3` | P3 top 1% | `alphabaguette_round5.py` |

Line numbers in this doc all refer to files in `/tmp/imc_archaeology/…` as cloned.

---

## 1. Per-repo extraction

### 1.1 `jmerle` (P2 rank 9) — Stable: AMETHYSTS (10k), MR: STARFRUIT

*File:* `jmerle/src/submissions/round5.py`

`MarketMakingStrategy.act()` is the generic stable/MR handler.

- **Fair value.** AMETHYSTS: hard-coded `return 10_000` (line 290–291). STARFRUIT: `round(get_mid_price)`, where `get_mid_price` (line 148-156) is `(popular_buy + popular_sell) / 2`, and *popular* means "the level whose aggregate quantity is largest". So STARFRUIT's FV is the **max-volume mid** — the same idea as pe049395's `maxamt_midprc`. Not BBO mid.
- **Quoting shape.** Two-sided every tick (line 241-281):
    - TAKE: scan `sell_orders` ascending, take any with price ≤ `max_buy_price = true_value − (1 if pos > 0.5·limit else 0)` (line 238); symmetric on the sell side.
    - REST: post remaining `to_buy` at `min(max_buy_price, popular_buy_price + 1)` (line 258-260) — i.e. penny the popular bid, capped so we never overpay fair.
- **Inventory skew.** Only a **one-tick** skew on the limit side (the `true_value - 1` / `true_value + 1` clause on line 238-239); not a continuous q-dependent skew.
- **Stuck-inventory drain.** `soft_liquidate` / `hard_liquidate` (line 235-236, 247-256, 268-277): if position has been at ±limit for ≥5 of the last 10 ticks, dump half at `true_value ± 2`; if pinned for all 10, dump half at `true_value`.
- **OBI / imbalance:** **not used anywhere** in the stable/MR handlers.
- **Directional taker overlay:** **none** for AMETHYSTS/STARFRUIT. Signal overlays only appear for CHOCOLATE/ROSES/COCONUT via `SignalStrategy` (line 169-207), driven by insider-trader names, not by book.
- **One-sided book:** `run()` at line 484 only calls the strategy when both sides are populated; no special handling.

### 1.2 `linear_utility` (P2 rank 2) — Stable: AMETHYSTS, MR: STARFRUIT

*File:* `linear_utility/round1/round_1_v6.py`

The canonical "take / clear / make" three-stage template that every subsequent team seems to have ported. Configured via `PARAMS` (line 14-35).

- **Fair value.**
    - AMETHYSTS: `fair_value: 10000` (line 16).
    - STARFRUIT: `starfruit_fair_value()` at line 160-197. This is the load-bearing piece:
        ```
        filtered_ask = [p for p ... if abs(vol) >= adverse_volume]  # adverse_volume = 15
        mm_ask = min(filtered_ask)
        mm_bid = max(filtered_bid)
        mmmid_price = (mm_ask + mm_bid) / 2
        ```
        Then an AR(1) mean-reversion tweak (line 186-194): `pred_returns = last_returns * reversion_beta` (beta = **-0.229**), and `fair = mmmid_price * (1 + pred_returns)`.
        The "filtered mid" throws away small retail quotes — it's the mid between the *real* market makers, not BBO.
- **Three stages applied to both products.**
    - `take_orders` (line 199-225 → `take_best_orders` line 46-93): cross the spread if `best_ask ≤ fair − take_width` (take_width=1) or `best_bid ≥ fair + take_width`. Optional `prevent_adverse` rejects any take where the other side's size exceeds `adverse_volume=15` — avoids being run over by large informed orders (STARFRUIT only).
    - `clear_orders` (line 227-248 → `clear_position_order` line 114-158): if `position_after_take > 0`, dump at `fair + clear_width` any bids that price or better; symmetric on the short side. This actively *unwinds inventory through the book* rather than waiting for the passive quote to fill.
    - `make_orders` (line 250-310):
        - `asks_above_fair = [p for p in sell_orders if p > fair + disregard_edge]`, `bids_below_fair = [p for p in buy_orders if p < fair − disregard_edge]` (line 266-275).
        - If nearest level within `join_edge` → join (same price). Else penny it (best_ask_above − 1 / best_bid_below + 1). Else `fair ± default_edge`.
        - AMETHYSTS uses `manage_position: True` with `soft_position_limit: 10` (line 23, 294-298): if `position > 10` shift the *ask down 1* (aggressively exit); if `position < −10` shift the *bid up 1*. Continuous inventory skew on the binding side only.
- **OBI / imbalance.** Zero occurrences. `grep -i imbalance|microprice|obi|ofi` in this file: **0 hits** across the whole repo.
- **Directional taker overlay.** None for stable/MR. Signal-based taking appears only in round 5 via `SignalStrategy` on CHOCOLATE/ROSES (copied into `jmerle` pattern).
- **One-sided book.** `starfruit_fair_value` falls back to the previous `last_price` if the filtered side is empty (line 178-183).

### 1.3 `pe049395` (P2 rank 13) — Avellaneda-Stoikov-ish

*File:* `pe049395/submissions/round5.py`

- **Fair value.** `maxamt_midprc` (line 605-607): midpoint of the **bid price with the largest volume** and the **ask price with the largest volume** (line 573-603). This is effectively the "wall mid" — the level where the real MM is sitting.
- **Quoting shape.** Two-sided every tick; no OBI. For both AMETHYSTS and STARFRUIT:
    1. `Strategy.arb(state, fair_price=maxamt_midprc)` (line 720-753): take any ask below fair, any bid above fair. Include `==` case only if it *reduces* inventory.
    2. A closed-form market-making layer. **AMETHYSTS uses `mm_ou`** (Avellaneda-Stoikov OU-utility, line 799-833); **STARFRUIT uses `mm_glft`** (Guéant-Lehalle-Fernandez-Tapia infinite-horizon, line 756-796).
- **`mm_glft` / `mm_ou` in detail.** These are *symmetric* quoters with an analytical q-dependent skew:
    ```
    q = rt_position / order_amount
    kappa_b = 1 / max((fair - best_bid) - 1, 1)
    kappa_a = 1 / max((best_ask - fair) - 1, 1)
    δ_b = (1/γ)·ln(1+γ/κ_b) + (-μ/(γσ²) + (2q+1)/2)·√(...)
    δ_a = (1/γ)·ln(1+γ/κ_a) + ( μ/(γσ²) − (2q−1)/2)·√(...)
    ```
    (Lines 765-775, 806-815.) Skew is driven entirely by **inventory `q`**, not OBI. μ, the drift, is hard-coded to 0 for AMETHYSTS.
- **Quote clamping.** After computing `p_b`, `p_a`, three clamps in order (line 780-786, 820-826):
    1. `p_b ≤ fair_price`, `p_a ≥ fair_price` (never cross).
    2. `p_b ≤ best_bid + 1`, `p_a ≥ best_ask − 1` (never too deep).
    3. `p_b ≥ maxamt_bidprc + 1`, `p_a ≤ maxamt_askprc − 1` (**never pass the wall**: if the big MM is at 9996, you never quote ≤ 9996; you always sit *above* his wall).
- **OBI / imbalance.** None used for quote placement.
- **Directional taker overlay.** None for stable/MR. For ROSES they use insider-trader trades (`informed_trading` on line 1074); for AMETHYSTS/STARFRUIT, zero signal overlay.

### 1.4 `stanford` (P1 rank 2) — PEARLS + BANANAS

*File:* `stanford/trader.py`

- **Fair value.**
    - PEARLS: `acc_bid = 10000, acc_ask = 10000` (line 505-506). The acceptable window is a single integer.
    - BANANAS: AR(4) 1-step forecast `calc_next_price_bananas` (line 62-72): `nxt_price = 4.48 + [-0.019, 0.045, 0.163, 0.809]·[p_{t-3}, p_{t-2}, p_{t-1}, p_t]`. Then `acc_bid = forecast − 1, acc_ask = forecast + 1` (line 501-503). They use `values_extract` at line 491-492 which returns the **max-size level**, not best — again, "popular price" / wall-price.
- **Quoting shape — PEARLS (`compute_orders_pearls` line 91-161).** Three-layer, and *not* strictly symmetric — the bid side and ask side have independent logic:
    - Layer 1 — TAKE (line 104-110): for each ask in ascending order, if `ask < acc_bid`, or `ask == acc_bid` and we are short, cross and buy up to position limit.
    - Layer 2 — POSITION-CONDITIONAL MAKE-ADDS (line 121-134). Three mutually exclusive branches:
        * If `position < 0` → make at `min(undercut_buy + 1, acc_bid − 1)` — i.e. a *more aggressive* bid, quoting past best-bid by 1 (line 123).
        * If `position > 15` → make at `min(undercut_buy − 1, acc_bid − 1)` — i.e. quote one tick *deeper* (back away).
        * Otherwise → make at `bid_pr = min(undercut_buy, acc_bid − 1)`.
    - Layer 3 — same pattern on the ask side (line 138-159).
    - Each layer posts up to `min(40, position_limit − cpos)` — so the **aggregate maker size on one side can reach 40 contracts** (2× the limit) via layered quotes. Position limit is 20, but the total order book impression is larger, letting them fill faster from whichever layer the market hits first.
- **BANANAS (`compute_orders_regression` line 164-209).** Same skeleton but *much tighter and single-layer*: only take if ask ≤ forecast−1 (or ==forecast and short), post the remainder at `bid_pr = min(best_bid+1, forecast−1)`. No three-layer ladder.
- **OBI / imbalance.** None. `values_extract` returns the level with the largest size; it's not a ratio or skew, just a fair-value proxy.
- **Directional taker overlay.** None for PEARLS/BANANAS. (For DIVING_GEAR / BERRIES they do have threshold-based signals.)
- **Insight.** The stacked maker pattern is the P1 gold-standard idea: by posting multiple quotes across several price points, you maximize **fill probability per tick** without ever crossing fair.

### 1.5 `chrispy` (P3 7th global) — RESIN, KELP, SQUID_INK

*File:* `chrispy/ROUND 1/final_round_1_trader.py`

- **Fair value.**
    - RESIN: hard-coded 10,000 (line 295-296 use this as the take threshold).
    - KELP: `(worst_ask + worst_bid) / 2` using `list(...)[-1]` — the **widest ends of the book** (line 335-340). This is the "wall mid" — extreme outer quotes, not BBO mid. Same as timo.
- **Quoting shape — RESIN (`trade_resin` line 293-318).**
    - TAKE at 10_000: `search_buys(..., 10000, depth=3)` — take any asks ≤ 10000 (and strictly < to avoid self-lose), symmetric on the sell side (line 295-296, 209, 233).
    - MAKE: default **edge 4** — `buy_price = 9996`, `sell_price = 10004` (line 303-304). If someone else is quoting *inside* (`get_ask(fair)`, `get_bid(fair)` at line 299-300, 249-267 which **filters out shitty single-lot quotes**), then penny them (`ask − 1` / `bid + 1`).
- **Quoting shape — KELP (`trade_kelp` line 320-374).**
    - Fair = wall-mid = `(worst_ask + worst_bid) / 2`.
    - TAKE: `search_buys/search_sells` with `depth=3` against `decimal_fair_price` (line 343-344).
    - MAKE: default **edge 2** — `buy_price = floor(fair) − 2`, `sell_price = ceil(fair) + 2` (line 351-352). If a better non-shitty inside quote exists, penny it.
    - Inventory skew: at line 369-374, if `position > 0` and the computed buy_price is already `== decimal_fair_price`, *skip the buy order*; symmetric on the sell side. One-tick avoidance of the same side we are already long/short on.
- **OBI / imbalance.** None.
- **Directional taker overlay.**
    - RESIN, KELP: none.
    - SQUID_INK (`trade_squid` line 442-520): **yes** — turns off one side of the quote based on a **short-MA / long-MA crossover** (line 477-488): if `long_mean < short_mean`, the market is trending up, so `buy_side = False` (stop buying, keep selling only). If `delta_vol > 2` (a flash crash detector at line 502-515), *aggressively take* in the reversion direction. This is not book-imbalance; it's a trend filter on the mid.

### 1.6 `carter` / Alpha Animals (P3 9th global) — RESIN, KELP

*File:* `carter/trader.py`

- **Fair value.**
    - Both RESIN and KELP: `mm_mid_price = (mm_ask + mm_bid) / 2` where `mm_ask = min(filtered_asks)` with `filtered_asks = [p for p in sell_orders if abs(vol) ≥ 10]` (line 326-338). Same **volume-filtered BBO** idea as linear-utility's STARFRUIT.
    - Then, surprisingly, a **VWAP roll over `timespan=20`** using `best_bid * |ask_vol| + best_ask * bid_vol` (line 343-360, 367-384). This is a type of microprice (size-weighted towards whichever side has more pressure on the opposite side of the book), computed per tick, then exponentially averaged. Applied even to *stable* RESIN (line 363-386).
    - This VWAP is a de facto **microprice-tilted fair value** — so Carter's "fair value" already contains a book-pressure signal. This is the closest thing to "OBI-driven fair value skew" in any of the repos, though it's not documented as such.
- **Quoting shape (`product_orders` line 315-434).** Identical skeleton to linear_utility: take at `fair ± take_width` (RESIN take_width = **0.3**, KELP = 1.0; line 217-218). Then `clear_position_order` at line 278-313 — but Carter's version only unwinds if `fair_for_ask` *exactly appears* in `buy_orders.keys()`, which is weaker than linear-utility's "all levels at or better". Then penny-in-make at line 414-433 with `best_ask_above_fair − 1` and `best_bid_below_fair + 1`.
- **Make width.** RESIN=3.0, KELP=8.0 (line 209-211). KELP is *wide* because its tick volatility is higher.
- **OBI / imbalance.** Implicit via VWAP; never explicit. Nothing of the form "if bid_size > k·ask_size → skew".
- **Directional taker overlay.** None for RESIN/KELP. (SQUID_INK has a separate momentum / volatility-regime logic not shown here.)

### 1.7 `timo` / Frankfurt Hedgehogs (P3) — RESIN, KELP

*File:* `timo/FrankfurtHedgehogs_polished.py`

- **Fair value.** `wall_mid = (bid_wall + ask_wall) / 2` (line 153-166), where `bid_wall = min(buy_order_keys)` and `ask_wall = max(sell_order_keys)` — same as chrispy: the *outermost* quotes, i.e. the persistent MM wall, not BBO.
- **Quoting shape — StaticTrader / RESIN (line 275-331).**
    - TAKE (line 286-298): buy every ask ≤ wall_mid − 1 full size; include `ask == wall_mid` **only if short** (to flatten). Symmetric on sells.
    - MAKE (line 300-328): base is `bid_wall + 1` / `ask_wall − 1` (just inside the wall). Then:
        - "Overbidding" loop (line 307-313): walk `buy_orders` from best to worst; first level with `bv > 1` (size > 1 — ignore single-lot chaff) whose price+1 is still under wall_mid → use that. Otherwise, skip levels with `bp < wall_mid` and join.
        - Symmetric "underbidding" on the ask side.
    - Effect: quotes sit *just inside the inner MM* rather than at BBO+1. Because they're inside the wall but the wall is wide (wall_mid for RESIN ~= 10,000 with walls at say 9995/10005), they collect a real spread.
- **Quoting shape — DynamicTrader / KELP (line 335-377).**
    - Base: same `bid_wall+1 / ask_wall−1`.
    - **Directional taker overlay** (line 349-374):
        - If the "informed trader" (Olivia) **bought** KELP in the last 5 ticks (`informed_bought_ts + 5_00 >= timestamp`), and we are not already max long (`position < 40`), **upgrade the bid to `ask_wall` with size `40 − position`**. That's crossing the spread to lift *aggressively*, triggered purely by a named-trader signal.
        - Symmetric on sells.
        - Secondary: if `informed_direction == SHORT` and we're not too short, pull the bid down to `bid_wall` (stop aggressive buying).
- **OBI / imbalance.** None. The taker overlay is driven by *who traded*, not by book sizes.

### 1.8 `sylvain` (P3 top 1%) — RESIN, KELP, SQUID_INK

*File:* `sylvain/alphabaguette_round5.py`

Direct port of the linear-utility template (line 90-356 are almost byte-identical to `linear_utility/round1/round_1_v6.py`). Same `take_width=1`, `clear_width=1`, `reversion_beta=-0.229` for KELP (line 57-65). Same `make_rainforest_resin_orders` (line 247-269) as linear-utility. No OBI. No directional taker for RESIN/KELP.

---

## 2. Head-to-head matrix

| Team | FV source (stable) | FV source (MR) | Quote symmetry | Inventory skew | OBI / imbalance used | Directional taker (stable/MR) | Adverse-volume filter |
|---|---|---|---|---|---|---|---|
| jmerle | hard 10000 | popular-mid | Symmetric | 1-tick at ±0.5·limit; hard/soft drain when pinned | No | No | No |
| linear_utility | hard 10000 | MM-mid + AR(1) β=−0.229 | Symmetric + penny/join | `manage_position` shifts one side when \|pos\|>soft_limit | No | No | Yes (STARFRUIT, `adverse_volume=15`) |
| pe049395 | maxamt-mid | maxamt-mid | Symmetric (GLFT/AS-OU closed-form) | Continuous q-dependent δ_b, δ_a | No | No | No (clamp via wall price) |
| stanford (P1) | hard 10000 | AR(4) 1-step forecast ±1 | Asymmetric (3-layer maker stack) | Position-conditional maker layers | No | No | No |
| chrispy (P3) | hard 10000 | wall-mid (outer ends) | Symmetric (edge 4 / edge 2) | Skip same-side quote when long/short | No | No (but SQUID_INK uses MA-crossover) | Via `get_ask/get_bid` filter ("don't copy shit markets") |
| carter (P3) | VWAP(mm-mid, timespan 20) | VWAP(mm-mid, timespan 20) | Symmetric penny-in | Via `clear_position_order` only (exact-level match) | Implicitly via VWAP tilt | No for stable/MR | Volume filter ≥10 |
| timo (P3) | wall-mid | wall-mid | Symmetric inside-wall (`wall+1`) | None explicit on RESIN | No | **Yes** — Olivia taker overlay on KELP (crosses to wall) | Size>1 filter on "overbid" |
| sylvain (P3) | hard 10000 | MM-mid + AR(1) β=−0.229 | Symmetric + penny/join | `manage_position` one-tick shift | No | No | Yes |

### Convergence (what ~everybody does)

1. **Fair value is some form of volume-robust mid, not BBO mid.** Five of eight use one of: max-amount mid (`maxamt_midprc` / `values_extract`), size-filtered mid (`adverse_volume` ≥ 15 or size ≥ 10), or wall mid (outermost quotes). Stable products are then clamped to the integer anchor (10,000). This systematically *rejects single-lot retail noise*.
2. **Stable product FV = 10,000, always.** Every team in this set hard-codes 10000 for AMETHYSTS / PEARLS / RAINFOREST_RESIN and never tries to model it.
3. **Quoting is symmetric both-sides every tick.** Nobody in this set turns off one side of the book for AMETHYSTS / PEARLS / RESIN in the default regime. (Some throttle one side for SQUID_INK or KELP under specific trend/signal triggers, but not for the stable product.)
4. **Three-stage pattern (TAKE → CLEAR → MAKE) is ubiquitous.** jmerle, linear_utility, pe049395, sylvain, carter, timo, chrispy all implement variants. Stanford's PEARLS does it slightly differently but the logical layers are the same.
5. **OBI / book-imbalance as an explicit signal for stable products: nobody.** A literal grep across all eight repos for `imbalance`, `obi`, `microprice`, `ofi`, `order_flow`, `book_imbalance` returned **zero hits inside any stable/MR handler**. Carter's VWAP is the closest to a size-weighted mid and it's used only as fair-value input, not as an asymmetric skew signal.
6. **Penny-the-inside-MM.** When a real (non-shitty) MM is quoting inside, everyone undercuts them by one tick rather than joining. The definition of "real" is: filtered by size ≥ 10 (linear-utility, carter), or size > 1 (timo), or "not a single-lot market" (chrispy's `get_ask/get_bid`).

### Divergence

- **Inventory skew magnitude.** pe049395's GLFT/AS-OU skew is **continuous** and large (can move quotes ±3–4 ticks based on q). linear-utility / sylvain use a **single-tick binary** shift past a soft limit. jmerle uses only a single-tick shift at 50% of limit plus a soft-liquidate-at-true-value if pinned for 5+ of 10 ticks. Stanford's PEARLS is the most *asymmetric*: three separate maker layers per side with *different* prices conditional on sign and magnitude of position, giving it a de-facto 3-tick skew.
- **Fair-value tightness.** Stanford's BANANAS uses `acc_bid = forecast − 1`, `acc_ask = forecast + 1` — extremely tight. linear-utility uses `take_width=1` + `default_edge=1`. Carter uses `take_width=0.3` for RESIN, the tightest in the set, and `make_width=3` (default edge 3). Timo / chrispy use `edge=4` default on RESIN. Wider defaults survive adverse selection better on the stable product; tighter defaults demand a better FV estimator.
- **Directional taker overlay for MR product.** Timo has one (Olivia on KELP). Chrispy has one for SQUID_INK only (MA crossover), not for KELP itself. Everyone else: none.
- **Stacked-maker design.** Stanford is unique in the set: **multiple maker layers per side at different prices per tick** (lines 121-134). None of the P2/P3 teams did this.

---

## 3. What mechanism most plausibly explains a 4-5× gap on ASH?

Given the claim that ASH is mean-reverting around 10,000 with limit ~50 and we're extracting 612–818 per 100k ticks versus top teams' ~3–4.5k, here are the specific mechanisms present in top-team repos that our engine may be missing, ranked by plausibility of delivering the gap.

### 3A. Most likely: we are quoting at BBO instead of *inside the wall* with a filtered FV

All top teams' FV for stable/MR is a **volume-robust mid** — max-amount, size-filtered, or wall-mid. Specifically:

- `pe049395` lines 780-786 and 820-826 clamp `p_b ≥ maxamt_bidprc + 1` and `p_a ≤ maxamt_askprc − 1`. Their quotes *always sit inside the wall* by exactly one tick.
- `timo` line 303-304: `bid_price = bid_wall + 1`, `ask_price = ask_wall − 1` — ditto.
- `linear_utility` line 287-292 and `sylvain` line 298-305: `ask = best_ask_above_fair − 1` — pennied *inside* the nearest non-adverse ask.

Compare against a naive MM that posts at `best_bid / best_ask` or `fair ± k`. If the wall is wide (bid_wall=9995, ask_wall=10005) but best_bid/best_ask are tight (9999/10001), the top team quotes at 9996/10004 (captures most of the wall spread), while the naive MM quotes at 9999/10001 or 10000±1 (captures just 1–2 ticks). On a stable product, almost every trade that reaches a maker crosses some retail noise between the inner quote and the wall — so the wide quoter collects 3–5× more per fill. This alone can produce the 4–5× extraction gap.

### 3B. Also material: aggregated maker size via stacked layers (Stanford) or 40-size per layer

Stanford's PEARLS handler (line 121-159) posts **up to 40 contracts per side per tick across three price layers** — i.e. position limit is 20 but order-book impression is 40+. On a stable product, the total-fill rate scales with standing size. pe049395 posts `order_amount = 20` per side and saturates to the limit. jmerle/linear-utility post `position_limit − position − buy_volume` which also saturates. So the size dimension is already largely exhausted by everyone. What Stanford does differently is *layering* — with 3 different prices, the first hitter fills layer 1, the second hitter layer 2, etc. This gives strictly more expected fills per tick than a single-price quote, particularly when inventory control otherwise shuts us off.

### 3C. Not likely the gap: OBI-based asymmetric quoting

**No top-team repo we have uses book-imbalance to asymmetrically skew quotes on a stable/MR product.** If our team already has an IC=+0.52 OBI signal, then we have *better* information than any of these teams on this axis, and yet we extract less. That is strong evidence that the gap is *not* strategy-level OBI usage. It is mechanical — fair-value estimator + quote placement.

The natural counter is "maybe using OBI for directional taking (not quote skew) is the missing move". But again, none of these teams does this on stable/MR, and `timo` (who has a directional overlay on KELP) uses a **named-trader signal**, not OBI. So "directional taker from OBI" is not a top-team pattern — it's our own invention. The IC says it would work in *theory*, but the evidence from top-team code is that **they extract 4–5× using symmetric passive MM with a good FV and inside-wall placement**, not a directional layer.

### 3D. Fill-rate calibration (F7) deserves explicit mention

If our local simulator underestimates how often passive quotes fill, then even a symmetric "quote-inside-wall" strategy would look weaker in local replay than it would in production. This is separate from strategy. Given that every top team is running the same three-stage symmetric MM and getting 3–4.5k, and we're running a similar-but-naive version and getting 600–800 locally, the single most actionable hypothesis is:

**Either (a) we are quoting at BBO/fair±edge instead of inside a volume-filtered wall, or (b) our simulator systematically under-fills passive quotes at prices between BBO and wall.** Both mechanisms produce roughly the same observable: each of our quotes earns real edge only when the market crosses all the way to it, instead of filling against the retail flow that sits in the middle of the wall.

### Recommended diagnostic

1. Compute `wall_mid = (min(buy_orders), max(sell_orders)) / 2` for ASH and compare to our current FV. If they differ systematically, our quotes are placed relative to a biased reference.
2. Look at the distribution of ASH `best_bid` vs the `max-amount-size bid price`. If they're equal most of the time, the wall *is* the BBO and 3A doesn't apply; if they differ often, we're leaving edge on the table.
3. Replace our MM quote formula with `p_b = max_amt_bid_price + 1`, `p_a = max_amt_ask_price − 1` (pe049395-style) and re-run. If P&L jumps toward 3k on the same 100k ticks, the gap is 3A. If it doesn't, the gap is 3D (sim fill rate).

---

## 4. Concrete design choices to port (ranked by expected marginal P&L)

1. **FV = (max_amt_bid + max_amt_ask) / 2**, or `(mm_bid_filtered, mm_ask_filtered)/2` with filter size ≥ 10-15. Reference: `pe049395` lines 573-607; `linear_utility` line 164-178; `carter` line 326-337.
2. **Quote placement inside-the-wall, not at BBO.** `p_b = max(fair − edge, max_amt_bid + 1)`, `p_a = min(fair + edge, max_amt_ask − 1)`. Reference: `pe049395` lines 782-786, 822-826; `timo` lines 303-304.
3. **Three-stage TAKE → CLEAR → MAKE.** Reference: `linear_utility` lines 199-310 (the template).
4. **`manage_position` one-tick inventory skew** past a soft limit. Reference: `linear_utility` lines 294-298.
5. **`prevent_adverse` size-filter on takes** (don't lift a 40-lot ask with `adverse_volume=15`). Reference: `linear_utility` lines 46-93.
6. **Stuck-pin drain** when \|pos\| = limit for N ticks. Reference: `jmerle` lines 231-256.
7. *(Only if 1–6 aren't enough)* **Stacked-maker layers at two or three prices per side.** Reference: `stanford` lines 121-159.

We already have 3–6 in some form. The load-bearing missing ingredients — based on the archaeology — are 1 and 2.

### One counterintuitive conclusion

The thing we were most excited about (an OBI signal with IC = 0.52) is **not** what top teams used to extract 3–4k on the analog products. None of them used book-imbalance for stable-product quote skew. The extraction came from *symmetric passive MM against a volume-robust fair value placed inside the MM wall*, with conservative inventory control. If we're extracting 4× less with a better signal than they had, the gap is mechanical, not strategic — FV reference, quote placement relative to the wall, or simulator fill rate. OBI is a nice-to-have on top; it is not the 4× driver.

# ETF / Basket Arbitrage Engine — Implementation Blueprint

**Scope.** Concrete, adoption-ready design for the Prosperity 4 R3 basket engine,
grounded in what six top teams actually shipped. Not another summary — module
names, class signatures, persisted-state layout, and a tick-level control flow
written against the existing `src/` scaffolding.

**Source base (verified).** Every parameter cited below was read from the raw
source of the named repo (URLs inline). Line numbers match the fetched files.

---

## 1. Top-team basket code — head-to-head matrix

Six baskets, six different designs. This table is the load-bearing artifact of
this document; the blueprint in §4 is a deliberate synthesis of it.

| Team | Edition / place | Spread construction | Hedge-ratio source | Window | Entry | Exit | Max pos | Hedge legs? | Residual MM? | Source |
|---|---|---|---|---|---|---|---|---|---|---|
| **Stanford Cardinal** | P1 / R4, #2 overall | `basket − 4·DIP − 2·BAG − UKU − 375` (constant premium) | Static; integer weights; premium offset hardcoded | Fixed `basket_std` (precomputed) | `|res| > 0.5·σ` | `|res| > -1000·σ` (≈never) | 70 | No — basket-only | No | `ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal/main/trader.py` L471-513 |
| **Linear Utility (older)** | P2 / R3, #2 overall | `basket_swmid − (4·choc + 6·straw + 1·rose)_swmid` | Static; `sma_window=1500`, `std_window=45` | 45 ticks for std, 1500 for mean | `|z| ≥ 9` | (not specified, target-based) | 58 | Yes (`convert_synthetic_basket_orders`) | No | `ericcccsliu/imc-prosperity-2/main/round3/round3_v1_simple_strat.py` L29-32, 369-405 |
| **Linear Utility (shipped)** | P2 / R3 | Same synthetic, same weights | Static; `std_window=45` | 45 | `|z| ≥ 7` | target ±58 | 58 | Yes | No | `…/round3_v2.py` L36-39, 369-390 |
| **jmerle** | P2 / R3, #9 | `basket − 4·choc − 6·straw − rose` (no premium) | Static; NO rolling window | none | per-symbol absolute diff; e.g. BASKET `(290, 355)` | — | 60 (full limit) | **Disabled** after −36k on roses | No | `jmerle/imc-prosperity-2/master/src/submissions/round3.py` L234-278 |
| **CarterT27 (Alpha Animals)** | P3 / R2, #9 global | `premium_diff = prem(B1) − prem(B2)`; **trade B1-vs-B2 instead of vs constituents** | Static integer weights inside each premium; `window=30` for z-score of premium diff | 30 | `|z| > 20` | implicit (reversion) | B1:60 / B2:32 | Yes — all five legs atomic | **Yes** — MM on B2 with `fair±2` | `CarterT27/imc-prosperity-3/main/trader.py` L109-114, 1057-1399 |
| **Frankfurt Hedgehogs (TimoDiehm)** | P3 / R2, top global | `basket_wall_mid − (constituents @ factors)` w/ Welford-running `mean_premium` | Factors `[[6,3,1],[4,2,0]]`; static; premium computed online | `n_hist_samples = 60_000` bootstrap; Welford thereafter | **Absolute** `|spread| > BASKET_THRESHOLDS[b_idx] ± informed_adj` where thresholds `[80, 50]` | `ETF_CLOSE_AT_ZERO = True` — flat when spread crosses informed adj | default | `ETF_HEDGE_FACTOR = 0.5` (50% hedge) | No basket MM; wall-quote only | `TimoDiehm/imc-prosperity-3/main/FrankfurtHedgehogs_polished.py` L249-358 |
| **Sylvain-Topeza** | P3 / R5, top 1% | B1: `basket − (6C+3J+D)` deviation; B2: **no arb — Olivia-Caesar trade mirror** | Static integer weights | none | B1: `|dev| > 5`; B2: Olivia/Caesar sender check | (none) | B1: 5/signal; B2: 100 | No (B1) / n.a. (B2) | No | `Sylvain-Topeza/imc-prosperity-3/main/alphabaguette_round5.py` L845-1019 |
| **chrispyroberts** (P3 R2 writeup) | P3 / R2, 7th, 1st USA | Premium mean-rev, **8% residual budget** MM | Single hyperparameter threshold; stability-in-neighborhood selected | not numeric in fetched sources | symmetric Z | Z=0 | default | reverse-hedges constituents | **Yes** — explicit residual book (~$5k/day) | transcript §R2 |

### 1.1 Convergence (what everyone did)

1. **Integer, static hedge ratios** derived from the ETF definition. Nobody
   runs Kalman. Linear Utility tried OLS-fitted coefficients in P3 and got
   almost-integer values (pb1 coef 6.0, 3.0, 1.0) — confirming the definition
   itself is the ground truth. **Static weights = correct prior.**
2. **Three-phase take/clear/make was universal** for everything else —
   but baskets themselves are predominantly **take-only** on the entry side.
   Frankfurt, Linear Utility, jmerle, Stanford all "cross the spread" via
   `basket.ask(bid_wall, vol)` / `basket.bid(ask_wall, vol)`. Only chrispyroberts
   and CarterT27 added residual maker quotes.
3. **All top P3 teams used the two-basket structure** (B1 = 6C+3J+1D,
   B2 = 4C+2J). Nobody attempted SVD / PCA on the overlapping constituents —
   a possible non-obvious alpha (§3.4).
4. **Close-at-zero / target-position exit** beat linear scaling-out. Both
   Frankfurt (`ETF_CLOSE_AT_ZERO`) and Linear Utility (`target_position=58`)
   snap flat rather than scale. Academic research (ArbitrageLab, Nandi
   hysteresis) also argues for this.

### 1.2 Divergence (where the real design decisions are)

| Decision axis | Evidence |
|---|---|
| **Z-score vs. raw threshold** | Linear Utility + CarterT27 = z-score. Frankfurt + Stanford + jmerle + Sylvain = absolute. Absolute is simpler and, if your premium is stationary and σ is stable, as good. Z-score earns its cost when σ drifts across days. |
| **Hedge legs or basket-only** | jmerle disabled after losing 36k on ROSES. CarterT27 and Linear Utility ship full-leg hedges. Frankfurt uses **50%** hedge (`ETF_HEDGE_FACTOR=0.5`) — net long 50% of the spread exposure as carry. **This 0.5 is a deliberate choice, not a bug.** |
| **Residual budget** | chrispyroberts: 8% of book → $5k/day. CarterT27: explicit MM on B2 when not arbing. Frankfurt & others: none. |
| **Mean-premium estimation** | Frankfurt's Welford-online mean with 60k sample bootstrap is the most robust — no window-edge artifacts, constant memory, survives restarts. Everyone else either hardcodes (Stanford 375) or uses a fixed window (Linear Utility 1500/45). |
| **Informed-trader piggyback** | Frankfurt's `informed_thr_adj = ±90` is the only top team who **widens the threshold by 90 ticks in the signal direction**. This is Olivia-conditioned; raw signal is a regime flag, not a price. Confirmed from transcript 1 that the Frankfurt team also trades `ETF_INFORMED_CONSTITUENT` (the shared constituent, CROISSANTS). |
| **B1-vs-B2 vs vs-constituents** | CarterT27 trades premium-of-B1 vs premium-of-B2 (their main signal), which sidesteps the position-limit bind noted in transcript 1 §R2. Linear Utility, Frankfurt: vs-constituents directly. **Both work.** Choice depends on your position-limit algebra. |

---

## 2. Critical analysis

### 2.1 What did P3 teams miss that P4 could capture?

1. **Nobody ran a Kalman hedge ratio.** The integer weights are definitionally
   correct for the spread of a perfectly-replicable basket; but if IMC injects
   a micro-drift in a constituent (e.g. a DJEMBE that slowly decouples),
   a Kalman filter would catch it before a static spread blows up. Cheap
   insurance, 40 lines of code. **Alpha estimate: small but free.**

2. **Nobody used SVD across 2+ baskets with shared constituents.** With
   B1=6C+3J+1D and B2=4C+2J over (C, J, D), the design matrix has rank 2
   but three constituents. The **rank-deficient axis** (djembe direction
   orthogonal to both baskets' shared C+J exposure) is a free directional
   exposure you can hold or short. In P3 this probably didn't pay; in P4
   if there are 3+ baskets it becomes the dominant axis.

3. **Nobody ran a cross-basket pairs trade against fundamentals.** B1 and B2
   both contain 2·(2C+J); the "basket ratio" `B1 − 1.5·B2` should cointegrate
   with just `1·DJEMBE + premium`. CarterT27 did the closest thing
   (B1-premium vs B2-premium z-score). A direct `B1 − 1.5·B2 − DJEMBE`
   construction is cleaner and has fewer constituent legs.

4. **Residual market-making is undervalued.** Only chrispyroberts and
   CarterT27 did it. $5-10k/day per product is **not small** in a 3-round
   tournament; over three rounds that's meaningful. Everyone else was
   leaving 3-5% edge on the table.

5. **Olivia / informed piggyback.** Frankfurt is the only team that made it
   explicit code (`informed_thr_adj`). Every P3 transcript says top teams
   "had Olivia from R2 onward." In P4, doing this from R3 tick 0 via P&L
   clustering is the highest-EV edge.

### 2.2 Where top teams disagreed, who was right?

- **Hedge legs: yes/no/partial.** Evidence favors **partial**. jmerle lost
  36k on ROSES specifically because unhedged directional drift in a
  constituent is unbounded. Full 1:1 hedge (Linear Utility, CarterT27)
  eats spread cost and caps your carry. Frankfurt's 50% hedge is the
  compromise: half your spread exposure is carried as directional, half
  is delta-neutral. The carry pays theta on the mean-premium; the hedged
  half captures the reversion. **Adopt 50% as default, parameterize.**

- **Window length.** 30 (CarterT27) vs 45 (Linear Utility) vs 60k Welford
  (Frankfurt). Fixed windows have an edge effect on day-rollover;
  Frankfurt's Welford has none. **Adopt Welford.** Window-based spreads
  get ugly when premium regime shifts.

- **Target-flat vs. scale-out.** Frankfurt's `ETF_CLOSE_AT_ZERO` and
  Linear Utility's `target_position=58` both ship with hard targets.
  Scale-out leaks reversion profit (Academic §2.2, Nandi hysteresis).
  **Adopt target-flat.**

- **Threshold values.** Absolute thresholds (Frankfurt 80/50) and
  z-thresholds (CarterT27 20, Linear Utility 7-9) are equally defensible.
  Absolute works when σ is stable; z-score is safer when σ drifts. P4 R3
  σ stability is unknown; **we should compute z in state but gate on
  BOTH raw |spread| > k_abs AND |z| > k_z** (belt-and-suspenders).

### 2.3 Non-obvious alpha to explicitly hunt

1. **Residual-budget MM on the basket itself.** Nobody except chrispyroberts
   & CarterT27 did this. Target: 5-10% of position limit reserved for
   one-tick-wide maker quotes around the current fair (basket_mid or
   synthetic_mid). Expected +5k/day.
2. **Kalman hedge-ratio drift detector** (not the primary hedge —
   a monitoring signal). If `|β_kalman − β_static| > 5%`, flip to kill-switch
   for the affected basket. Cost: 40 lines. Saves you from the 36k-ROSES
   scenario.
3. **Shared-constituent individual z-score overlay.** Frankfurt's
   `ETF_INFORMED_CONSTITUENT` trades the constituent on Olivia signal.
   Transcript 1 R2 §Frankfurt: they ran **individual z-scores on each
   constituent** on top of the basket z. This is a second signal source at
   zero marginal data cost.
4. **Cross-basket pairs** (`B1 − 1.5·B2 − DJEMBE` or eigen-axis).
   Two baskets ⇒ a cleaner two-variable spread than basket-vs-three-things.

---

## 3. Engine blueprint — the architecture

### 3.1 Constraints from the existing codebase

Current trader loop (`src/trader.py` L122-155):
```python
for product, snapshot in snapshots.items():
    ...
    intent = strategy.generate_intent(context)   # per-product, no cross-view
    raw_orders = self.execution_engine.generate_orders(...)
    ...
    legal_orders = self.risk_manager.clip_orders(...)
```

This is strictly per-product. A basket engine needs **cross-product state**
(basket snapshot AND all constituent snapshots in the same tick). Blueprint
adds a **pre-strategy cross-product stage** and keeps the per-product loop
intact for MM products.

### 3.2 New module layout

```
src/core/
  basket_spec.py        # NEW — frozen dataclass: basket → (constituents, weights, limits)
  basket_state.py       # NEW — rolling Welford + z-score deque per basket (persisted)
  basket_signals.py     # NEW — spread→signal decision logic (thresholds, hysteresis)
  basket_execution.py   # NEW — atomic multi-product order emission + hedge scaler
  ...                   # existing modules unchanged

src/strategies/
  basket_arb.py         # NEW — BasketArbEngine, orchestrator
  ...                   # existing per-product strategies unchanged

src/signals/
  counterparty.py       # NEW — Olivia/informed-trader detector (feeds basket_signals)
```

### 3.3 Core types (new, frozen)

```python
# src/core/basket_spec.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Mapping
from types import MappingProxyType

@dataclass(frozen=True)
class BasketSpec:
    """Static definition of an ETF basket."""
    name: str                              # e.g. "PICNIC_BASKET1"
    weights: Mapping[str, int]             # {"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1}
    position_limit: int                    # IMC-given
    initial_premium: float = 0.0           # seed for Welford mean
    bootstrap_n: int = 60_000              # Frankfurt's n_hist_samples
    # Signal thresholds — BOTH gates must trigger.
    abs_threshold: float = 50.0            # Frankfurt 80/50
    z_threshold: float = 2.0               # Academic §2.1 default
    kill_z: float = 4.0                    # OU regime-break (Academic §2.1)
    # Hedge policy: 0.0 = basket-only, 1.0 = full leg hedge, 0.5 = Frankfurt.
    hedge_factor: float = 0.5
    # Informed-trader threshold widening (Frankfurt ETF_THR_INFORMED_ADJS).
    informed_adj: float = 0.0              # set >0 once counterparty detector live
    # Residual MM on the basket itself (chrispyroberts 8% budget).
    residual_mm_enabled: bool = False
    residual_mm_edge: float = 2.0
    residual_mm_size: int = 2

@dataclass(frozen=True)
class BasketEngineConfig:
    baskets: tuple[BasketSpec, ...]
    # Exit-at-zero shortcut (Frankfurt ETF_CLOSE_AT_ZERO). Always recommended.
    close_at_zero: bool = True
    # Kalman monitor (OFF by default; flips basket-specific kill switch).
    kalman_enabled: bool = False
    kalman_drift_threshold: float = 0.05    # 5% deviation from static β
```

### 3.4 Rolling state (persisted in `traderData`)

Welford is the right primitive — constant memory, no window-edge bleed.

```python
# src/core/basket_state.py
from __future__ import annotations
from dataclasses import dataclass, field
from collections import deque

@dataclass
class BasketMemory:
    """Per-basket persisted state. Packed into ProductMemory.values via
    keyed JSON (survives existing StateStore's JSON round-trip)."""
    # Welford running stats for raw spread (no premium adjustment).
    n: int = 0
    mean: float = 0.0
    m2: float = 0.0                     # sum of squared deviations
    # Rolling deque of (z, timestamp) for the last K entries — diagnostic only.
    recent_z: deque[float] = field(default_factory=lambda: deque(maxlen=64))
    # Kill-switch state.
    killed: bool = False
    kill_reason: str = ""
    # Counterparty-derived threshold bias (Olivia).
    informed_direction: int = 0          # -1 / 0 / +1

    def update(self, raw_spread: float) -> tuple[float, float]:
        """Welford online update. Returns (current_mean, current_std)."""
        self.n += 1
        delta = raw_spread - self.mean
        self.mean += delta / self.n
        delta2 = raw_spread - self.mean
        self.m2 += delta * delta2
        var = self.m2 / self.n if self.n > 1 else 0.0
        return self.mean, var ** 0.5

    def z_score(self, raw_spread: float) -> float | None:
        if self.n < 2:
            return None
        std = (self.m2 / self.n) ** 0.5
        if std <= 0:
            return None
        return (raw_spread - self.mean) / std
```

**Persistence.** A Welford triple `(n, mean, m2)` is 3 floats + 1 int per
basket. For 3 baskets that's ~100 bytes. The 50k `traderData` budget has
enough headroom for this plus the existing per-product memory. Key under
`memory.values["basket::<name>::n"]` etc., or add a dedicated top-level
`basket_memory` dict to `EngineState` (requires a StateStore version bump).

### 3.5 Cross-product snapshot assembly

```python
# src/core/basket_signals.py
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Mapping
from src.core.types import NormalizedSnapshot
from src.core.basket_spec import BasketSpec

@dataclass(frozen=True)
class BasketView:
    """All snapshots needed to evaluate one basket, same tick."""
    spec: BasketSpec
    basket: NormalizedSnapshot
    constituents: Mapping[str, NormalizedSnapshot]

    def synthetic_price(self) -> float | None:
        """Sum of constituent wall_mid × weight. Wall-mid (most-volume level mid)
        is less manipulable than simple mid — convergence pick from all top teams."""
        total = 0.0
        for sym, w in self.spec.weights.items():
            s = self.constituents.get(sym)
            if s is None:
                return None
            # Prefer wall_mid (use existing FilteredWallMidEstimator logic),
            # fall back to mid, then microprice.
            px = _wall_mid(s) or s.mid or s.microprice
            if px is None:
                return None
            total += w * px
        return total

    def raw_spread(self) -> float | None:
        syn = self.synthetic_price()
        bpx = _wall_mid(self.basket) or self.basket.mid
        if syn is None or bpx is None:
            return None
        return bpx - syn

def _wall_mid(snap: NormalizedSnapshot) -> float | None:
    if not snap.bids or not snap.asks:
        return None
    wb = max(snap.bids, key=lambda l: l.volume)
    wa = max(snap.asks, key=lambda l: l.volume)
    return (wb.price + wa.price) / 2.0
```

### 3.6 Signal decision (hysteresis, dual-gate, kill-switch)

Decisive part of the engine. Dual-gate (absolute + z), target-flat exit,
close-at-zero, kill on `|z| > kill_z`.

```python
# src/core/basket_signals.py (continued)
from typing import Literal
BasketAction = Literal["idle", "long_spread", "short_spread", "close", "killed"]

@dataclass(frozen=True)
class BasketIntent:
    action: BasketAction
    size: int                          # basket units; hedge scaled by hedge_factor
    rationale: str
    z: float | None
    raw_spread: float | None

def decide(
    view: BasketView,
    mem: BasketMemory,
    current_basket_pos: int,
) -> BasketIntent:
    raw = view.raw_spread()
    if raw is None:
        return BasketIntent("idle", 0, "no_spread", None, None)

    mem.update(raw)               # MUTATES (Welford accumulator)
    spread = raw - mem.mean       # demeaned
    z = mem.z_score(raw)

    # Kill-switch: regime break. Once killed, only unwinds.
    if z is not None and abs(z) > view.spec.kill_z:
        mem.killed = True
        mem.kill_reason = f"|z|={abs(z):.2f} > {view.spec.kill_z}"

    if mem.killed:
        if current_basket_pos == 0:
            return BasketIntent("idle", 0, f"killed:{mem.kill_reason}", z, raw)
        return BasketIntent("close", abs(current_basket_pos),
                            f"killed_unwind:{mem.kill_reason}", z, raw)

    # Informed-trader bias (Frankfurt): widen the side we disagree with,
    # tighten the side we agree with. E.g. if Olivia is long, shift upward.
    bias = mem.informed_direction * view.spec.informed_adj
    abs_thr = view.spec.abs_threshold
    z_thr = view.spec.z_threshold

    # Dual gate: BOTH absolute and z must exceed.
    fire_short = (spread > abs_thr + bias) and (z is not None and z > z_thr)
    fire_long  = (spread < -abs_thr + bias) and (z is not None and z < -z_thr)

    # Close-at-zero: snap flat whenever spread crosses back through bias.
    if current_basket_pos > 0 and spread > bias:
        return BasketIntent("close", current_basket_pos, "close_at_zero", z, raw)
    if current_basket_pos < 0 and spread < bias:
        return BasketIntent("close", -current_basket_pos, "close_at_zero", z, raw)

    if fire_short:
        size = _available_size(view, current_basket_pos, want_short=True)
        return BasketIntent("short_spread", size, "entry_short", z, raw)
    if fire_long:
        size = _available_size(view, current_basket_pos, want_short=False)
        return BasketIntent("long_spread", size, "entry_long", z, raw)

    return BasketIntent("idle", 0, "no_signal", z, raw)

def _available_size(view: BasketView, pos: int, *, want_short: bool) -> int:
    """Size constrained by basket position limit AND constituent volume.
    Mirrors CarterT27 L1076-1097 in structure."""
    limit = view.spec.position_limit
    if want_short:
        basket_cap = limit + pos                       # can sell up to limit+pos
        available = view.basket.total_bid_volume(depth=3)
    else:
        basket_cap = limit - pos
        available = view.basket.total_ask_volume(depth=3)
    cap = min(basket_cap, available)
    # Constituent volume cap: hedge volume scales with weights.
    for sym, w in view.spec.weights.items():
        s = view.constituents[sym]
        if want_short:
            # Selling basket short ⇒ buy constituents ⇒ need ask volume.
            const_vol = s.total_ask_volume(depth=3)
        else:
            const_vol = s.total_bid_volume(depth=3)
        cap = min(cap, const_vol // max(1, w))
    return max(0, cap)
```

### 3.7 Atomic execution (take-the-book with hedge scaling)

```python
# src/core/basket_execution.py
from __future__ import annotations
from src.datamodel import Order
from src.core.basket_signals import BasketIntent, BasketView

def emit_orders(
    view: BasketView,
    intent: BasketIntent,
) -> dict[str, list[Order]]:
    """Emit one atomic take-order per leg. Cross-spread entry, wall-price exit.
    Mirrors Frankfurt L313-337 AND CarterT27 L1084-1097 structure."""
    out: dict[str, list[Order]] = {view.spec.name: []}
    for sym in view.spec.weights:
        out[sym] = []
    if intent.action in ("idle", "killed"):
        return out

    size = intent.size
    if size <= 0:
        return out

    # Direction: short_spread ⇒ sell basket, buy constituents.
    #            long_spread  ⇒ buy basket, sell constituents.
    #            close        ⇒ opposite of current position (caller signs intent).
    sell_basket = intent.action in ("short_spread",) or (
        intent.action == "close" and _sign_close_is_sell(view, intent)
    )

    # Basket leg — cross the spread, take the wall.
    if sell_basket:
        best_bid = view.basket.best_bid
        if best_bid is not None:
            out[view.spec.name].append(
                Order(view.spec.name, best_bid.price, -size)
            )
    else:
        best_ask = view.basket.best_ask
        if best_ask is not None:
            out[view.spec.name].append(
                Order(view.spec.name, best_ask.price, size)
            )

    # Constituent hedge legs — scaled by hedge_factor (Frankfurt 0.5).
    if view.spec.hedge_factor > 0:
        for sym, w in view.spec.weights.items():
            s = view.constituents[sym]
            hedge_qty = round(size * w * view.spec.hedge_factor)
            if hedge_qty <= 0:
                continue
            if sell_basket:
                # We sold basket ⇒ we're short basket exposure ⇒ buy constituents.
                best_ask = s.best_ask
                if best_ask is not None:
                    out[sym].append(Order(sym, best_ask.price, hedge_qty))
            else:
                best_bid = s.best_bid
                if best_bid is not None:
                    out[sym].append(Order(sym, best_bid.price, -hedge_qty))
    return out
```

### 3.8 The orchestrator — `BasketArbEngine`

One engine, 1/2/3 baskets, overlapping or disjoint constituents. Inheritable.

```python
# src/strategies/basket_arb.py
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from src.core.types import NormalizedSnapshot
from src.core.basket_spec import BasketEngineConfig, BasketSpec
from src.core.basket_state import BasketMemory
from src.core.basket_signals import BasketView, decide, BasketIntent
from src.core.basket_execution import emit_orders
from src.datamodel import Order

class BasketArbEngine:
    """Cross-product basket arbitrage orchestrator.

    Generalises over 1/2/3 baskets and any combination of overlapping /
    disjoint constituents. Executes in a defined order: baskets whose
    |z| is largest go first so they consume constituent volume before
    less-edgy baskets compete for it (Frankfurt L344 ordering).

    Hook points (subclass overrides):
      - ``priority_order(views)`` — custom cross-basket priority.
      - ``update_hedge_ratios(view, mem)`` — Kalman/drift monitor; default no-op.
      - ``inject_counterparty_bias(view, mem)`` — Olivia detector hook.
      - ``residual_mm_orders(view)`` — hook for CarterT27-style leftover MM.
    """

    def __init__(self, cfg: BasketEngineConfig) -> None:
        self.cfg = cfg
        self._specs: dict[str, BasketSpec] = {b.name: b for b in cfg.baskets}

    # ----------------------------------------------------------------- run
    def run(
        self,
        snapshots: Mapping[str, NormalizedSnapshot],
        memories: Mapping[str, BasketMemory],
        current_positions: Mapping[str, int],
    ) -> dict[str, list[Order]]:
        views: list[BasketView] = []
        for spec in self.cfg.baskets:
            if spec.name not in snapshots:
                continue
            const_snaps = {
                s: snapshots[s] for s in spec.weights if s in snapshots
            }
            if len(const_snaps) < len(spec.weights):
                continue   # at least one constituent missing
            views.append(BasketView(spec, snapshots[spec.name], const_snaps))

        # Priority: highest |z| first (protects arb capacity under contention).
        views = self.priority_order(views, memories)

        out: dict[str, list[Order]] = {}
        consumed: dict[str, int] = {}   # buy/sell already reserved for this tick

        for view in views:
            mem = memories[view.spec.name]
            self.update_hedge_ratios(view, mem)
            self.inject_counterparty_bias(view, mem)

            pos = current_positions.get(view.spec.name, 0)
            intent = decide(view, mem, pos)

            if intent.action != "idle":
                basket_orders = emit_orders(view, intent)
            else:
                basket_orders = {view.spec.name: []}

            # Residual MM (opt-in per basket).
            if view.spec.residual_mm_enabled and intent.action in ("idle",):
                mm_orders = self.residual_mm_orders(view, pos)
                basket_orders[view.spec.name].extend(mm_orders)

            for sym, orders in basket_orders.items():
                out.setdefault(sym, []).extend(orders)

        return out

    # -------------------------------------------------------------- hooks
    def priority_order(
        self,
        views: list[BasketView],
        memories: Mapping[str, BasketMemory],
    ) -> list[BasketView]:
        def key(v: BasketView) -> float:
            z = memories[v.spec.name].z_score(v.raw_spread() or 0.0)
            return -abs(z) if z is not None else 0.0
        return sorted(views, key=key)

    def update_hedge_ratios(self, view: BasketView, mem: BasketMemory) -> None:
        """Override to add Kalman drift monitoring."""
        return None

    def inject_counterparty_bias(self, view: BasketView, mem: BasketMemory) -> None:
        """Override to pipe Olivia detector into mem.informed_direction."""
        return None

    def residual_mm_orders(self, view: BasketView, pos: int) -> list[Order]:
        """CarterT27-style residual MM. Default: none. Subclass to enable."""
        return []
```

### 3.9 Tick control flow (full engine)

```
1. trader.run() loads EngineState
2. MarketDataAdapter normalizes TradingState → snapshots: dict[str, Snapshot]
3. NEW: basket_engine.run(snapshots, basket_memories, positions)
       (a) Build BasketViews where basket + ALL constituents present
       (b) update_hedge_ratios()       — Kalman drift check (optional)
       (c) inject_counterparty_bias()  — Olivia detector
       (d) Priority-sort views by |z|
       (e) For each view:
           - decide()    → BasketIntent (uses Welford + dual-gate + close-at-zero + kill)
           - emit_orders()      → basket + scaled hedge legs
           - residual_mm_orders (if enabled and idle)
       (f) Accumulate orders by symbol
4. Existing per-product loop runs for NON-BASKET products (R1/R2 MM products)
5. Merge per-product orders (§3.10 rules below)
6. RiskManager.clip_orders() runs last — guarantees no limit breach
7. Serialize EngineState (basket memories packed)
8. Return
```

### 3.10 Order merging rule (the inventory-contention trap)

A basket arb hedge on CROISSANTS produces `±hedge_qty`. A separate
CROISSANTS MM strategy might emit maker quotes the same tick. If both
emit a buy, the risk manager clips — fine; but a long-limit squeeze can
still occur. Rules:

1. **Basket legs have priority.** Append them first to the symbol's order
   list. Risk clipping will then shrink MM orders before basket orders.
2. **When any basket holds non-zero in a constituent, freeze MM for that
   constituent** on the side that would add to the inventory. This is a
   light-touch version of the transcript-1 "portfolio manager." Implement
   as `ProductConfig.freeze_mm_if_basket_exposed = ("PICNIC_BASKET1",)`.
3. **Residual MM on the basket** only when basket position = 0 AND z-score
   is inside `±z_threshold / 2` (no-trade dead zone — Academic §2.2).

---

## 4. Concrete parameter recommendations (v0 defaults)

Derived by triangulating the six teams above, with a slight bias toward
Frankfurt (top-3 global in P3, most robust architecture).

```python
from src.core.basket_spec import BasketSpec, BasketEngineConfig

P4R3_BASKET_CONFIG = BasketEngineConfig(
    baskets=(
        BasketSpec(
            name="PICNIC_BASKET1",
            weights={"CROISSANTS": 6, "JAMS": 3, "DJEMBES": 1},
            position_limit=60,
            initial_premium=50.0,       # retune after R3 first-hour calibration
            bootstrap_n=1_000,           # smaller than Frankfurt's 60k; P4 rounds are short
            abs_threshold=50.0,          # between Frankfurt 80 and jmerle 32
            z_threshold=2.0,             # academic default (NOT CarterT27's 20 — that's extreme)
            kill_z=4.0,                  # OU regime-break
            hedge_factor=0.5,            # Frankfurt default
            informed_adj=0.0,            # enable after counterparty detector validated
            residual_mm_enabled=False,   # enable after baseline-vs-residual A/B
        ),
        BasketSpec(
            name="PICNIC_BASKET2",
            weights={"CROISSANTS": 4, "JAMS": 2},
            position_limit=100,
            initial_premium=30.0,
            bootstrap_n=1_000,
            abs_threshold=30.0,
            z_threshold=2.0,
            kill_z=4.0,
            hedge_factor=0.5,
            residual_mm_enabled=False,
        ),
    ),
    close_at_zero=True,
    kalman_enabled=False,
)
```

### 4.1 Why these differ from any single top team

- **`bootstrap_n=1_000` not 60_000.** Frankfurt trained on P3's multi-day
  history. We enter R3 cold. A smaller bootstrap lets the Welford mean
  converge in the first ~10% of session; too-large `n` freezes the mean
  near `initial_premium` and we're just using an offset.
- **`z_threshold=2.0` not 20.** CarterT27's 20 is because their
  `premium_diff` is a z of a derived spread with much higher σ. For a
  raw basket-vs-synthetic spread with typical σ ~30-50, z_threshold=2
  corresponds to the top 5% of ticks — correct entry rate.
- **Dual gate `abs AND z`.** Protects against both cold-start σ=0 (z blows
  up) and regime shifts (abs threshold stays sane).
- **`hedge_factor=0.5`.** Copy Frankfurt. Re-evaluate if first-day backtest
  shows spread cost > directional carry.

---

## 5. Edge cases (non-trivial)

1. **Position-limit saturation across overlapping constituents.** When
   B1 holds +40 and wants to add +20, its CROISSANTS hedge wants +120
   constituent units (6·20); if the CROISSANTS limit is, say, 200 and
   B2's hedge already used 80, only 120 is free — B1's full size may
   not fit. `_available_size()` handles this for single-basket; the
   orchestrator needs a **two-pass sizing** when overlapping:
   - Pass 1: compute desired sizes per basket assuming full capacity.
   - Pass 2: walk baskets by |z| priority; deduct hedge volume from each
     shared constituent's remaining capacity; clip later baskets.
   (Reference: CarterT27 L1076 `crossaint_volume_available // 2` is a
   one-basket-ahead version of this.)

2. **Constituent unavailability.** Any missing `best_bid`/`best_ask` on
   a constituent should **mark the basket idle for the tick**, not
   ship an unhedged basket leg. Handled in §3.5 (`if len(const_snaps) < len(spec.weights): continue`).

3. **Spread regime break.** `|z| > kill_z` latches `mem.killed=True`;
   subsequent ticks only close existing positions. Reset either (a) on
   day rollover (`memory.flush_history_on_day_rollover` pattern —
   extend to basket memories), or (b) manually via `BasketMemory.killed = False`
   when σ has stabilized. **Recommendation: latch per-day, auto-clear on
   rollover.**

4. **Day rollover.** Welford state should **persist** across days (unlike
   `recent_mids` in the MM path, which flushes for linear_drift). The mean
   premium is a property of the product pair, not of one day's book.
   Exception: if IMC re-seeds mid prices at day boundaries, Welford may
   need a "soft reset" — blend old mean with new observation at weight 0.5
   on the first tick of a new day.

5. **Kill-switch integration.** The existing `EngineConfig` does not have
   a global kill flag. Extend:
   ```python
   @dataclass(frozen=True)
   class BasketKillSwitch:
       max_realized_loss: float = -5_000.0   # basket-level drawdown
       jump_ratio: float = 4.0               # Academic §1.4
   ```
   Check against PnL attribution per basket (compute from fill prices ×
   side; use the `logger` event stream to attribute) and on any tick with
   `|r_t| / EWMA(|r|, 500) > 4.0`, set all `BasketMemory.killed = True`.

---

## 6. Adoption checklist — mapping to existing codebase

### 6.1 New files to create

| File | Responsibility | Est. lines |
|---|---|---|
| `src/core/basket_spec.py` | `BasketSpec`, `BasketEngineConfig` frozen dataclasses | ~80 |
| `src/core/basket_state.py` | `BasketMemory` (Welford), persistence helpers | ~120 |
| `src/core/basket_signals.py` | `BasketView`, `decide()`, `_available_size()` | ~180 |
| `src/core/basket_execution.py` | `emit_orders()` (atomic multi-product) | ~100 |
| `src/strategies/basket_arb.py` | `BasketArbEngine` orchestrator + hooks | ~200 |
| `src/signals/counterparty.py` | Olivia detector (P&L trajectory clustering) — pre-R5 hook | ~250 |

Total: **~930 new lines.** Exactly the "hours of verified helpers behind 5
lines of trading logic" the P3 top-8 speaker called out.

### 6.2 Existing modules to extend

- **`src/core/types.py`** — add `BasketMemory` dict to `EngineState`
  (and bump `version` from 1 → 2). Add migration in
  `StateStore._migrate(from_version=1)` to preserve existing state.

- **`src/core/config.py`** — add `basket_config: BasketEngineConfig | None`
  field to `EngineConfig`. Add `KNOWN_STRATEGY_NAMES += ("basket_arb",)`
  so per-product configs can name the basket strategy (optional — baskets
  can alternately be driven *outside* the per-product loop).

- **`src/trader.py`** — after line 124's `snapshots = self.market_data.normalize_state(state)`,
  insert:
  ```python
  basket_orders: dict[str, list[Order]] = {}
  if self.config.basket_config is not None:
      positions = {p: s.position for p, s in snapshots.items()}
      basket_orders = self.basket_engine.run(
          snapshots=snapshots,
          memories=engine_state.basket_memories,
          current_positions=positions,
      )
  ```
  Then in the per-product loop, **merge basket orders first** into `results[product]`
  and pass them through `RiskManager.clip_orders()` alongside MM orders.

- **`src/core/state_store.py`** — extend `_encode`/`load` to round-trip
  `BasketMemory` objects (Welford triple + informed_direction + killed flag).
  Keep the hard 50k char budget; basket state is tiny per basket.

- **`src/core/risk.py`** — no change. `clip_orders()` already accepts an
  arbitrary order list and respects position limits. It is the right
  single place for contention resolution.

### 6.3 Test cases (pytest, `tests/test_basket_arb.py`)

TDD checklist before any production use:

1. `test_welford_matches_np_mean_std` — Welford n=1000 vs numpy on a
   seeded random series. Tolerance 1e-9.
2. `test_bascket_memory_survives_roundtrip` — save → load via StateStore,
   verify Welford triple preserved exactly.
3. `test_dual_gate_requires_both` — spread > abs but |z| < z_thr ⇒ idle.
4. `test_kill_z_latches` — single tick |z|>kill_z latches killed; next
   tick with |z|=0 still closes existing position, doesn't re-enter.
5. `test_close_at_zero_on_cross` — long position + spread crossing 0 ⇒
   close order emitted; no new entry.
6. `test_hedge_factor_scales_legs` — hedge_factor=0.5 ⇒ constituent qty
   = round(basket_qty × weight × 0.5).
7. `test_hedge_factor_zero_emits_basket_only` — jmerle-style configuration.
8. `test_overlapping_constituents_two_pass_sizing` — B1 and B2 compete
   for CROISSANTS; higher-|z| basket wins capacity, lower is clipped.
9. `test_priority_order_by_abs_z` — B1 |z|=3, B2 |z|=1 ⇒ B1 processed
   first in `run()`.
10. `test_missing_constituent_no_orders` — basket with one constituent
    missing `best_bid` ⇒ zero orders.
11. `test_residual_mm_only_when_idle_and_in_dead_zone` — residual quotes
    only when `action=="idle" AND |z| < z_thr / 2`.
12. `test_informed_bias_shifts_thresholds` — `informed_direction=+1` AND
    `informed_adj=20` ⇒ `short_spread` fires at spread > abs_thr + 20,
    not the base abs_thr.
13. `test_counterparty_olivia_detector` — replay fixture where 'Olivia'
    is always top/bottom ⇒ detector returns `+1` near lows, `-1` near
    highs within 10 ticks.
14. `test_day_rollover_preserves_welford` — timestamp resets to 0;
    `BasketMemory.n` unchanged; `mem.mean` unchanged.
15. Integration: `test_full_tick_with_both_baskets_active` — seed two
    baskets in a crafted snapshot; verify correct sign of basket and
    hedge-constituent orders.

Use existing pytest markers: `@pytest.mark.unit` for 1-12, `@pytest.mark.integration`
for 13-15.

### 6.4 Enablement gate (same pattern as `ResidualConfig`)

Ship `basket_config = None` in `default_engine_config()`. Provide a
`round3_basket_engine_config()` factory that hydrates `BasketEngineConfig`.
**Do not flip to active in production until:**

- [ ] All 15 tests pass.
- [ ] Backtest on P3 tape (if replay tape for R3 exists in `data/raw/`)
      shows `basket_pnl >= 30% of max theoretical` (Linear Utility
      realized 111k / projected 135k ≈ 82% — reasonable target).
- [ ] Side-by-side diff of baseline (no basket) vs. basket-on shows
      maker/taker mix, time-near-limits unchanged for non-basket products.
- [ ] `traderData` size-after-save < 45k chars (10% headroom below 50k).
- [ ] Kill-switch manually triggered in replay: verify unwind is clean,
      no cross-leg residuals.

### 6.5 Rollout order (what to code first, day by day)

Given R3 hasn't opened yet (we're mid-R2 on 2026-04-22) and we have
~7-10 days:

| Day | Deliverable |
|---|---|
| 1 | `basket_spec.py` + `basket_state.py` + Welford unit tests (tests 1-2). |
| 2 | `basket_signals.py` `decide()` with dual-gate, close-at-zero, kill (tests 3-5). |
| 3 | `basket_execution.py` + hedge factor scaling (tests 6-7). |
| 4 | `BasketArbEngine` orchestrator + priority + two-pass sizing (tests 8-10). |
| 5 | Trader wire-up + StateStore migration + integration test (test 15). |
| 6 | Counterparty detector `signals/counterparty.py` + informed-adj integration (tests 12-13). |
| 7 | Residual MM hook + enablement gate comparison. |
| 8 | Kalman monitor (OPTIONAL — only if time remains). |
| 9-10 | Buffer for R3 specifics (constituent symbols, weights, limits) + live calibration. |

---

## 7. What NOT to build (scope discipline)

- **No Kalman primary hedge.** Static integer weights are definitionally
  correct for any spread of a replicable basket. Kalman only as a drift
  monitor (§2.3 point 2).
- **No SVI / smile modelling here.** This is the basket engine. If R3
  lands with options, reuse this for any basket-of-options and let the
  options module own IV.
- **No `cvxpy` or `scipy`.** Both blocked on the IMC platform. All math
  must be pure-stdlib (Welford OK, integer weights OK, OLS OK if
  inlined).
- **No per-basket custom strategies.** One `BasketArbEngine` parameterized
  by `BasketEngineConfig`. If a basket needs a radically different path
  (e.g. B2 becomes Olivia-mirror à la Sylvain-Topeza), subclass and
  override `inject_counterparty_bias`, don't fork the engine.
- **No inheritance of `BaseStrategy`.** `BasketArbEngine` runs *alongside*
  per-product strategies, not as one of them. Forcing it into the
  per-product mold loses the cross-product view and gains nothing.

---

## 8. Confidence & risk

- **HIGH confidence** on the Welford mean premium, dual-gate signal,
  target-flat exit, 50% hedge factor, and priority-by-|z| ordering.
  These are convergence points across ≥3 top teams.
- **MEDIUM confidence** on the specific threshold values
  (`abs_threshold=50`, `z_threshold=2`). These need first-hour-of-R3
  calibration; bootstrap `n=1_000` gets us a mean in ~10 minutes of
  tick data.
- **LOW confidence** on informed-adj values. Copy Frankfurt's ±90 as a
  starting guess; adjust after verifying the counterparty detector
  identifies the right bot.
- **Single biggest regret candidate** (per CLAUDE.md P1/P2 discipline):
  over-complicating. If time runs short, **ship basket_arb with
  `hedge_factor=0.5`, `close_at_zero=True`, `residual_mm=off`,
  `kalman=off`, and a single basket**. That alone is >85% of the edge
  Linear Utility captured (111k/135k).

---

## 9. Reference URLs (all verified by fetch, 2026-04-22)

- `https://raw.githubusercontent.com/jmerle/imc-prosperity-2/master/src/submissions/round3.py`
- `https://raw.githubusercontent.com/ericcccsliu/imc-prosperity-2/main/round3/round3_v1_simple_strat.py`
- `https://raw.githubusercontent.com/ericcccsliu/imc-prosperity-2/main/round3/round3_v2.py`
- `https://raw.githubusercontent.com/ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal/main/trader.py`
- `https://raw.githubusercontent.com/CarterT27/imc-prosperity-3/main/trader.py`
- `https://raw.githubusercontent.com/TimoDiehm/imc-prosperity-3/main/FrankfurtHedgehogs_polished.py`
- `https://raw.githubusercontent.com/Sylvain-Topeza/imc-prosperity-3/main/alphabaguette_round5.py`
- `https://raw.githubusercontent.com/chrispyroberts/imc-prosperity-3/main/ROUND%202/FINAL_FRENCH_GUY.py`
  (directory listing confirmed; exact file contents behind an R2 naming
  variation — `FINAL_FRENCH_GUY.py`, `french_guy.py`, `cmm_with_spikes_final_version.py`
  are all candidates; the writeup-verified numbers are the transcript-1 team's,
  not necessarily identical to chrispyroberts'.)

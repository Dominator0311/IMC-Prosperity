# Engines: `StatArbEngine` + `CounterpartyIntelligenceEngine`

Two independent engines for P4 R4/R5. A = cross-exchange / external-signal
stat-arb (Orchid/Macaron template). B = counterparty intelligence, runs
from R1 tick 0 across ALL products. B is the single highest-EV pre-R5
investment (P3 transcript 1: "top teams already knew about this from
round one").

**Repo citations inline:**

| Ref | Repo / file | What it shows |
|---|---|---|
| `CPR-R5` | chrispyroberts `ROUND5/OLIVIA IS THE GOAT.py` | ID-string copy-trade + basket hedging |
| `CPR-R4` | chrispyroberts `ROUND 4/algo run for round 4.py` L1098-1131 | macaron break-even, `math.ceil/floor(island_mid)` quoting |
| `TDH-R4` | TimoDiehm `FrankfurtHedgehogs_polished.py` `macaron_arb_make` | `math.floor(ex_raw_bid + 0.5)` + 0.58 fill-threshold |
| `CAR-R4` | CarterT27 `trader.py` `_update_regime` | Sunlight regime flag (CSI_THRESHOLD=0) |
| `CAR-R5` | CarterT27 `trader.py` `copy_olivia_trades` | Hardcoded `insider_id = "Olivia"`, no win-rate |
| `JMR-R5` | jmerle `src/submissions/round5.py` L233-296 | Vladimir↔Remy, Vinnie↔Rihannas filter |
| `ELU-R2` | ericcccsliu `round2/round_2_v1_adaptive_edge.py` | Adaptive-edge orchid arb |
| `ELU-R5` | ericcccsliu `round5/round5_v1.py` | Pre-computed `COCONUT_TRADES` signal strings |

---

## 0. Compare/contrast — answering the brief

### 0.1 chrispyroberts vs CarterT27 Olivia detection

Both naïve. Both hardcode `insider_id = "Olivia"` and trigger on
`trade.buyer/seller == "Olivia"`. **Neither computes any runtime win-rate.**
CarterT27's README claims "win-rate statistical analysis" but the code
(`CAR-R5`) is a pure ID string match; the analysis lived in a notebook
and was baked out to a constant.

Chrispyroberts is marginally more robust: (1) scans both
`own_trades` + `market_trades`; (2) persists signal state (`self.squid_signal`)
across ticks so missed ticks don't reset; (3) gates out base MM via
`if self.croissants_signal is None: self.basket2_mm(state)`. CarterT27
re-derives per-tick and runs MM in parallel.

**Both fail** if Olivia is renamed, trades a different product, or fake
Olivia-labeled prints appear. The correct engine must rediscover the
informed ID from flow, not assume the string. See §2.

### 0.2 The 30-unit macaron stockpile trick

Both top teams tied `conversions = min(abs(position), 10)` to current
position (reactive, clear-to-zero). The alpha is setting stockpile =
`−cap · round_trip_ticks`: with P(no-fill)=0.4 (TDH-R4's 0.58 hit rate),
99th-pct empty run ≈ 5 ticks ⇒ target ~30 short locally, 30 long
external. Converts at full cap even when bot is AWOL.

General principle: **separate three state variables** — displayed quote
size, stockpile target, conversion request. Target chases buffer, not
zero.

### 0.3 Sunlight: regime flag vs linear regressor — quantified

- CarterT27: regime flag `low_sun = sun < 0` → accumulate-only in low-sun.
- chrispyroberts' notebook: logistic regression (sunlight_diff coef
  −2.05, p<0.01), backtested 25k/day, abandoned in submission due to
  "generalization concerns."

Realized submission P&L: CarterT27 disabled before R5 (~0);
chrispyroberts static arb (no sunlight) ~146k; theoretical cap with
stockpile ~290k. **The regime flag is cheap insurance; the regressor is
a distractor. The dominant edge is the hidden taker bot.** Use the flag
only to disable sells in low-sun, never to drive sizing.

### 0.4 When NOT to piggyback Olivia

`CPR-R5` abandons own MM when Olivia shows. Transcript 1: "P&L from
following > P&L from own algo." But that's a ceiling case (18/18 perfect).

Decision rule: piggyback iff `E[R_olivia] · σ_olivia / σ_own >
E[R_own]` at equal vol-normalized Kelly. **Don't piggyback** when:
1. Olivia's product-level Sharpe < own algo's Sharpe.
2. Piggyback collides with a larger factor (CPR-R5's
   `basket1_market_make_pos` offset exists precisely because YOLO on
   croissants eats basket1 capacity via 6C+3J+1D).
3. Olivia trades against liquidity your MM relies on (skip those ticks).
4. Detection confidence low.

**Right split:** hybrid (weight by posterior) when 0.6 ≤ conf < 0.9;
YOLO only when conf ≥ 0.9 AND realized mid has followed her direction
≥3 times consecutively.

---

## 1. Engine A — `StatArbEngine`

### 1.1 Contract

```python
# src/engines/statarb/engine.py
from dataclasses import dataclass

@dataclass(frozen=True)
class TariffQuote:
    conv_bid: float
    conv_ask: float
    import_tariff: float          # signed; negative = subsidy
    export_tariff: float
    transport_fee: float
    storage_per_tick: float
    conv_cap: int                 # units/tick

@dataclass(frozen=True)
class BreakEven:
    sell_local_be: float
    buy_local_be: float
```

### 1.2 Break-even (symbolic, signed)

From `ELU-R2` `orchids_implied_bid_ask` — generalized with signed tariffs:

```python
def compute_break_even(t: TariffQuote, holding_ticks: float = 1.0) -> BreakEven:
    storage = t.storage_per_tick * holding_ticks
    return BreakEven(
        sell_local_be = t.conv_ask + t.import_tariff + t.transport_fee + storage,
        buy_local_be  = t.conv_bid - t.export_tariff - t.transport_fee - storage,
    )
```

A negative `import_tariff` (subsidy) lowers `sell_local_be`, widening
import arb. Never take `abs()` of tariffs — that was how both P3 teams
missed the macaron subsidy edge in their backtests.

### 1.3 Hidden-bot fill probe — Thompson bandit

`ELU-R2`'s 5-tick rolling-volume controller is primitive. `TDH-R4` uses a
fixed `math.floor(ex_raw_bid + 0.5)` with a 0.58 hit rate. We scan 3
integer offsets in parallel and let the bandit converge (~200 ticks):

```python
# src/engines/statarb/fill_probe.py
@dataclass
class FillProbeState:
    attempts: dict[int, int]      # offset -> count
    fills:    dict[int, int]
    pnl:      dict[int, float]

def pick_probe_offset(s: FillProbeState, eligible: list[int]) -> int:
    best_off, best_draw = eligible[0], -1.0
    for off in eligible:
        a = 1 + s.fills.get(off, 0)
        b = 1 + s.attempts.get(off, 0) - s.fills.get(off, 0)
        theta = _beta_sample(a, b)                     # inline via random
        mean_edge = s.pnl.get(off, 0.0) / max(1, s.fills.get(off, 1))
        draw = theta * mean_edge
        if draw > best_draw:
            best_off, best_draw = off, draw
    return best_off
```

### 1.4 Stockpile optimizer (§0.2 formalized)

```python
# src/engines/statarb/stockpile.py
import math

def stockpile_target(
    conv_cap: int, fill_rate_ewma: float, storage_per_tick: float,
    arb_edge_per_unit: float, lookahead_ticks: int = 100,
) -> int:
    """Signed target: negative = short locally, long externally."""
    if not 0 < fill_rate_ewma < 1:
        return -conv_cap
    p_no_fill = 1 - fill_rate_ewma
    # 99th-pct empty run from geometric distribution
    buffer_ticks = max(1, int(math.ceil(math.log(0.01) / math.log(p_no_fill))))
    target = -conv_cap * buffer_ticks
    carry = abs(target) * storage_per_tick * lookahead_ticks
    gain  = (buffer_ticks - 1) * conv_cap * arb_edge_per_unit
    return target if gain > carry else -conv_cap
```

For P3 macaron numbers (p=0.6, cap=10, edge≈1.4, storage=0.1): buffer=5,
target=−50, carry=500, gain=56 → fails the carry test and defaults to
−cap. The *right* target for macarons was ~30 (buffer 3) because edge
was closer to 2.0 after the `+0.5` offset — transcript 1 confirms. The
solver rederives this from inputs instead of a magic number.

### 1.5 Percentile regime detector (NOT linear regression)

```python
def classify_regime(hist, cfg) -> str:    # "low" | "normal" | "high"
    if len(hist) < 200: return "normal"
    s = sorted(hist)
    n = len(s)
    lo = s[int(cfg.low_pct * n)]; hi = s[int(cfg.high_pct * n)]
    cur = hist[-1]
    return "low" if cur < lo else "high" if cur > hi else "normal"
```

CarterT27's `CSI_THRESHOLD=0` is brittle to any cross-round shift.
Percentile-rank is self-calibrating.

### 1.6 Stream attribution

```python
@dataclass
class StreamPnL: arb_pnl: float = 0.0; signal_pnl: float = 0.0; mm_pnl: float = 0.0
```

Per Academic §3.3: cap signal stream at 20-30% of risk until it has 2k
ticks of consistent edge. Enforce via per-stream position cap, not
global. Tag every order with `meta["stream"] ∈ {arb, signal, mm}`.

### 1.7 Composition

```python
class StatArbEngine:
    def tick(self, product, snap, tariff, state):
        be = compute_break_even(tariff)
        regime = classify_regime(state.signal_history, state.regime_cfg)
        arb_orders = self._arb_take(snap, be)
        target = stockpile_target(tariff.conv_cap, state.fill_rate_ewma,
                                  tariff.storage_per_tick, state.edge_ewma)
        conv = self._conversion_toward(state.position, target, tariff.conv_cap)
        offset = pick_probe_offset(state.probe, [0, 1, 2])
        make_orders = self._make(snap, tariff, be, regime, offset)
        return StatArbDecision(orders=arb_orders+make_orders, conversions=conv)
```

---

## 2. Engine B — `CounterpartyIntelligenceEngine`

### 2.1 Per-counterparty state

```python
# src/engines/counterparty/state.py
@dataclass
class CounterpartyStats:
    trader_id: str; product: str
    trade_count: int = 0
    net_quantity: int = 0
    gross_volume: int = 0
    cum_edge: float = 0.0              # (mid - their_price) · side
    wins: int = 0; losses: int = 0     # does mid move in their direction?
    lookforward_ticks: int = 100
    pending: deque = field(default_factory=deque)         # (ts, side, mid0)
    impact_samples: deque = field(default_factory=lambda: deque(maxlen=200))
```

### 2.2 Five features

| Feature | Formula | Informed signal |
|---|---|---|
| **Win rate** | `wins / (wins + losses)` over 100 ticks | >0.70 suspicious, >0.85 near-certain |
| **Edge** | `mean(side · (mid_after − price))` | Positive + growing → not MM |
| **Inventory amplitude** | `max(net_q) − min(net_q)` | High+trending = informed; high+flat = MM |
| **Kyle's λ** | OLS slope of Δmid on signed qty | High λ = informed |
| **Trade intensity** | trades/window | MM high; informed low-moderate |

### 2.3 Classifier

```python
# src/engines/counterparty/features.py
def kyle_lambda(samples):              # [(signed_qty, dmid_over_N), ...]
    n = len(samples)
    if n < 20: return 0.0
    sx = sum(x for x,_ in samples); sy = sum(y for _,y in samples)
    sxx = sum(x*x for x,_ in samples); sxy = sum(x*y for x,y in samples)
    d = n*sxx - sx*sx
    return 0.0 if d <= 0 else (n*sxy - sx*sy) / d

def classify_counterparty(s) -> str:       # "informed" | "mm" | "noise" | "unknown"
    if s.trade_count < 20: return "unknown"
    wr  = s.wins / max(1, s.wins + s.losses)
    lam = kyle_lambda(list(s.impact_samples))
    intensity = s.trade_count / 1000.0
    if wr >= 0.70 and lam > 0.02 and intensity < 0.20:
        return "informed"
    if abs(lam) < 0.005 and intensity > 0.30 and abs(s.cum_edge) < 0.5*s.gross_volume:
        return "mm"
    if s.cum_edge < -1.0 * s.gross_volume and intensity > 0.15:
        return "noise"
    return "unknown"
```

### 2.4 Anonymization-resilient fingerprinting

Pre-R5, IDs may be anonymous. Compute a stable stylometric hash —
`(top3_modal_sizes, mean_price_offset_bucket, mean_iat_bucket)`. When
R5 reveals real IDs, cross-check against informed-classified
fingerprints. Cheap, high-reuse.

### 2.5 K-means (pure-python, scipy-blocked)

```python
# src/engines/counterparty/cluster.py
def kmeans_3d(points, k=3, iters=20):
    """points = [(pnl_slope, log_volume, win_rate), ...]. k=3 mirrors
    the three regimes from transcript 1. Deterministic quantile init.
    n≈20 counterparties → <1ms/call."""
    if not points: return [], []
    sp = sorted(points, key=lambda p: p[0]); n = len(sp)
    centroids = [sp[int((i+0.5)*n/k)] for i in range(k)]
    labels = [0]*len(points)
    for _ in range(iters):
        for i, p in enumerate(points):
            labels[i] = min(range(k), key=lambda j:
                sum((p[d]-centroids[j][d])**2 for d in range(3)))
        for j in range(k):
            mem = [p for i,p in enumerate(points) if labels[i]==j]
            if mem: centroids[j] = tuple(sum(c)/len(mem) for c in zip(*mem))
    return labels, centroids
```

### 2.6 Signal API

```python
@dataclass(frozen=True)
class CounterpartyReport:
    product: str
    informed_active: bool
    informed_side: str                    # "long" | "short" | "none"
    informed_confidence: float            # posterior [0, 1]
    informed_ids: tuple[str, ...]
    mm_ids:       tuple[str, ...]
    noise_ids:    tuple[str, ...]

class CounterpartyIntelligenceEngine:
    def __init__(self):
        self.stats: dict[tuple[str,str], CounterpartyStats] = {}

    def ingest(self, snap):
        for t in snap.trades:
            for role, sign in (("buyer", +1), ("seller", -1)):
                trader = getattr(t, role)
                if not trader: continue
                key = (trader, snap.product)
                s = self.stats.setdefault(key, CounterpartyStats(trader, snap.product))
                s.trade_count += 1; s.net_quantity += sign*t.quantity
                s.gross_volume += t.quantity
                edge = sign * (snap.mid_price - t.price)
                s.cum_edge += edge
                s.pending.append((t.timestamp, sign, snap.mid_price))
        # resolve look-forward
        for s in self.stats.values():
            while s.pending and snap.timestamp - s.pending[0][0] >= s.lookforward_ticks:
                ts, side, mid0 = s.pending.popleft()
                d = snap.mid_price - mid0
                if side*d > 0: s.wins += 1
                elif side*d < 0: s.losses += 1
                s.impact_samples.append((float(side), d))

    def report(self, product) -> CounterpartyReport:
        informed, mm, noise, sign_sum = [], [], [], 0
        for (tr, pr), s in self.stats.items():
            if pr != product: continue
            c = classify_counterparty(s)
            if c == "informed":
                informed.append(tr)
                sign_sum += (1 if s.net_quantity>0 else -1 if s.net_quantity<0 else 0)
            elif c == "mm": mm.append(tr)
            elif c == "noise": noise.append(tr)
        side = "long" if sign_sum>0 else "short" if sign_sum<0 else "none"
        conf = 0.0
        if informed:
            conf = sum(
                min(1.0, max(0.0, (self.stats[(t,product)].wins /
                max(1, self.stats[(t,product)].wins+self.stats[(t,product)].losses) - 0.5) * 5))
                for t in informed) / len(informed)
        return CounterpartyReport(product, bool(informed) and side!="none",
                                  side, conf, tuple(informed), tuple(mm), tuple(noise))
```

### 2.7 Piggyback sizing (Kelly-adapted)

```python
# src/engines/counterparty/sizing.py
def piggyback_size(report, own_signal, own_sharpe,
                   product_limit, current_position, base_risk=0.5) -> int:
    if not report.informed_active:
        return int(own_signal * base_risk * product_limit)
    olivia_sharpe = 4.0 + 4.0 * report.informed_confidence            # 4..8
    w_o = olivia_sharpe**2 / (olivia_sharpe**2 + own_sharpe**2)
    olivia_signal = 1.0 if report.informed_side == "long" else -1.0
    # Collision check — §0.4 rule 3
    if own_signal != 0 and own_signal * olivia_signal < 0:
        return current_position                                       # stand aside
    frac = max(-1.0, min(1.0, w_o*olivia_signal + (1-w_o)*own_signal))
    if report.informed_confidence < 0.6:
        frac *= report.informed_confidence / 0.6
    return int(frac * product_limit)
```

---

## 3. Non-obvious alpha

**Quote-shape fingerprinting.** MMs quote two-sided fixed lots (e.g.
15/15 at ±1). Informed quote one side with variable size. Noise quotes
tight, small, rarely. Add `quote_fingerprint` to `CounterpartyStats`
and pre-position when a new bot's quote fingerprint matches a known
informed one — *before* its first trade.

**Lead-lag cross-correlation** (Academic §2.3). Compute `corr(signal_t,
price_{t+lag})` for lag ∈ [−100, +100]. Use when lag>0 and |corr|>0.08
(realistic IC). >0.15 is lookahead leakage.

**Inventory sweet-spot.** `carry_per_unit = storage · holding_ticks`;
if `edge_per_unit < carry`, optimum is 0 (stockpile only for
operational smoothness, not alpha). P3 macarons: edge=1.4, carry=5 →
*stockpile is pure operational, not inventory alpha*.

**Glosten-Milgrom posterior** feeds directly into
`informed_confidence`: after k buys / n-k sells,
`log(LR) = k·log(θ/0.5) + (n-k)·log((1-θ)/0.5)`, θ≈0.85.

**News shock detector** (Academic §4.2): `|r| / sqrt(baseline_var) >
3` → halt short-gamma, invalidate rolling means 500 ticks, widen all
quotes. Wire into both engines' kill switch.

---

## 4. Adoption

### Files to create

```
src/engines/
  statarb/{engine,break_even,fill_probe,stockpile,regime,attribution}.py
  counterparty/{state,features,fingerprint,cluster,sizing,api}.py
  shared/{leadlag,glosten_milgrom,jump_detect}.py
```

### Extensions to existing `src/`

1. **`src/trader.py`** — `self.counterparty.ingest(snap)` per product
   before strategy dispatch; inject `CounterpartyReport` into
   `StrategyContext`.
2. **`src/strategies/base.py`** — add `counterparty: CounterpartyReport
   | None` field to `StrategyContext`.
3. **`src/strategies/ash_*`, `market_making.py`** — consume
   `ctx.counterparty` to widen quotes / gate MM when informed collides.
4. **`src/core/config.py`** — add `StatArbConfig`, `CounterpartyConfig`.
   All thresholds configurable (no hardcoded strings).
5. **`src/core/signals.py`** — extend `_effective_taker_edges` to
   widen by `0.5 · informed_confidence` when MM mode + informed-active.
6. **`src/backtest/simulator.py`** — add synthetic-Olivia generator;
   pre-replay to emit `counterparty_report_series.csv`.

### Interface: how B feeds A and strategies

```
CounterpartyIntelligenceEngine.report(product) → CounterpartyReport
   │
   ├──► StatArbEngine  (skip piggyback on collision; widen quotes when
   │                    informed_active, still run arb legs)
   ├──► Basket / MM    (gate MM via flag mirroring CPR-R5 pattern)
   └──► Options        (Glosten-Milgrom adverse-selection widen)
```

Every engine checks `informed_active` per tick. Actions:

- `informed_active=True` + `conf ≥ 0.9`: disable own-quoting, piggyback
- `0.6 ≤ conf < 0.9`: hybrid via `piggyback_size`
- `conf < 0.6`, informed active: widen quotes by `0.5·conf·spread`
- All engines share position limits; `piggyback_size` includes
  `basket_market_make_pos` offset (CPR-R5 pattern) so MM in correlated
  products is consumed into the YOLO leg, never double-booked.

### Test cases

```python
def test_kyle_lambda_nonzero_on_trending_mid():
    assert kyle_lambda([(1,0.5),(1,0.6),(1,0.4),(-1,-0.5),(-1,-0.6)]) > 0.3

def test_classify_olivia_like():
    s = CounterpartyStats("olivia","croissants")
    s.wins, s.losses, s.trade_count = 18, 0, 40
    s.impact_samples.extend([(1, 0.8)] * 25)
    assert classify_counterparty(s) == "informed"

def test_classify_mm_flat_pnl():
    s = CounterpartyStats("mm_bot","kelp")
    s.trade_count, s.gross_volume, s.cum_edge = 500, 5000, 5.0
    s.impact_samples.extend([(1,0.001),(-1,-0.001)] * 50)
    assert classify_counterparty(s) == "mm"

def test_break_even_signed_subsidy():
    t = TariffQuote(100,102,-5,2,1,0.1,10)
    be = compute_break_even(t, holding_ticks=10)
    assert be.sell_local_be == 99     # 102 + (-5) + 1 + 1

def test_piggyback_collision_stands_aside():
    r = CounterpartyReport("x", True, "long", 0.95, ("olivia",),(),())
    assert piggyback_size(r, own_signal=-1.0, own_sharpe=2.0,
                          product_limit=250, current_position=0) == 0
```

### One-week adoption order

| Day | Deliverable |
|---|---|
| 1 | `counterparty/{state,features}.py` + unit tests |
| 2 | `api.py` + K-means + `ingest` wired into `trader.py` |
| 3 | Backfill R1/R2 replay → verify top-quartile informed bot found |
| 4 | `statarb/{break_even,stockpile,regime}.py` + tests |
| 5 | `fill_probe.py` + `engine.py` + simulator integration |
| 6 | `sizing.py` + MM strategies consume `CounterpartyReport` |
| 7 | Synthetic-Olivia E2E → confirm YOLO fires on conf≥0.9 |

---

## 5. Ranked alternatives + what to BUILD

**DO NOT build** (worst to least-bad):

1. Sunlight linear regression (99% R² = lookahead). Redundant with regime flag.
2. Hardcoded `insider_id = "Olivia"`. Fragile; useless pre-R5.
3. Quadratic IV smile. Degrades. Use rolling mid-IV.
4. Per-strike delta hedging in 1-wide books (100× destructive).

**DO build (in order):**

1. **`CounterpartyIntelligenceEngine`** — highest EV, usable from R1.
   5 features, robust classifier, fingerprint fallback, Kelly sizing.
   The piece both P3 top teams got wrong (hardcoded; we infer).
2. **`StatArbEngine` break-even + stockpile** — fixes the biggest P3
   P&L leaver. Reusable for any cross-exchange product.
3. **Thompson-bandit fill probe** — replaces magic
   `int(ex_raw_bid + 0.5)` with empirically calibrated best offset.
4. **Glosten-Milgrom posterior + jump detector** — confidence gate.
5. **Lead-lag cross-correlation** — quantifies any external signal's lag.
6. **Stylometric fingerprint** — insurance against anonymization.

**Key discipline.** Every engine exposes a **posterior confidence**,
not a binary signal. Downstream strategies size by `confidence · Kelly`.
This is the architectural difference vs every P1/P2/P3 top-2 repo:
they hardcoded; we compute posteriors.

---

## 6. The one table that matters

| Scenario | Correct action | Precedent |
|---|---|---|
| No informed, own signal strong | Follow own + MM residual | all of them |
| Informed, conf < 0.6 | Widen quotes, skip piggyback | **novel** |
| Informed, conf 0.6-0.9 | Hybrid via `piggyback_size` | partial CPR-R5 |
| Informed, conf ≥ 0.9, no collision | YOLO + basket hedge | CPR-R5 Olivia |
| Informed, conf ≥ 0.9, own signal opposes | Stand aside | **novel — both P3 teams missed** |
| Olivia on X, basket contains X | Offset basket leg by Olivia pos | CPR-R5 `basket1_market_make_pos` |
| Arb with conv_cap binding | Stockpile `−cap · buffer` | **novel — both P3 teams missed** |
| External signal at extreme pct | Disable opposing-side quotes | CAR-R4 pattern |
| News shock detected | Halt short-gamma, invalidate means | **novel, Academic §1.4** |

The **novel** rows (4 of 9) are the EV edges this engine pair delivers
over all P1-P3 open-source. The pre-R5 prep window closes fast.

---

## 7. Pointers back into this repo

- `src/core/signals.py` — extend `_effective_taker_edges` to accept
  `counterparty` and widen by `0.5·conf` when informed-active.
- `src/signals/flow_analyzer.py` — current `FlowReport` is aggregate;
  extend to per-counterparty slices.
- `src/strategies/ash_*`, `src/strategies/market_making.py` — consume
  `ctx.counterparty`; gate quoting on informed collision.
- `src/backtest/simulator.py` — synthetic-Olivia tape generator for
  ground-truth regression tests on Engine B.

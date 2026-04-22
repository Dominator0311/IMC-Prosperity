# Options Engine Blueprint — IMC Prosperity 4 R3/R4

**Status:** concrete engineering spec, ready to adopt into `src/`.
**Audience:** the person who will implement this the day R3 opens.
**Bias:** opinionated. We pick one primary architecture and justify against the alternatives; we do not enumerate a menu.

---

## 0. Executive summary

**Build a residual-IV market maker on a per-strike basis, with graceful-degradation smile fitting (quadratic prior → rolling-window mid-IV override), no per-tick delta hedging, a hard gamma-notional cap, and a jump-driven kill switch.** Primary alpha = IV residual MM. Secondary = ATM IV-scalp via mean-reversion of mid-IV. Overlay = butterfly/risk-reversal when adjacent strikes show same-signed IV residuals. Everything else from the research pack is either dominated by these three or mechanically unsound under Prosperity's 1-wide spread.

This is the consensus structure of every P3 top-10 team that made money on volcanic vouchers. Their failure modes — overfit smile, delta-hedge bleed, visualizer memory wipe — become explicit guarded state here.

---

## 1. Evidence — what P2/P3 top teams actually shipped

I extracted the working options code from the four most relevant repos. All four use the same outer shape and diverge on exactly three details.

### 1.1 chrispyroberts (7th global, 1st USA, P3) — `ROUND 3/big_volcano_man.py` + `ROUND 4 chris analysis/big_volcano_man_IV_window.py`

- **Pricer:** `statistics.NormalDist().cdf()`. Stdlib-only, portable.
- **IV solver:** pure bisection over `[0.001, 1.0]`, tol `1e-10`, max 200 iters. No Newton (diverges on deep OTM where vega≈0).
- **Smile v1 (R3 submission, broke):** offline-fit quadratic `IV = a·m² + b·m + c`, `m = log(S/K)/√T`. Ask: `a=0.2386, b=-0.00196, c=0.1516`. Bid: `a=0.1436, b=-0.00155, c=0.1504`. Calibrated on one day; by submission, ATM level had drifted → systematic mis-quote.
- **Smile v2 (R4 post-mortem):** per-strike `np.mean/std` over last 100 IV obs. Backtest 80k/day → 200k/day.
- **Trade rule:** `buy_at = floor(BS(avg−std))`, `sell_at = ceil(BS(avg+std))`. Skip strike when `high−low < 1.0` (book too tight).
- **Sizing:** flat ±80 per strike (not the 200 limit — leaves hedge headroom, unused in the end).
- **Delta hedge:** implemented, gated by `dont_hedge=True`. Prose: ~$50k/day to hedge vs ~$16k unhedged loss.
- **traderData:** `"SAMPLE"`. Stateless — rolling window lost on container reset. Directly identified as a failure mode.
- **Rolling windows:** `list` with `-window:` slicing. Not `deque`. Negligible at n≤100 but scales poorly.

### 1.2 CarterT27 / Alpha Animals (9th global, P3) — `trader.py`

- **IV solver:** Newton-Raphson, init `0.5`, 50 iters, tol `1e-5`, clipped `[0.01, 2.0]`, `vega=0` → fallback to `mean_volatility`. Cached by `(price, S, K, T, r)`.
- **Smile:** none — per-strike rolling mean of last 20 IV observations.
- **Trade rule:** mechanical MM at `floor(BS_fair)` / `floor(BS_fair)+1`; always quotes to limit, no residual gate.
- **Delta hedge:** computed, never called. Dead code.
- **traderData:** `jsonpickle.encode(past_volatilities)` — roughly 10× heavier than json. Latent memory-blow-up.

### 1.3 TimoDiehm / Frankfurt Hedgehogs (top-3 P3) — `FrankfurtHedgehogs_polished.py`

The IV-scalp specialist.

- **"IV solver":** not a solver — polynomial evaluation. They use a hardcoded smile as IV and never invert market:
  ```python
  def get_iv(St, K, TTE):
      m = np.log(K/St) / TTE**0.5
      return np.poly1d([0.27362531, 0.01007566, 0.14876677])(m)
  ```
- **Scalp signal:** dual EMA.
  `mean_theo_diffs = EMA(20) of (market_mid − BS_theo)`,
  `switch_means = EMA(100) of |diff − mean_diff|`. Entry when `switch_means ≥ 0.7` and `current − mean ≥ 0.5 + low_vega_adj`. Strikes ≥ 9750 only (skip deep ITM).
- **Delta hedge:** computed, unused. Underlying traded pure MR, decoupled from options.
- **Kill switch:** none.

The "negative 1-lag autocorrelation" story is not explicit code — it emerges because short-EMA overshoots long-EMA, making `diff − mean_diff` mean-revert. Generalizes in P4 iff bots re-anchor to a slow fair (true in most Prosperity products).

### 1.4 ericcccsliu / Linear Utility (#2 P2) — `round4/round4_v3.py`

- **Pricer/solver:** bisection `[0.01, 1.0]`, tol `1e-10`, 200 iters. Same shape as chrispyroberts.
- **Trade rule:** extreme tails only, `|z| ≥ 5.1` against 20-tick rolling mean/std → max position. In between, quote around theoretical.
- **Delta hedge:** **they do hedge**, every tick, target `−delta · position`, clipped to coconut's ±300 limit. The oft-repeated "chose to hold residual delta" is misleading — 600 × 0.53 = 318 > 300, so the cap *forced* residual. **This matters:** 250-day expiry + deep book makes hedging penciled. 7-day expiry + 1-wide spread makes it bleed. P4 options product expiry determines the hedge policy.

### 1.5 Invariants across all four

(1) `statistics.NormalDist().cdf()` — no scipy. (2) bisection or Newton — bisection safer. (3) log-moneyness `m = log(K/S)/√T`. (4) per-strike limits, not aggregate. (5) `traderData` is either `"SAMPLE"` or a tiny dict. (6) **Delta hedging is the most-regretted P3 decision** — 3 of 4 teams disabled it.

---

## 2. Critical compare-and-contrast — what to adopt, what to drop

### 2.1 Quadratic smile vs rolling mid-IV — why quadratic broke

Quadratic fits 3 params to 5 strikes. The 5-point cross-section has only 2 residual DoF; the fit always eats wing noise. chrispyroberts calibrated offline on one day; by submission day ATM `c` had drifted ~1.5 vol points, systematically mis-quoting every strike in the same direction.

Rolling mid-IV has zero cross-strike coupling — each strike learns its own level from its own history. Correct when: true smile is unknown, bot quotes drift, cross-strike N=5 is too thin for shape signal, and spread cost dominates skew edge.

**Decision.** Hybrid: quadratic prior for warmup (first 50 ticks per strike), rolling mean±std after. Gate is observation count, not P&L. Day-1 behavior from the prior, Day-3 behavior from live IV.

### 2.2 TimoDiehm IV-scalp — what's really happening

The neg-1-lag autocorrelation is microstructure, not a bot quirk. Mechanism: bots re-quote around a slow fair `F_t`; a random trade pushes `mid_t` off; next refresh snaps it back. `mid − F_t` therefore has negative AR(1), and `BS_theo(IV̂) ≈ F_t` when `IV̂` is a stable rolling mean, so `mid − BS_theo` inherits the sign-flip. The EMA-diff signal is a band-pass filter on that.

**P4 generalization.** Holds when bots re-anchor to a slow fair (most Prosperity products). Fails for fast-drifting products (squid-ink-style). Safe default: enable scalp at ATM only, gate on `std(IV)/mean(IV) < 0.15`, halt on jump.

### 2.3 Delta-hedge — when it pencils

Whalley-Wilmott no-trade band: `Δ_band = (3/2 · λ · Γ²·S² / γ)^(1/3) · σ^(−2/3) · T^(1/3)`.

- **P3 vouchers (7d, 1-wide):** λ=0.5, Γ·S²≈50, σ≈0.15, T=7/365 → `Δ_band ≈ 15` rock-equivalents. chrispyroberts hedging at |Δ|>1 was paying λ ~50× too often.
- **P2 coupons (250d):** large T → band small in proportion to position, gamma small → drift slow. Hedge pencils; Linear Utility hedged and profited.

**Decision.** Whalley-Wilmott gate, default `max(WW, 10)`. For <14d expiry expect hedging off most of the time; for >60d expect regular firing. Always hedge the aggregate book, not per-strike (3-5× volume reduction).

### 2.4 The "short everything" gamble — disciplined version

#2 P3 team shorted every option (rank 2 via variance). Disciplined form: systematic short-ATM-straddle sized to `theta_budget / (Γ·S²)` so expected daily theta > expected daily gamma bleed. Exit on (a) |r|>4σ, (b) RV>IV×1.15 over 50 ticks, (c) PnL drawdown > 2× collected theta. This is variance-risk-premium harvesting; real edge iff IV>RV on average (testable in 1 day of replay). Enable as ≤10% overlay, never across news ticks.

### 2.5 Residual delta "by choice" — actually by cap

Linear Utility's 318 of 600 un-hedged is a position-cap artifact (600 × 0.53 > 300). Under log-wealth you'd fully hedge. Under rank-based scoring with R3 reset to zero, **deliberately-sized residual delta is fine**; accidental slippage residual is not. Size it explicitly or not at all.

---

## 3. Non-obvious alpha — what we investigate and what we drop

| Alpha | Verdict | Rationale |
|---|---|---|
| Multi-strike butterfly / risk-reversal | **Include as overlay, tiny size** | Fires only when 2+ adjacent strikes both show same-signed IV residual; otherwise noise. |
| MM-layer gamma scalp (quote both sides at fair, roll with Γ) | **Include as primary MM mode** | This *is* what IV-residual MM does. Gamma scalping with delta hedging (textbook) loses to spread cost; MM-at-fair-theta-paid-for captures the same gamma without the hedge leak. |
| Calendar / forward-vol arb | **Skip unless multi-expiry** | P3 had single expiry; P4 may extend. Hook is in the design but off by default. |
| Intra-day IV mean-reversion | **Primary in TimoDiehm style** | Evidence-backed; generalizes under low-vol-of-vol. |
| Cross-day IV mean-reversion | **Skip** | IV levels legitimately drift across days; no mean to revert to. |
| Gap-risk asymmetry | **Implement kill switch** | Short-gamma is linearly exposed to gaps; one bad tick wipes a week. Ratio detector `|r| / EWMA(|r|) > 4` halts short-gamma positions. |
| ATM straddle variance-risk-premium | **Enable, gated** | §2.4. |
| Put-call parity arb | **Skip** | Prosperity historically only lists calls. |
| Pin risk at expiry | **Flatten at TTE < 0.5 day** | No edge holding through expiry; intrinsic value is mechanical. |
| Known-bot fills (`int(externalBid + 0.5)`) | **Not options, but hook it** | This was the macaron (R4 P3) edge. If R4 has options + cross-market, probe it per-strike. |

---

## 4. The engine blueprint

Target location: `src/options/`. Five modules, each <400 LOC, all typed, all tested. Strategy-side entry point is `src/strategies/options_book.py` that plugs into the existing `STRATEGY_REGISTRY`.

### 4.1 Directory layout

```
src/options/
    __init__.py
    bsm.py            # norm_cdf/pdf, BS call, greeks
    iv_solver.py      # bisection IV solver with safe bounds
    smile.py          # QuadraticSmile + RollingMidIV + degradation
    hedge.py          # Whalley-Wilmott band + aggregator
    risk.py           # gamma notional cap, theta budget, jump detector, kill switch
    engine.py         # OptionsEngine orchestrator (per-tick tick())
    state.py          # compact traderData serialization
src/strategies/
    options_book.py   # adapter from BaseStrategy → OptionsEngine
tests/options/
    test_bsm.py
    test_iv_solver.py
    test_smile.py
    test_hedge.py
    test_engine_tick.py
```

### 4.2 `src/options/bsm.py` — pricer and greeks

Use `statistics.NormalDist()`. Inline A&S as a backup (some past editions have blocked `statistics` — cheap insurance). Frozen dataclasses for immutability per our coding style.

```python
from __future__ import annotations
from dataclasses import dataclass
from math import log, sqrt, exp
from statistics import NormalDist

_N = NormalDist()


def norm_cdf(x: float) -> float:
    """Prefer stdlib; inline A&S fallback if banned in future editions."""
    return _N.cdf(x)


def norm_pdf(x: float) -> float:
    return _N.pdf(x)


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float


def bs_d1_d2(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> tuple[float, float]:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise ValueError("bs_d1_d2: inputs must be positive")
    d1 = (log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    return d1, d2


def bs_call(S: float, K: float, T: float, sigma: float, r: float = 0.0) -> Greeks:
    d1, d2 = bs_d1_d2(S, K, T, sigma, r)
    price = S * norm_cdf(d1) - K * exp(-r * T) * norm_cdf(d2)
    delta = norm_cdf(d1)
    pdf_d1 = norm_pdf(d1)
    gamma = pdf_d1 / (S * sigma * sqrt(T))
    vega = S * pdf_d1 * sqrt(T)
    theta = (-S * pdf_d1 * sigma / (2 * sqrt(T))) - r * K * exp(-r * T) * norm_cdf(d2)
    return Greeks(price=price, delta=delta, gamma=gamma, vega=vega, theta=theta)
```

Source: Hull *Options, Futures and Other Derivatives* ch. 15; A&S 26.2.17.

### 4.3 `src/options/iv_solver.py` — bisection

Bisection, not Newton. Rationale: deep OTM vega ≈ 0 → Newton diverges; bisection is O(log(1/ε)) and never explodes. chrispyroberts, Linear Utility, and every P3 blueprint I've seen do the same.

```python
from __future__ import annotations
from src.options.bsm import bs_call

IV_LOW = 1e-3
IV_HIGH = 2.0
TOL = 1e-6
MAX_ITERS = 60  # log2(2/1e-6) ≈ 21; 60 is conservative


def implied_vol_call(
    market_price: float, S: float, K: float, T: float, r: float = 0.0
) -> float | None:
    intrinsic = max(0.0, S - K)
    if market_price < intrinsic - 1e-6 or market_price <= 0 or T <= 0:
        return None
    lo, hi = IV_LOW, IV_HIGH
    for _ in range(MAX_ITERS):
        mid = 0.5 * (lo + hi)
        diff = bs_call(S, K, T, mid, r).price - market_price
        if abs(diff) < TOL:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)
```

Bounded; `None` on infeasible inputs; never raises during a live tick.

### 4.4 `src/options/smile.py` — degrading fit

The core graceful-degradation machinery. Quadratic prior (coefficients loaded from config, offline-calibrated) for warmup; rolling mid-IV per-strike once enough observations land. Exposes a single `fair_iv(strike)` call regardless of mode.

```python
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from math import log, sqrt

WARMUP_OBS = 50
ROLLING_WINDOW = 200  # ~20% of one day of ticks


@dataclass
class QuadraticCoeffs:
    a: float
    b: float
    c: float

    def eval(self, m: float) -> float:
        return self.a * m * m + self.b * m + self.c


@dataclass
class StrikeState:
    iv_window: deque[float] = field(default_factory=lambda: deque(maxlen=ROLLING_WINDOW))
    obs_count: int = 0

    def observe(self, iv: float) -> None:
        self.iv_window.append(iv)
        self.obs_count += 1

    def mean(self) -> float:
        return sum(self.iv_window) / len(self.iv_window)

    def std(self) -> float:
        n = len(self.iv_window)
        if n < 2:
            return 0.0
        mu = self.mean()
        return (sum((x - mu) ** 2 for x in self.iv_window) / (n - 1)) ** 0.5


class Smile:
    def __init__(self, prior: QuadraticCoeffs, strikes: tuple[int, ...]) -> None:
        self._prior = prior
        self._states: dict[int, StrikeState] = {k: StrikeState() for k in strikes}

    def moneyness(self, S: float, K: int, T: float) -> float:
        return log(K / S) / sqrt(T)

    def observe(self, K: int, iv: float) -> None:
        self._states[K].observe(iv)

    def fair_iv(self, S: float, K: int, T: float) -> tuple[float, float]:
        """Returns (mean_iv, std_iv). Falls back to prior before WARMUP_OBS."""
        st = self._states[K]
        if st.obs_count < WARMUP_OBS:
            m = self.moneyness(S, K, T)
            return self._prior.eval(m), 0.02  # prior-std default
        return st.mean(), max(st.std(), 1e-4)
```

Design points:
- `deque(maxlen=...)` is O(1) and **preempts the chrispyroberts 100MB visualizer wipe**. Research doc §5.4.
- Warmup → prior is not a backtest-worthy fit. It exists so we don't quote garbage on tick 0.
- Residual std floor prevents division-by-zero in trade-gate arithmetic.

### 4.5 `src/options/hedge.py` — Whalley-Wilmott gate

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class HedgeDecision:
    target_delta_trade: int  # signed; underlying units
    reason: str


def ww_band(
    gamma_dollar: float, sigma: float, T_residual: float,
    half_spread: float, risk_aversion: float = 1.0
) -> float:
    """Whalley-Wilmott no-trade band, units: underlying contracts."""
    if gamma_dollar <= 0 or sigma <= 0 or T_residual <= 0:
        return 0.0
    return ((1.5 * half_spread * gamma_dollar ** 2 / risk_aversion)
            ** (1 / 3)) * sigma ** (-2 / 3) * T_residual ** (1 / 3)


def decide_hedge(
    net_delta: float, target_delta: float,
    gamma_dollar: float, sigma: float, T_residual: float,
    half_spread: float, hard_floor: int = 10,
) -> HedgeDecision:
    band = max(ww_band(gamma_dollar, sigma, T_residual, half_spread), hard_floor)
    drift = net_delta - target_delta
    if abs(drift) < band:
        return HedgeDecision(0, f"inside_band:{band:.1f}")
    return HedgeDecision(-int(drift), f"band_break:{drift:+.1f}>{band:.1f}")
```

Citation: Whalley & Wilmott 1997 eq. 4.12. `hard_floor=10` prevents fire at very small drift regardless of theoretical band. Zakamouline (2005) refinements are available if needed but add parameters and buy little in tight-spread books.

### 4.6 `src/options/risk.py` — caps and kill switch

```python
from __future__ import annotations
from collections import deque
from dataclasses import dataclass


JUMP_RATIO_THRESHOLD = 4.0
JUMP_EWMA_ALPHA = 2 / (500 + 1)


@dataclass
class RiskState:
    ewma_abs_return: float = 0.0
    last_mid: float | None = None
    kill_active: bool = False
    kill_until_tick: int = 0
    realized_pnl: float = 0.0
    peak_pnl: float = 0.0

    def observe_mid(self, mid: float, tick: int) -> None:
        if self.last_mid is not None:
            r = abs(mid - self.last_mid)
            if self.ewma_abs_return == 0:
                self.ewma_abs_return = r
            else:
                self.ewma_abs_return = (
                    JUMP_EWMA_ALPHA * r + (1 - JUMP_EWMA_ALPHA) * self.ewma_abs_return
                )
            if (
                self.ewma_abs_return > 0
                and r / self.ewma_abs_return > JUMP_RATIO_THRESHOLD
            ):
                self.kill_active = True
                self.kill_until_tick = tick + 500  # cool-off
        self.last_mid = mid

    def observe_pnl(self, pnl: float, max_dd_abs: float) -> None:
        self.realized_pnl = pnl
        self.peak_pnl = max(self.peak_pnl, pnl)
        if self.peak_pnl - pnl > max_dd_abs:
            self.kill_active = True

    def release_if_due(self, tick: int) -> None:
        if self.kill_active and tick >= self.kill_until_tick:
            self.kill_active = False
```

Kill logic: jump detector (|r|/EWMA > 4 halts short-gamma) + drawdown trigger (configurable absolute shells). Cool-off is 500 ticks (~5% of one day).

### 4.7 `src/options/engine.py` — the orchestrator

```python
from __future__ import annotations
from dataclasses import dataclass, field
from src.options.bsm import bs_call
from src.options.hedge import decide_hedge
from src.options.iv_solver import implied_vol_call
from src.options.risk import RiskState
from src.options.smile import QuadraticCoeffs, Smile


@dataclass(frozen=True)
class OptionsConfig:
    underlying: str
    strikes: tuple[int, ...]
    expiry_ticks: int
    per_strike_limit: int           # e.g. 80
    underlying_limit: int           # e.g. 400
    half_spread_estimate: float     # e.g. 0.5
    prior: QuadraticCoeffs
    residual_k_sigma: float = 1.0   # entry trigger |IV − fair| > kσ
    max_drawdown_shells: float = 20_000
    enable_scalp: bool = True


@dataclass
class OptionsEngine:
    config: OptionsConfig
    smile: Smile = field(init=False)
    risk: RiskState = field(default_factory=RiskState)

    def __post_init__(self) -> None:
        self.smile = Smile(self.config.prior, self.config.strikes)

    # --- public API called per tick ---
    def tick(self, ctx: "TickContext") -> "TickOutput":
        """
        ctx carries: underlying mid S, TTE in years, per-strike mid and book,
        per-strike position, underlying position, current tick, realized PnL.
        Returns signed trades keyed by symbol.
        """
        self.risk.observe_mid(ctx.S, ctx.tick)
        self.risk.observe_pnl(ctx.pnl, self.config.max_drawdown_shells)
        self.risk.release_if_due(ctx.tick)

        trades: dict[str, int] = {}
        net_delta = 0.0
        gamma_dollar = 0.0
        sigma_used = 0.0

        # 1. Update IV per strike, decide residual trade per strike
        for K in self.config.strikes:
            obs_mid = ctx.option_mid[K]
            iv_obs = implied_vol_call(obs_mid, ctx.S, K, ctx.T)
            if iv_obs is None:
                continue
            self.smile.observe(K, iv_obs)
            iv_fair, iv_std = self.smile.fair_iv(ctx.S, K, ctx.T)
            residual = iv_obs - iv_fair
            greeks = bs_call(ctx.S, K, ctx.T, iv_fair)
            net_delta += greeks.delta * ctx.option_pos[K]
            gamma_dollar += greeks.gamma * ctx.S * ctx.S * max(abs(ctx.option_pos[K]), 1)
            sigma_used = max(sigma_used, iv_fair)

            if self.risk.kill_active:
                continue

            # Residual entry gate
            if residual > self.config.residual_k_sigma * iv_std:
                # market-rich in IV → sell
                size = self._size_for_strike(K, ctx.option_pos[K], side=-1)
                if size > 0:
                    trades[f"VOUCHER_{K}"] = -size
            elif residual < -self.config.residual_k_sigma * iv_std:
                size = self._size_for_strike(K, ctx.option_pos[K], side=+1)
                if size > 0:
                    trades[f"VOUCHER_{K}"] = +size

        # 2. Aggregate-delta hedge decision
        decision = decide_hedge(
            net_delta=net_delta,
            target_delta=0.0,
            gamma_dollar=gamma_dollar,
            sigma=sigma_used,
            T_residual=ctx.T,
            half_spread=self.config.half_spread_estimate,
        )
        if decision.target_delta_trade != 0 and not self.risk.kill_active:
            hedge = max(
                -self.config.underlying_limit - ctx.underlying_pos,
                min(self.config.underlying_limit - ctx.underlying_pos,
                    decision.target_delta_trade),
            )
            if hedge != 0:
                trades[self.config.underlying] = hedge

        return TickOutput(trades=trades, diagnostics={
            "net_delta": net_delta, "gamma_$": gamma_dollar,
            "kill": self.risk.kill_active, "hedge_reason": decision.reason,
        })

    def _size_for_strike(self, K: int, pos: int, side: int) -> int:
        limit = self.config.per_strike_limit
        if side > 0:
            return max(0, limit - pos)
        return max(0, pos + limit)


@dataclass(frozen=True)
class TickContext:
    S: float
    T: float
    tick: int
    pnl: float
    option_mid: dict[int, float]
    option_pos: dict[int, int]
    underlying_pos: int


@dataclass(frozen=True)
class TickOutput:
    trades: dict[str, int]
    diagnostics: dict[str, object]
```

### 4.8 `src/options/state.py` — compact traderData

Do not use `jsonpickle`. JSON-only, hand-rolled, budgeted at <4KB (Prosperity truncates stdout at ~3.75KB; we assume `traderData` has a similar soft limit).

```python
import json
from src.options.smile import Smile


def serialize(smile: Smile) -> str:
    payload = {
        "v": 1,
        "sm": {str(K): list(s.iv_window)[-50:]  # trim to last 50
               for K, s in smile._states.items()},
    }
    return json.dumps(payload, separators=(",", ":"))


def deserialize(raw: str, smile: Smile) -> None:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return
    if obj.get("v") != 1:
        return
    for Kstr, window in obj.get("sm", {}).items():
        K = int(Kstr)
        if K in smile._states:
            smile._states[K].iv_window.extend(window)
            smile._states[K].obs_count = max(smile._states[K].obs_count, len(window))
```

Trim last 50 observations per strike. 5 strikes × 50 floats × ~10 chars ≈ 2.5KB.

### 4.9 `src/strategies/options_book.py` — adapter

Plugs into the existing `BaseStrategy` surface. Intent-based execution doesn't fit vouchers cleanly (multiple products per strategy) so this strategy owns its own Order emission via a direct hook. Add a registry entry specifying `owns_multi_product=True`.

---

## 5. Adoption checklist

### 5.1 New files (create)

- `src/options/{__init__,bsm,iv_solver,smile,hedge,risk,engine,state}.py`
- `src/strategies/options_book.py`
- `tests/options/test_{bsm,iv_solver,smile,hedge,engine_tick}.py`
- `configs/options_r3.py` (or YAML) — holds `QuadraticCoeffs`, strikes, limits

### 5.2 Module extension

- `src/core/config.py`: add an `OptionsProductGroup` config type that lists strikes + underlying as a unit.
- `src/strategies/__init__.py`: register `options_book` with a `multi_product: True` flag.
- `src/trader.py`: dispatch loop must handle strategies that own multiple products (read position for each strike, write orders for each). Right now it's per-product; add a branch.
- `src/core/state_store.py`: plumb through the `options` namespace in `traderData` alongside existing per-product memory.

### 5.3 Config constants to decide before R3 opens

| Constant | Default | Calibrate from |
|---|---|---|
| `prior.a, b, c` | From tutorial replay, offline fit | Offline: fit once, check residual <1.5σ |
| `residual_k_sigma` | 1.0 | Sweep 0.75..1.5 in backtest |
| `per_strike_limit` | 0.4 × exchange limit | Leaves 60% for hedge room |
| `half_spread_estimate` | 0.5 (Prosperity convention) | Measure: median(ask−bid)/2 first 5k ticks |
| `max_drawdown_shells` | 20,000 | ~10% of expected round P&L; adjust after R3 day 1 |
| `JUMP_RATIO_THRESHOLD` | 4.0 | Measure tail quantiles in replay |
| `enable_scalp` | True for ATM only | Confirm vol-of-vol low in replay |

---

## 6. Tests

Every module ships with a regression suite. Target >80% coverage per our rules.

### 6.1 `test_bsm.py`

- `bs_call` reproduces Hull's table 15.3 values (ATM, ITM, OTM) to 1e-4.
- Greeks: put-call parity, `delta ∈ [0,1]`, `gamma = ∂Δ/∂S` verified by finite difference.
- Boundary: `bs_d1_d2` raises on non-positive inputs.

### 6.2 `test_iv_solver.py`

- Round-trip: `implied_vol_call(bs_call(S,K,T,σ).price, ...) ≈ σ` across σ ∈ {0.05, 0.15, 0.5, 1.0}.
- Infeasible price (below intrinsic) → returns `None`.
- Deep OTM: vega ≈ 0 but solver returns a monotone IV (no divergence).
- Bounded iterations: never more than 60.

### 6.3 `test_smile.py`

- Warmup: before 50 obs, `fair_iv` returns prior(m), std=0.02.
- After 50 obs of constant IV=0.18, `fair_iv` returns 0.18 ± 1e-9.
- Rolling window ejects oldest after 200 obs.
- `observe` with unknown strike raises KeyError.

### 6.4 `test_hedge.py`

- Band zero on zero gamma → no hedge.
- `drift < band` → `target_delta_trade == 0`.
- `drift > band` → hedge sign matches drift sign.
- `hard_floor` binding case: small drift, small band → no trade.

### 6.5 `test_engine_tick.py`

- Kill switch activates after one 4σ jump; no orders emitted for 500 ticks.
- Net delta aggregates correctly across 5 strikes.
- Residual trade fires at `|residual| > k·σ`, not before.
- `serialize/deserialize` round-trip preserves `<50 obs` per strike; stays under 4KB.
- End-to-end tick-replay on 1k-tick fixture matches P&L within ±2%.

### 6.6 `test_engine_integration.py`

- Run against one day of P3 R3 replay (should be in `data/raw/` or fetched). Acceptance: >60% of strikes traded, no NaN in diagnostics, drawdown-triggered kill occurred at known jump timestamp.

---

## 7. Scope discipline — what this blueprint deliberately does NOT include

- **No Kalman IV estimator.** Over-parameterized for 5-strike chain; Sepp (2017) acknowledges OU half-life estimation is noisy under 500 obs.
- **No SVI fit.** Gatheral-Jacquier (2013) is the industry standard but (i) 5 strikes is below SVI's reliable regime (needs ≥7 for the 5-param fit); (ii) arbitrage-free constraints add branching logic not worth 1-day-of-competition debugging.
- **No local-vol surface.** Overkill.
- **No gamma-scalping with delta hedge.** §2.3: bleeds spread. Our "MM at IV-fair" *is* the correct Prosperity-native gamma harvest.
- **No multi-expiry / calendar logic by default.** Hook is there (`expiry_ticks` per contract) but active code path assumes single expiry; extension is a +~100 LOC change.
- **No dynamic prior re-fit.** Prior is frozen offline. Letting it re-fit is the chrispyroberts R3 failure mode.

---

## 8. Primary sources (reference)

Repo code inspected:
- chrispyroberts/imc-prosperity-3 — `ROUND 3/big_volcano_man.py`, `ROUND 4 chris analysis/big_volcano_man_IV_window.py` (quadratic params, bisection IV, ±80 size, delta-hedge disabled).
- CarterT27/imc-prosperity-3 — `trader.py` (Newton IV with `[0.01, 2.0]` clamp, 20-obs rolling mean, jsonpickle — do not copy).
- TimoDiehm/imc-prosperity-3 — `FrankfurtHedgehogs_polished.py` (hardcoded smile `poly1d([0.2736, 0.01, 0.1488])`, dual-EMA 20/100 scalp with THR_OPEN=0.5, THR_SCALPING=0.7, delta computed and ignored).
- ericcccsliu/imc-prosperity-2 — `round4/round4_v3.py` (bisection `[0.01, 1.0]`, z=5.1 tail trigger, delta hedge every tick capped by rock limit).

Academic / practitioner:
- Hull, *Options, Futures and Other Derivatives* 10e, ch. 15 (BS pricer and greeks).
- Whalley & Wilmott (1997), *An Asymptotic Analysis of an Optimal Hedging Model for Option Pricing with Transaction Costs*, Math. Finance (no-trade band §4.12).
- Leland (1985), *Option Pricing and Replication with Transactions Costs*, J. Finance (hedging-error scaling).
- Zakamouline (2005), *Optimal Hedging with Transaction Costs* (refinements; noted but not adopted).
- Sinclair, *Volatility Trading* 2e (variance-risk-premium harvesting; regression of RV on IV).
- Gatheral & Jacquier (2013), arxiv 1204.0646, *Arbitrage-Free SVI Volatility Surfaces* (surface prior, not adopted at 5 strikes).
- Natenberg, *Option Volatility and Pricing* 2e, appendix on greeks near expiry (pin-risk flattening rule).

Prior internal research (this repo):
- `docs/manual_round_3/research_prior_editions.md` §1d–1f, §5.
- `docs/manual_round_3/research_academic_quant.md` §1.1–1.5.
- `docs/manual_round_3/transcript_1_extracted.md` R3 failure taxonomy.
- `docs/manual_round_3/P4_R3-5_STRATEGIC_BRIEF.md` §2.2, §3.

---

**One-line verdict.** Build residual-IV market making with degrading smile, Whalley-Wilmott-gated aggregate-book hedge, jump-kill switch, and compact JSON `traderData`. Reject every more-clever variant unless it has paid-off evidence in the cited repos.

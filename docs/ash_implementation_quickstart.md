# ASH Market-Making Refinements: Implementation Quickstart

## Phase 1: Baseline Calibration (1–2 days)

### 1.1 Estimate Volatility σ

```python
# From recent session data
returns = np.diff(np.log(mid_prices))
sigma_ticks = np.std(returns) * np.sqrt(ticks_per_session)  # scale to daily
# Expected: 4–5 ticks; if < 2, check data quality
```

### 1.2 Estimate Mean-Reversion Speed θ

```python
# AR(1) on residual (wall_mid - fair_value)
residual = wall_mid - ewma_mid
rho = np.corrcoef(residual[:-1], residual[1:])[0, 1]
theta = np.log(1 / rho) if rho > 0 else 0.1  # per-tick
half_life = np.log(2) / theta
# Expected half-life: 5–7 ticks for ASH
```

### 1.3 Estimate Order-Book Liquidity κ

```python
# Poisson regression: count fills vs. quote depth
# For each depth d (0 to 10 ticks from mid), count fills
depths = np.arange(0, 11)
fill_counts = [count_fills_at_depth(d) for d in depths]
# Regress: fill_count = intercept + lambda * exp(-kappa * depth)
# Extract kappa from negative exponential decay
# Expected: 0.1–0.3 per tick
```

### 1.4 Estimate Risk-Aversion Parameter γ

```python
# Method 1: From observed spreads
# Regress: spread ~ 2/gamma * ln(1 + gamma/kappa) + gamma*sigma^2*time_remaining
# Extract gamma from residual-sum-of-squares minimization

# Method 2: From target mid-session spread
target_spread_mid_session = 2  # ticks, adjust to your target
T_mid = 0.5  # fraction of session elapsed
gamma_est = target_spread_mid_session / (2 * sigma**2 * T_mid)
# Expected: 0.002–0.005

# Validate: check that max position skew (80 * gamma * sigma^2 * T) ~ 2–3 ticks
max_skew = 80 * gamma_est * sigma**2 * 1.0
print(f"Max inventory skew: {max_skew:.2f} ticks")  # Should be 1–3
```

---

## Phase 2: Guéant Mean-Reversion Spreads (2–3 days)

### 2.1 Replace Fixed Spread with Adaptive Formula

```python
def guéant_spread(inventory, sigma, kappa, gamma, theta, time_remaining):
    """
    Optimal spread under mean reversion.

    Args:
      inventory: current position q
      sigma: volatility (ticks)
      kappa: order book depth parameter
      gamma: risk aversion
      theta: mean-reversion speed (per tick)
      time_remaining: fraction of session left, in [0, 1]

    Returns:
      half_spread (apply both sides around reservation price)
    """
    # Adverse selection component
    adverse_sel = (2 / gamma) * np.log(1 + gamma / kappa)

    # Mean-reversion component (decays with time)
    mean_rev = (gamma * sigma**2 / (2 * theta)) * (1 - np.exp(-2 * theta * time_remaining))

    return adverse_sel + mean_rev

def reservation_price(mid, inventory, gamma, sigma, time_remaining):
    """Inventory-adjusted fair value."""
    return mid - inventory * gamma * sigma**2 * time_remaining
```

### 2.2 Integration: Quote Formation

```python
def compute_quotes(mid, inventory, time_frac, market_params):
    """Form optimal bid/ask under Guéant model."""
    r = reservation_price(mid, inventory, **market_params)
    delta = guéant_spread(inventory, **market_params)

    bid = r - delta
    ask = r + delta

    return bid, ask, r
```

### 2.3 Validation

- Compare Guéant spreads vs. current fixed spreads over a 100-tick window.
- Expected tighter spreads mid-session, wider near close.
- Run backtests to verify fill rate improvement (expect +3–8% more fills at same spread, or same fills at −3–8 bps tighter spreads).

---

## Phase 3: OFI Gating of Taker Aggression (1 day)

### 3.1 Compute Rolling OFI

```python
def compute_ofi(bid_qty, ask_qty, lookback_ticks=20):
    """Order flow imbalance from best bid/ask levels."""
    buy_qty = np.convolve(bid_qty, np.ones(lookback_ticks), mode='valid')
    sell_qty = np.convolve(ask_qty, np.ones(lookback_ticks), mode='valid')
    ofi = (buy_qty - sell_qty) / (buy_qty + sell_qty + 1e-6)
    return ofi
```

### 3.2 Gate Taker Order Size

```python
def adjust_taker_size(base_size, ofi, threshold=0.3, reduction_factor=0.5):
    """Reduce taker aggression if imbalance is extreme."""
    if abs(ofi) > threshold:
        return base_size * reduction_factor
    return base_size
```

### 3.3 Validation

- Measure adverse-selection cost (fill price vs. mid at fill time) for taker orders.
- Expected reduction of −1–3 bps from gating. Check via P&L impact of taker fills before/after gating.

---

## Phase 4: Cartea–Jaimungal Alpha Skew (1–2 days)

### 4.1 Define Alpha Signal

```python
def compute_alpha_signal(wall_mid, fair_value, history_length=50):
    """
    Alpha = deviation from fair value, in z-scores.

    Args:
      wall_mid: recent wall mid price
      fair_value: ewma_mid or other baseline
      history_length: number of ticks for rolling std

    Returns:
      alpha: z-score deviation
    """
    residual = wall_mid - fair_value
    residual_std = np.std(np.array(residual_history[-history_length:]))
    alpha = (residual / (residual_std + 1e-6))
    return alpha
```

### 4.2 Asymmetric Spread Adjustment

```python
def cartea_jaimungal_spreads(base_half_spread, alpha, beta=0.15):
    """
    Skew spreads based on alpha signal.

    Args:
      base_half_spread: δ from Guéant or Avellaneda–Stoikov
      alpha: z-score signal (mean 0, std 1)
      beta: sensitivity (0.1–0.2)

    Returns:
      ask_half_spread, bid_half_spread (may differ)
    """
    skew = beta * alpha
    skew = np.clip(skew, -base_half_spread/2, base_half_spread/2)

    ask_half_spread = base_half_spread - skew
    bid_half_spread = base_half_spread + skew

    return ask_half_spread, bid_half_spread
```

### 4.3 Full Quote Formation

```python
def compute_quotes_with_alpha(mid, inventory, time_frac, alpha, market_params):
    """Combine Guéant spreads with Cartea–Jaimungal alpha skew."""
    r = reservation_price(mid, inventory, **market_params)
    delta_base = guéant_spread(inventory, **market_params)

    delta_ask, delta_bid = cartea_jaimungal_spreads(delta_base, alpha, beta=0.15)

    ask = r + delta_ask
    bid = r - delta_bid

    return bid, ask, r
```

### 4.4 Validation

- A/B test: quote subset of volume with alpha skew, subset without.
- Expected directional bias: when α > 0 (ask overpriced), you achieve higher fill rate on ask (which you want, to short); when α < 0 (bid overpriced), higher fill on bid (long).
- Expected PnL gain: +2–4 bps on filled volume from better inventory positioning.

---

## Phase 5: Advanced – Position-Sizing via OU Control (Optional, 3–5 days)

### 5.1 Compute Dynamic Target Position

```python
def ou_target_position(mid, mean, theta, inventory_cost, position_limit):
    """
    OU-optimal target position based on price deviation.

    q* = min(Q_max, max(-Q_max, theta * (mean - mid) / (2 * inventory_cost)))

    When price is below mean, you're long; above mean, short.
    """
    deviation = mid - mean
    cost = inventory_cost  # roughly gamma * sigma^2 / 2
    target = (theta * deviation) / (2 * cost)
    target = np.clip(target, -position_limit, position_limit)
    return target
```

### 5.2 Adjust Inventory Skew Toward Target

```python
def inventory_skew_to_target(current_inventory, target, gamma, sigma, time_frac):
    """
    Scale reservation-price skew to pull toward target, not just neutralize.

    Instead of r = s - q * gamma * sigma^2 * T,
    use r = s - (q - target) * gamma * sigma^2 * T
    """
    return - (current_inventory - target) * gamma * sigma**2 * time_frac
```

### 5.3 Validation

- Simulation: run a full session with dynamic target vs. fixed flatten-at-0.7.
- Check inventory distribution at close: should be tighter around 0 with dynamic target.
- Expected gain: +0.5–2 bps from better mean-reversion captures.

---

## Full Integration Example

```python
class ASHMarketMaker:
    def __init__(self, market_params, alpha_beta=0.15, ofi_threshold=0.3):
        self.sigma, self.kappa, self.gamma, self.theta = market_params
        self.alpha_beta = alpha_beta
        self.ofi_threshold = ofi_threshold
        self.position = 0
        self.fair_value_history = []
        self.ofi_history = []

    def update(self, tick):
        """Process one tick and generate quotes."""
        mid = tick.mid
        bid_qty, ask_qty = tick.best_bid_qty, tick.best_ask_qty
        time_remaining = tick.time_frac_remaining

        # Update fair value
        self.fair_value_history.append(self.compute_fair_value())
        fair_value = self.fair_value_history[-1]

        # Compute OFI
        ofi = compute_ofi(bid_qty, ask_qty, lookback_ticks=20)
        self.ofi_history.append(ofi)

        # Compute alpha signal
        alpha = self.compute_alpha_signal(mid, fair_value)

        # Guéant base spreads
        base_delta = guéant_spread(
            self.position, self.sigma, self.kappa, self.gamma,
            self.theta, time_remaining
        )

        # Cartea–Jaimungal skew
        delta_ask, delta_bid = cartea_jaimungal_spreads(base_delta, alpha, self.alpha_beta)

        # Reservation price
        r = reservation_price(mid, self.position, self.gamma, self.sigma, time_remaining)

        # Final quotes
        bid = r - delta_bid
        ask = r + delta_ask

        # Gating for taker orders (if needed)
        taker_size = adjust_taker_size(
            base_size=2, ofi=ofi, threshold=self.ofi_threshold
        )

        return {
            'bid': bid,
            'ask': ask,
            'reservation_price': r,
            'taker_size': taker_size,
            'alpha': alpha,
            'ofi': ofi
        }

    def process_fill(self, side, size, price):
        """Update position on fill."""
        if side == 'buy':
            self.position += size
        else:
            self.position -= size

    def compute_fair_value(self):
        """Placeholder: use ewma_mid or wall_mid."""
        return self.fair_value_history[-1] if self.fair_value_history else 10000

    def compute_alpha_signal(self, mid, fair_value):
        """Alpha as z-score of residual."""
        residual = mid - fair_value
        recent_std = np.std(self.fair_value_history[-50:]) if len(self.fair_value_history) >= 50 else 1
        return residual / (recent_std + 1e-6)
```

---

## Testing & Validation

### Metrics to Track

1. **Fill rate** by distance from mid (should increase near mid after implementation).
2. **Average spread traded** vs. quoted (should tighten).
3. **Inventory P&L** (should improve due to better skew).
4. **Execution quality** on taker orders (should improve after OFI gating).
5. **End-of-session inventory** (should be lower after OU-target implementation).

### Backtest Workflow

```python
# Load replay data
replay = load_ash_replay('round1_stress')

# Run baseline
baseline_results = backtest(replay, use_guéant=False, use_alpha_skew=False, use_ofi_gating=False)

# Run with each mechanism enabled individually
guéant_only = backtest(replay, use_guéant=True, use_alpha_skew=False, use_ofi_gating=False)
alpha_skew_only = backtest(replay, use_guéant=False, use_alpha_skew=True, use_ofi_gating=False)
ofi_gating_only = backtest(replay, use_guéant=False, use_alpha_skew=False, use_ofi_gating=True)

# Run with all enabled
full_integration = backtest(replay, use_guéant=True, use_alpha_skew=True, use_ofi_gating=True)

# Compare PnL, Sharpe, max drawdown, inventory at close
print(f"Baseline:        {baseline_results['pnl']:.2f}")
print(f"Guéant only:     {guéant_only['pnl']:.2f}")
print(f"Alpha skew only: {alpha_skew_only['pnl']:.2f}")
print(f"OFI gating only: {ofi_gating_only['pnl']:.2f}")
print(f"Full integration:{full_integration['pnl']:.2f}")
```

---

## Expected Results Summary

| Mechanism | PnL Impact | Effort | Priority |
|-----------|-----------|--------|----------|
| Guéant mean-reversion spreads | +3–8 bps/fill (+0.7–1.8 ticks/day) | 2–3 days | **1 (HIGH)** |
| OFI gating of taker aggression | −1–3 bps/taker fill (+0.25–0.45 ticks/day) | 1 day | **2 (HIGH)** |
| Cartea–Jaimungal alpha skew | +2–4 bps/fill (+0.4–0.9 ticks/day) | 1–2 days | **3 (MEDIUM)** |
| OU dynamic target positioning | +0.5–2 bps/fill (+0.1–0.4 ticks/day) | 3–5 days | **4 (OPTIONAL)** |

**Total estimated upside: +1.5–3.5 ticks/day (~0.15–0.35% improvement), achievable in 1–2 weeks of implementation.**

---

## Quick Sanity Checks

Before deploying any mechanism:

1. Does the parameter estimate pass a sanity check?
   - σ should be 2–8 ticks (not 0.1 or 50).
   - θ half-life should be 3–20 ticks (not 0.01 or 1000).
   - γ should make max-position skew 1–4 ticks (not 0.01 or 20).

2. Do I see the expected directional effect in backtests?
   - Guéant: spreads should widen near close, tighten mid-session.
   - OFI gating: taker losses should drop when book is imbalanced.
   - Alpha skew: you should fill more on the alpha-favored side.

3. Does PnL improve without drawdown spikes?
   - If PnL improves but max drawdown increases, the mechanism is not robust.

---

## References

- `/docs/market_making_literature_pass.md` — Full theory, formulas, and justification.
- ASH empirical summary: narrow σ=1.04 ticks (residual), mean reversion −0.6 correlation, 16-tick spreads, maker-dominant.

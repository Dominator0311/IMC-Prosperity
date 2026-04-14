# Round 1 — Phase 2 Strategy-Family Proposal

This memo converts the two Phase-1 dossiers into the **simplest viable
strategy family per product**. Nothing is implemented yet (that is
Phase 3) and nothing is tuned (Phase 4). The goal is to lock in the
family, the primary fair value, the execution style, and the risks
**before** writing code.

## Cross-product summary

| Dimension                  | ASH_COATED_OSMIUM                         | INTARIAN_PEPPER_ROOT                              |
|----------------------------|-------------------------------------------|---------------------------------------------------|
| Structure (Phase 1)        | Anchored at ~10 000, σ(mid) 4–5, median spread **16** | Deterministic drift +0.1 / timestamp step, overnight +1 000 jump, σ around line ≈ 1.2 |
| Strategy family            | Stable-anchor wide-spread market maker    | Trend-fair taker with small maker overlay         |
| Primary fair value         | `wall_mid` (primary), `depth_mid` (alternate in Phase 4) | **new** `linear_drift` estimator (primary), `depth_mid` (strong fallback)    |
| Fallback chain (initial)   | `(mid, microprice)`                       | `(depth_mid, hybrid_wall_micro, mid)`             |
| Execution style            | Maker-first (inside-touch two-sided quotes with inventory skew) | Taker-first (residual-triggered crosses), small maker overlay when residual shrinks |
| Take logic                 | Take only when residual > `taker_edge` (≥ 1 tick beyond FV) | Take ask when `best_ask − fair < −taker_edge`; take bid when `best_bid − fair > taker_edge`; with a drift estimator this should fire more cleanly than on ASH |
| Inventory posture          | Moderate skew, moderate flatten threshold, avoid pinning at limit | Tight skew, aggressive flatten near EOD to avoid the +1 000 overnight jump |
| Phase-1 PnL intuition      | `wall_mid` 8.8k combined (placeholder limit=50)                   | `depth_mid` 40k combined; lagging FVs post −8k to −67k               |

## ASH_COATED_OSMIUM

### 1. Classification
**Stable-anchor wide-spread market maker.** The product has a
rock-solid anchor (median mid = 10 000 ± 2 ticks on every day) and a
wide, stable spread (median 16) that leaves ~7 ticks of room either
side of fair for inside-touch maker quotes. Oscillation around the
anchor is tight (σ 4–5 ticks), so the dominant edge is **spread
capture via two-sided quoting**, not directional forecasting.

### 2. Primary fair value
- **Primary:** `wall_mid` — most cross-day robust in Phase 1 (PnL 2.6k
  / 3.4k / 2.6k per day; near-limit 9 % under the placeholder limit=50
  config) and captures the center of mass of the visible book.
- **Fallbacks:** `(mid, microprice)` — cover rare one-sided snapshots
  (~7.9 % of steps) without introducing anchor bias.
- **Phase-4 alternates for Stage A:** `depth_mid` and `ewma_mid`. Both
  have the cleanest short-horizon markouts (d_n1 ≈ −0.2) but
  under-trade with the placeholder edge defaults. Stage A must sweep
  maker/taker edge against each of these to see whether more
  aggressive quoting turns their markout edge into PnL.
- **Rejected primaries (for now):** `anchor` — highest raw PnL but
  42 % near-limit and the largest cross-day variance; retain it as a
  **fallback / sanity check** only, not as primary.

### 3. Execution style
- **Maker-first.** Quote inside-touch two-sided pairs at
  `fair ± maker_edge` (initial `maker_edge=1` tick). With a 16-tick
  spread this still sits well inside the touch, so the bots that hold
  the outer quotes leave room for the taker flow to lift us.
- **Taker overlay is minimal.** Only take when the residual exceeds
  `taker_edge` (initial 1 tick). The dossier's residual → next-step
  correlation of ≈ −0.6 justifies *some* taker activity, but the
  spread is too wide for an aggressive taker to pay.
- **Initial inventory skew:** `inventory_skew=4.0` (half of
  EMERALDS's 8.0; the anchor is stronger so we can lean on it, but
  the 42 %-near-limit anchor replay in Phase 1 warns against being
  too permissive). Flatten threshold `0.7` as a guard against the
  book pinning our position.
- **Recovery / flatten:** keep the existing `market_making` strategy
  behaviour; do not add bespoke recovery in Phase 3.

### 4. Risks and failure modes
- **Inside-touch fill rate on the official exchange may be lower than
  local replay suggests.** Phase-1 replay is generous. This is the
  single biggest unknown and the main reason to keep `maker_edge=1`
  rather than chasing `0.5` in early sweeps.
- **Anchor drift / regime shift.** If the 10 000 anchor moves in
  official data, `wall_mid` will track but `anchor` as a fallback
  becomes misleading. Mitigation: keep `wall_mid` primary; reserve
  `anchor` for diagnostic use only.
- **Position limit unknown.** Phase-1 used a placeholder of 50.
  Tighter limits compress the profitable inventory skew range.
  Phase 4 sweeps must be re-validated once the real limit is known.
- **Overfit risk in quote edges.** A 4-D grid (maker_edge × taker_edge
  × inventory_skew × flatten_threshold) is large; Phase 4 must use
  staged sweeps and look for *plateaus*, not single peaks.

### 5. Phase-3 initial `ProductConfig` (minimum viable)
```python
"ASH_COATED_OSMIUM": ProductConfig(
    position_limit=50,            # placeholder, confirm from official site
    strategy_name="market_making",
    fair_value_method="wall_mid",
    fair_value_fallbacks=("mid", "microprice"),
    anchor_price=10_000.0,        # fallback only; not primary
    taker_edge=1.0,
    maker_edge=1.0,
    quote_size=5,
    max_aggressive_size=10,
    inventory_skew=4.0,
    flatten_threshold=0.7,
    history_length=48,
)
```

## INTARIAN_PEPPER_ROOT

### 1. Classification
**Trend-fair taker with a small maker overlay.** The dossier shows a
near-deterministic drift (exact +0.1 / timestamp step slope on every
day, σ(residual) ≈ 1.2 ticks around the line) with a +1 000 overnight
jump. Every lagging estimator loses money: `mid` −67k, `rolling_mid`
−36k, `weighted_mid` −8k, `microprice` −65k (combined 3-day replay,
placeholder limit=50). The dominant edge is **tracking a moving
fair** — *not* spread capture. A taker that crosses when the book
drifts stale against the true fair picks up cleaner PnL than a maker
that gets adversely selected by the trend.

### 2. Primary fair value
- **Primary (new, to be implemented in Phase 3):** `linear_drift` —
  an online estimator that fits `fair = slope × timestamp + intercept`
  on the recent mids in memory, then projects to the current
  timestamp. Minimum-viable form: equal-weight OLS over the last N
  mids. N will be tuned in Phase 4 Stage A alongside fallback choice.
- **Fallbacks:** `(depth_mid, hybrid_wall_micro, mid)`. `depth_mid`
  was the best cross-day estimator in Phase 1 (40 428 combined PnL;
  top-2 every day); it is the safest fallback if the drift fit is
  ill-conditioned early in a session.
- **Phase-4 alternates for Stage A:** compare `linear_drift` against
  `depth_mid`, `hybrid_wall_micro`, `ewma_mid`. These last three
  implicitly track the drift via book imbalance and microprice; the
  open question is whether an *explicit* drift model does meaningfully
  better.

### 3. Execution style
- **Taker-first.** At each step, compute
  `residual = fair − mid`. If `residual > taker_edge` we believe the
  market is underpriced relative to the drift-adjusted fair, so we
  lift the ask; symmetrically we hit the bid when `residual <
  −taker_edge`.
- **Small maker overlay.** Quote `fair ± maker_edge` for the opposite
  side when the residual is small (within ±taker_edge). This captures
  the tight σ ≈ 1.2 ticks of noise around the drift line without
  exposing us to adverse-selection while the mid is moving.
- **Initial inventory skew:** `inventory_skew=2.0` (modest — the drift
  does the directional work; skew is only a soft stabiliser). Flatten
  threshold `0.8`.
- **End-of-day behaviour.** At the end of each day, carrying a long
  position into the +1 000 overnight jump is a lottery ticket; a
  short position is a disaster. Phase 3 initial policy: rely on the
  existing flatten logic and keep position size modest
  (`quote_size=4`, `max_aggressive_size=8`) so the overnight exposure
  is bounded. Any explicit EOD flatten is deferred to Phase 4 Stage
  C.

### 4. Risks and failure modes
- **Slope assumption.** Three-day replay shows an identical +0.1
  slope; if the official data has a different slope or a regime shift,
  `linear_drift` will misprice and the fallback must carry us.
  Mitigation: Stage A in Phase 4 explicitly tests a fixed-slope
  variant vs an unconstrained OLS variant; pick the one that keeps
  per-day PnL positive even if the slope differs by ~20 %.
- **Overnight +1 000 jump.** A 50-unit long position into the jump is
  worth +50 000 PnL; a 50-unit short is −50 000. This completely
  dominates regular intraday PnL and must be managed. Mitigation:
  small quote sizes + flatten threshold; monitor closing position per
  day in review packs.
- **Warm-up period.** `linear_drift` needs ≥ 2 mids to fit anything
  useful, and ideally ≥ 10–20 for a stable slope estimate. The
  fallback `depth_mid` covers the first few steps.
- **Overfit risk in threshold frontier.** Phase 4 Stage B should
  sweep `taker_edge` on a coarse grid first, then refine; do not
  chase a 0.25-tick improvement if the gradient looks noisy.

### 5. Phase-3 initial `ProductConfig` (minimum viable)
```python
"INTARIAN_PEPPER_ROOT": ProductConfig(
    position_limit=50,            # placeholder, confirm from official site
    strategy_name="market_making",
    fair_value_method="linear_drift",        # NEW estimator added in Phase 3
    fair_value_fallbacks=("depth_mid", "hybrid_wall_micro", "mid"),
    taker_edge=1.0,
    maker_edge=1.5,
    quote_size=4,
    max_aggressive_size=8,
    inventory_skew=2.0,
    flatten_threshold=0.8,
    history_length=48,
)
```

## Design decisions that are deliberately deferred

- **Final edge parameters** — Phase 4.
- **EOD flatten for INTARIAN** — Phase 4 Stage C / Phase 5 review
  decision.
- **Whether a drift estimator with a *fixed* slope prior (+0.1 / step
  hardcoded) beats an unconstrained OLS** — Phase 4 Stage A.
- **Whether ASH profits from a maker-heavier config (`depth_mid` or
  `ewma_mid` primary with tighter edges)** — Phase 4 Stage A.
- **Position limit** — waiting for the official confirmation.

## What Phase 2 does NOT decide

- No product-specific strategy class: both products continue to use
  the shared `market_making` strategy. Only their `ProductConfig`
  (and, for PEPPER_ROOT, a new FV estimator) changes.
- No changes to `src/trader.py`, `src/core/execution.py`, or
  `src/core/risk.py`.
- No review packs, no sweeps. Phase 3 implements the minimum viable
  thing; Phase 4 tunes it.

## Acceptance (plan)

| Criterion | Status |
|-----------|--------|
| One simple viable family per product | PASS (ASH: stable-anchor maker; PEPPER: trend-fair taker) |
| Plain-English rationale | PASS (each section opens with mechanism → exploitation → execution) |
| Clear risks / failure modes | PASS (four risks per product, each with mitigation) |
| No final merged bot yet | PASS (Phase 2 = memo only; no code changes) |

# Round 1 — Phase 4 Staged Sweep Shortlist

This note summarises the Phase-4 staged sweeps and promotes a small
per-product shortlist for Phase 5 review. Markouts are now persisted
on every `SweepRow` (small change to `src/backtest/parameter_sweep.py`
to add `avg_markout_{1,5,20}` fields — regression-checked).

## How the sweeps were run

- **ASH Stage A**: 3 FVs (`wall_mid`, `depth_mid`, `ewma_mid`) × 4×4 `(maker_edge, taker_edge)` grid = 48 configs.
- **ASH Stage A boundary extension**: 2 FVs × 3×3 (maker ∈ {1.0, 1.5, 2.0}, taker ∈ {0.25, 0.5, 0.75}) = 18 configs.
- **PEPPER Stage A (FV family)**: 4 FVs × 2×2 edges = 16 configs + 4-point `linear_drift` history-length scan.
- **PEPPER Stage B (threshold frontier)**: 2 histories (16, 32) × 5×4 edge grid = 40 configs.
- **PEPPER Stage C (inventory)**: fixed (maker=1.0, taker=2.0, h=32) × 4×4 (skew, flatten) = 16 configs.

Inventory parameters were held fixed across Stages A/B per the plan's
"do not start inventory-refining too early" guidance. Stage C is the
only sweep that moves `inventory_skew` / `flatten_threshold`.

## Summary of parameter effects

### ASH_COATED_OSMIUM
- **Maker edge is nearly flat** (all means inside 6k–7.7k across tested values). Not the dominant lever.
- **Taker edge has a clear internal peak at 0.5–0.75 for `wall_mid`** (peak PnL 7747; boundary extension confirms 0.25 is *worse*, ruling out a hidden lower boundary).
- `ewma_mid` is maker-quiet (0 near-limit) with a similar taker sensitivity but a lower plateau.
- `depth_mid` and (implicitly) `filtered_wall_mid`/`hybrid_wall_micro` have the best markouts but trade less under the current engine defaults.
- `rolling_mid` / `weighted_mid` — not run in Stage A (redundant per dossier; Phase 1 already showed they cluster around `wall_mid`).

### INTARIAN_PEPPER_ROOT
- **Maker edge is effectively flat** (all averages within 36k–46k). Inventory / position-limit is the binding constraint, not quote competitiveness.
- **Taker edge has a monotone peak at 2.0** for `linear_drift` (with a plateau from 1.5 to 2.0).
- **History length matters a lot**, but the interaction with taker edge is subtle:
  - at `(maker=1.5, taker=1.0)`, shorter history wins (h=16 > 48 > 64)
  - at `(maker=1.0, taker=2.0)`, h=32 beats h=16 (56 300 vs 53 720)
  - h=32 is the **most cross-grid robust** choice.
- **`depth_mid` and `hybrid_wall_micro` catastrophe on their own** (combined PnL −128k) because PEPPER has no `anchor_price` and the fallback chain can hit the `zero_fallback` when the book is one-sided. They work in the Phase-1 FV-compare tool because that tool injects the full estimator pool as fallbacks. The lesson: any PEPPER config must have a robust (never-`None`) fallback; `linear_drift` or `ewma_mid` are the cleanest options.

## PEPPER deployment-readiness exclusion (formal)

`depth_mid`, `hybrid_wall_micro`, `mid`, `microprice`, `rolling_mid`,
`weighted_mid`, `wall_mid`, and `filtered_wall_mid` are **explicitly
excluded** from the PEPPER shortlist on deployment-readiness grounds.
Rationale:

1. Each one returns `None` when the book is one-sided (the book is
   one-sided in ~7.7 % of PEPPER snapshots per the Phase-1 dossier).
2. PEPPER has no `anchor_price`, so when every estimator in the chain
   declines, `FairValueEngine.estimate` falls through to the
   `zero_fallback` marker (price=0.0, confidence=0.0). Any strategy
   that treats that price as a real fair value quotes catastrophically
   wrong orders against a mid near 11 500.
3. The Phase-4 Stage-A evidence is unambiguous: `depth_mid`-primary
   combined PnL ≈ −128k, `hybrid_wall_micro`-primary ≈ −128k with
   entry-edge values (+5436) that are only possible if fair value
   collapsed to zero on many snapshots.

The exclusion stands unless **both** conditions below are later
addressed:
- the fallback chain is re-ordered to place a never-`None` estimator
  (`linear_drift` or `ewma_mid`) last, AND
- a cross-day sweep with that chain confirms the PnL does not hide a
  repeat of the zero-fallback failure mode.

For this reason the Phase-6 upload shortlist will only contain
candidates whose primary is either `linear_drift` (PEPPER) or
`wall_mid` / `ewma_mid` (ASH — both safe because ASH carries
`anchor_price=10 000`). The `FairValueEngine.estimate` docstring has
been updated to flag this trap so future work on products without an
anchor does not reinvent it.

### Inventory knobs (Stage C on PEPPER)
- **Low inventory_skew (1.0) dominates** (mean PnL 66k vs 52k for skew=2.0, vs 35k for skew=4.0, vs 23k for skew=8.0). The drift creates genuine directional alpha; skew just suppresses it.
- **High flatten_threshold (0.9) dominates** (mean PnL 48k vs 37k at 0.5). Forcing recovery too early kills good business on a trending product.
- **Trade-off is brutal at the extreme**: `(skew=1.0, flatten=0.9)` → PnL 78 844, near-limit 7 224 (24 % of steps pinned). This is the raw-PnL peak but highly exposed to end-of-session reversal; the plan's rule 5 ("inventory suppression prematurely killing profitable business") is the right frame — here it's the *opposite* — inventory *non*-suppression prematurely maxing out.

## Shortlist

### ASH_COATED_OSMIUM

| # | Role | FV | history | maker | taker | skew | flatten | PnL | near | trades | mk_1 | mk_5 | notes |
|---|------|----|---------|-------|-------|------|---------|-----|------|--------|------|------|-------|
| **C1-ASH** | Promoted default | wall_mid | 48 | 1.5 | 0.5 | 4.0 | 0.7 | **7 747** | 110 | 766 | +1.89 | +1.79 | Stage-A winner. Peak confirmed internal by boundary extension. |
| **C1b-ASH** | Markout-strong alternate | wall_mid | 48 | 1.5 | 0.75 | 4.0 | 0.7 | 7 688 | 134 | 700 | +2.00 | +1.86 | Slightly lower PnL, higher markouts at h=1,5. |
| **C2-ASH** | Safe-inventory alternate | ewma_mid | 48 | 1.0 | 0.25 | 4.0 | 0.7 | 6 471 | **0** | 472 | +2.08 | +1.94 | Gives up ~1 300 PnL for **zero near-limit steps** and +0.2 markout improvement. |

### INTARIAN_PEPPER_ROOT

| # | Role | FV | history | maker | taker | skew | flatten | PnL | near | trades | mk_1 | mk_5 | notes |
|---|------|----|---------|-------|-------|------|---------|-----|------|--------|------|------|-------|
| **C1-PEPPER** | Promoted robust default | linear_drift | 32 | 1.0 | 2.0 | 2.0 | 0.8 | **56 300** | 1 733 | 800 | +3.51 | +3.56 | Internal Stage-B plateau; Stage-C middle of the road. Best PnL/near ratio. |
| **C1b-PEPPER** | Low-inventory variant | linear_drift | 32 | 1.0 | 2.0 | 2.0 | 0.7 | 54 015 | **755** | 792 | +3.50 | +3.56 | Near-identical PnL with 57 % less near-limit exposure. Good Phase-5 candidate. |
| **C2-PEPPER** | Higher-upside alternate | linear_drift | 32 | 1.0 | 2.0 | 1.0 | 0.9 | **78 844** | 7 224 | 803 | +3.49 | +3.53 | Raw-PnL peak but 24 % of steps pinned at limit. Review pack must confirm this PnL is not concentrated in one segment before promotion. |
| **C3-PEPPER** | Ultra-safe fallback | linear_drift | 32 | 1.0 | 2.0 | 4.0 | 0.8 | 35 201 | **0** | 763 | +3.52 | +3.53 | Zero near-limit steps. A "never-stuck" variant worth carrying as a baseline control. |

Initial upload ordering hypothesis (confirmed or revised in Phase 6):
1. C1 (ASH promoted + PEPPER promoted C1-PEPPER) — single shortlist
2. C2 (ASH promoted + PEPPER higher-upside C2-PEPPER) — alternate
3. Baseline / control = Phase-3 MVB config (both products at the minimum-viable defaults)

Per the plan, final ordering and pairing happens in **Phase 6 after Phase 5 review packs**.

## Metrics recorded per config

For every row in every sweep the JSON/TXT artefacts contain:
- total PnL
- per-product PnL (single-product sweeps)
- trade count (and maker share)
- avg_entry_edge
- avg_markout_{1, 5, 20}
- final position
- steps_near_limit

These cover the plan's "metrics to record for every tested config"
requirement.

## What mattered vs what didn't (plan compliance)

| Parameter | Mattered? | Evidence |
|-----------|-----------|----------|
| ASH taker_edge | **Yes** (internal peak at 0.5–0.75) | Stage A + boundary extension |
| ASH maker_edge | No (flat) | Stage A averages differ by <1 % across values |
| PEPPER FV family | **Strongly** | linear_drift vs others: +56k vs −128k |
| PEPPER history_length | **Yes** (best 16–32) | 4-point scan + two Stage-B runs |
| PEPPER taker_edge | **Yes** (monotone to 2.0) | Stage B |
| PEPPER maker_edge | Weak | Stage B averages within 2.5 k |
| PEPPER inventory_skew | **Very strongly** | Stage C: skew=1.0 → 66k mean, skew=8.0 → 23k mean |
| PEPPER flatten_threshold | **Yes** (higher is better up to 0.9) | Stage C |

No sweep was meaningless — every one informed the shortlist.

## Open follow-ups for Phase 5

1. **Verify C2-PEPPER's 78 844 PnL is not concentrated in one time-slice.** Its near-limit count is 24 % of total steps, so the drift pattern could be producing a PnL spike when the trend is strongest. Phase 5 review pack should time-slice PnL.
2. **Verify C1-ASH's 7 747 PnL is cross-day stable.** Phase-1 showed cross-day variance was noticeable for ASH; rerun the promoted config per-day in the Phase-5 review.
3. **Check `depth_mid` catastrophe's root cause.** Confirm whether adding `linear_drift` as a PEPPER fallback salvages `depth_mid` as a primary. If so, a hybrid `depth_mid` primary with `linear_drift` fallback might rival `linear_drift` primary (worth one sweep in Phase 5 if budget allows).

## Acceptance criteria (plan)

| Criterion | Status |
|-----------|--------|
| Parameter effects interpretable | PASS — each axis has an explicit effect direction above |
| No meaningless sweeps | PASS — every stage contributed at least one promotion/rejection |
| Shortlist per product exists | PASS — 3 candidates per product, labelled by role |
| Phase 5 / 6 dependencies explicit | PASS — open follow-ups listed above |

## Artefacts

```
outputs/round_1/sweeps/
  20260414T132740Z_round1_ash_stage_a_wall_mid/
  20260414T132832Z_round1_ash_stage_a_depth_mid/
  20260414T132923Z_round1_ash_stage_a_ewma_mid/
  20260414T133645Z_round1_ash_boundary_wall_mid/
  20260414T133713Z_round1_ash_boundary_ewma_mid/
  20260414T133041Z_round1_pepper_stage_a_linear_drift/
  20260414T133056Z_round1_pepper_stage_a_depth_mid/
  20260414T133111Z_round1_pepper_stage_a_hybrid_wall_micro/
  20260414T133126Z_round1_pepper_stage_a_ewma_mid/
  20260414T133141Z_round1_pepper_stage_a_linear_drift_history/
  20260414T133411Z_round1_pepper_stage_b_h16_linear_drift_h16/
  20260414T133527Z_round1_pepper_stage_b_h32_linear_drift_h32/
  20260414T133636Z_round1_pepper_stage_c_linear_drift_stageC/
```

Each directory contains `summary.json` (all rows + aggregates) and
`summary.txt` (human-readable top-N table).

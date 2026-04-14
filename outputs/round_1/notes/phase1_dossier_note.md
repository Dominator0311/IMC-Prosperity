# Round 1 — Phase 1 Completion Note

## What Phase 1 produced

- A reusable, round-1-specific EDA pipeline:
  - `src/scripts/round_1/run_round1_fv_compare.py` — wraps
    `build_fair_value_report` with a local, round-1-only
    `EngineConfig` (the shared default is untouched).
  - `src/scripts/round_1/run_round1_dossier.py` — observation-only
    EDA: per-day price/spread statistics, trend fit, estimator
    residual & mean-reversion diagnostics, microstructure flags.
- Two product dossiers:
  - `outputs/round_1/research/ash_coated_osmium_dossier.md`
  - `outputs/round_1/research/intarian_pepper_root_dossier.md`
- Raw artefacts (JSON + summary.txt):
  - `outputs/round_1/eda/20260414T130527Z_round1_dossier_phase1/`
  - `outputs/round_1/fair_value_comparison/20260414T130741Z_round1_fv_phase1_ASH_COATED_OSMIUM/`
  - `outputs/round_1/fair_value_comparison/20260414T130807Z_round1_fv_phase1_INTARIAN_PEPPER_ROOT/`

## Cross-product summary

| Product | Dominant structure | Best placeholder FV | Alt | Likely execution style |
|---------|-------------------|---------------------|-----|------------------------|
| ASH_COATED_OSMIUM | Stable anchor ≈ 10 000, wide spread (median 16), tight oscillation (σ(mid) 4–5) | `wall_mid` (most cross-day robust; PnL 2.6k / 3.4k / 2.6k) | `weighted_mid`, `rolling_mid` (very similar), `ewma_mid` / `depth_mid` for best markouts | Maker-first, spread capture |
| INTARIAN_PEPPER_ROOT | Deterministic drift +0.1 / step; overnight +1 000 jump; σ around line ≈ 1.2 | `depth_mid` (PnL 40 428 combined; top-2 every day) | `hybrid_wall_micro` (best markouts, zero near-limit); `ewma_mid` (cross-day stable) | Taker-first / mixed; lagging FVs lose |

## Acceptance criteria (plan)

| Criterion | Status |
|-----------|--------|
| Each product has a real dossier | PASS (two dossiers with stats, tables, and conclusions) |
| Hypotheses stated clearly | PASS (both leading hypotheses supported with explicit evidence and caveats) |
| Uncertainty explicit | PASS (each dossier has a "still uncertain" section with Phase 2–4 dependencies) |
| No strategy implementation yet | PASS (scripts only read the book; no `STRATEGY_REGISTRY` changes; no Round-1 product configs promoted into `default_engine_config()`) |

## Phase-level headlines to carry into Phase 2

1. **INTARIAN_PEPPER_ROOT has a deterministic +0.1/step drift that no
   current estimator explicitly projects.** A bespoke trend-fair
   estimator (online OLS or Kalman with known slope prior) is the
   single highest-leverage research idea going into Phase 2.
2. **ASH_COATED_OSMIUM is anchored, wide-spread, and maker-friendly.**
   `wall_mid` is the safest cross-day-robust primary; `ewma_mid` and
   `depth_mid` have cleaner markouts but under-trade with the
   placeholder edge defaults. Phase 4 Stage A should sweep the quote
   edge against each of these primaries.
3. **The local replay fill model is generous.** In particular, the
   `anchor`-as-primary ASH replay keeps 42 % of steps at the position
   limit, which is unlikely to survive an official exchange. Phase 2
   strategy design should **not** assume that kind of inventory
   pinning is free.
4. **Neither product has counterparty IDs.** Bot inference must be
   from size menus, spread stability, and book reshape — not from
   buyer/seller strings.
5. **Position limit is still a placeholder (50).** The real limit
   matters most for ASH (near-limit counts) and for sizing decisions
   on INTARIAN_PEPPER_ROOT (drift direction). Phase 2 cannot finalise
   strategy families without knowing it; everything Phase 4 does must
   be re-validated once the limit is confirmed.

## What is explicitly NOT done (per plan)

- Strategy family proposals — Phase 2.
- Any change to `default_engine_config()` — Phase 3.
- Any parameter sweep or shortlist — Phase 4.
- Review packs / timestamp inspection — Phase 5.
- Official upload planning — Phase 6 / 7.

## Reproducing Phase 1

```bash
PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_dossier --label round1_dossier_phase1
PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_fv_compare --label round1_fv_phase1
```

# Round 5 Setup — Operational Entry Point

Date written: 2026-04-28 (R4 closeout, before R5 open).

This is the **operational** companion to
[`ROUND_4_LESSONS_FOR_ROUND_5.md`](ROUND_4_LESSONS_FOR_ROUND_5.md). The lessons
doc covers strategy and research discipline. This doc covers **what to do
first when R5 data drops** and **which pieces of the repo to reuse vs.
ignore**.

When R5 opens, read this first, then follow the "First 24 Hours Protocol"
section in the lessons doc.

## Repo state at R4 closeout

```
src/
  core/        — engine modules (fair_value, signals, risk, execution, config,
                 logger, market_data, state_store, types, utils, primitives/)
  backtest/    — replay_engine, simulator, fill_model, metrics, sweep,
                 charts, drilldown, parameter_sweep, plateau, reporting
  scripts/
    round_1/   — frozen R1 runners
    round_2/   — frozen R2 runners
    round_3/   — frozen R3 runners (58 files)
    round_4/   — frozen R4 audits + analysis (frozen, do not modify)
    validate_submission.py — validator-clean check
    run_review.py, run_backtest.py, ... — top-level runners
  manual_rounds/ — manual challenge solvers (R2 framework reusable)
tests/         — 996 passing pytest cases
data/raw/      — replay CSVs (per-round)
docs/
  round_3/     — R3 algo postmortem + research memory
  round_4/     — R4 research thread (60+ docs)
  round_5/     — start here
outputs/
  submissions/r4/ — pinned R4 finalists + _archive of 72 alternates
  submissions/r3/ — R3 archived candidates (in docs/round_3 area)
external/      — Kevin Fu's prosperity4bt (gitignored, reclone if missing)
```

Everything under `src/core/` and `src/backtest/` is round-agnostic — reuse
it. Everything under `src/scripts/round_N/` is **frozen historical research**
— do not modify, copy and adapt.

## First commands when R5 drops

```bash
# 1. Sanity: pytest must be green from a clean checkout
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q

# 2. Inspect the R5 data drop (file structure, products, limits)
ls data/raw/round_5/                   # adjust path to actual drop
head data/raw/round_5/prices_*.csv

# 3. Validate a baseline submission against the R5 validator
PYTHONPATH=. .venv/bin/python -m src.scripts.validate_submission \
    path/to/baseline.py
```

If pytest fails on a fresh clone, stop and fix the environment **before**
writing any R5 code. A red baseline means later red runs are ambiguous.

## What's reusable from R4 (high confidence)

### Tooling

| Path | Purpose |
|---|---|
| `src/scripts/validate_submission.py` | Validator-clean check (size + import + class shape). Required before every official upload. |
| `src/backtest/replay_engine.py` | Round-agnostic replay over CSV market data. |
| `src/backtest/simulator.py` | Local fill simulator. Calibrated against R3/R4 official slices — re-validate on first R5 official upload. |
| `src/backtest/fill_model.py` | Passive vs taker fill model. Known to under-fill passive in stale-bid regimes; treat passive PnL as *upper* bound. |
| `src/backtest/metrics.py` | PnL, drawdown, sharpe, per-product attribution. |
| `src/backtest/parameter_sweep.py` | Parameter grid sweeps. Use sparingly — see anti-patterns in lessons doc. |
| `src/scripts/run_review.py` | One-shot replay + report. Good for first-look diagnostics. |
| `external/kevin-bt/` | Community backtester (jmerle lineage). Useful as cross-validation against our simulator. Reclone from <https://github.com/kevin-fu1/imc-prosperity-4-backtester> if missing. |

### Patterns (concrete file pointers)

| Need | R4 file to copy from | Why |
|---|---|---|
| Validator-safe submission shape | `outputs/submissions/r4/submission_r4_final_probe_stack_hyd_abortgate18_long80_60.py` | Live-tested submission, under 100KB, all positions flat at close. |
| Counterparty-conditioned overlay | `outputs/submissions/r4/submission_r4_combo_stack_hyd80_marks_v1.py` (Mark 38 fade overlay) | Reference for adding identity-based gating to a base strategy. |
| Hardflat HYD-style wrapper | `outputs/submissions/r4/submission_r4_safer_hydflat995.py` | Smallest terminal residual pattern. Defensive fallback template. |
| Validated R3-style baseline | `outputs/submissions/r4/submission_r4_exp_flat995_vev5500_sell7_validated.py` | Conservative floor — copy when R5 first needs a sane baseline. |
| Audit script for counterparty/regime/basket | `src/scripts/round_4/audit_*.py` | Templates for new R5 mechanic audits. Adapt, don't extend. |

### Manual rounds

`src/manual_rounds/invest_expand*.py` (branch `round2-manual-challenge`,
documented in repo CLAUDE.md "Manual-round strategy lessons" section) is the
solver framework for any rank-based pillar-allocation game. **Calibration
must be redone per round** (priors are field-specific) but the math is
reusable.

## What to **not** carry forward

- Concrete R4 thresholds (Mark 22 OTM count, HYD 10020 regime gate, VEV
  4000-5200 strike weights). All product-specific.
- The "HYD long target = 80" sizing. R4-specific.
- Mark identity rules (Mark 38 fade, Mark 22 basket). R5 mechanics may not
  involve named counterparties at all.
- Anything in `src/scripts/round_4/audit_*.py` as-is — copy the structure,
  re-derive the thresholds.

## Validator + size checklist

The R4 hard limits (re-verify against R5 announcements):

- Source file: hard 122,880 bytes / soft 98,304 bytes (per
  `src/scripts/validate_submission.py`). Stay under soft.
- No I/O outside the SDK-provided interfaces.
- Position limits per product — read from R5 product spec on day one.
- Terminal positions: design for **flat at close** unless settlement
  mechanics change.

## Disk hygiene before R5

`outputs/round_*/` is gitignored. `r4 Sim Results/` and `Manual r4 test/`
are gitignored. They live on disk for reference. If disk pressure becomes
an issue mid-R5, the safe-to-delete list is:

- `outputs/round_1/`, `outputs/round_2/`, `outputs/round_3/`,
  `outputs/round_4/` (derived; can be regenerated from runners).
- `r4 Sim Results/_extracted_archive/` (44 unzipped folders; the 57 zips at
  top level are the source of truth).
- `external/` (reclone Kevin BT if needed).

Pinned and source-of-truth files (do **not** delete):

- `outputs/submissions/r4/` (5 pinned + `_archive/` + `velvet_probe_ladder/`).
- `data/raw/` (round CSVs).
- `docs/round_*/`.
- `src/`.

## Pre-R5 readiness check

Run this before R5 opens. Anything red is a blocker.

```bash
# Tests green from clean state
PYTHONPATH=. .venv/bin/python -m pytest tests/ -q

# Validator runs (smoke test against a known-good R4 file)
PYTHONPATH=. .venv/bin/python -m src.scripts.validate_submission \
    outputs/submissions/r4/submission_r4_final_probe_stack_hyd_abortgate18_long80_60.py

# Replay engine boots on R3 data
PYTHONPATH=. .venv/bin/python -m src.scripts.run_review --label baseline 2>&1 | tail -5

# Disk usage sane (<5GB target)
du -sh /Users/abhinavgupta/Desktop/IMC
```

Last full check: 2026-04-28. 996 tests passing. Disk ~3.0GB.

## Pointers to deep R4 research (when needed)

When in doubt about a R4 finding, the source-of-truth docs are:

- Strategy postmortem: [`docs/round_4/R4_LIVE_POSTMORTEM.md`](../round_4/R4_LIVE_POSTMORTEM.md)
- Mark mechanic verdict: [`docs/round_4/MARK_EXPLOITABILITY_HONEST_AUDIT.md`](../round_4/MARK_EXPLOITABILITY_HONEST_AUDIT.md)
- Final spine overfit review: [`docs/round_4/FINAL_SPINE_OVERFIT_RISK_REVIEW.md`](../round_4/FINAL_SPINE_OVERFIT_RISK_REVIEW.md)
- VELVET option complex: [`docs/round_4/VELVET_OPTION_COMPLEX_RESEARCH.md`](../round_4/VELVET_OPTION_COMPLEX_RESEARCH.md)
- R3 algo playbook (still load-bearing): [`docs/round_3/ROUND_3_ALGO_POSTMORTEM_AND_PLAYBOOK.md`](../round_3/ROUND_3_ALGO_POSTMORTEM_AND_PLAYBOOK.md)

The R4 research thread has 60+ docs. Most are calibration noise. The five
above plus the lessons doc cover ~95% of what carries over.

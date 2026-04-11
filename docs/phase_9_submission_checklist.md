# Phase 9 — Submission Packaging Checklist

This is the short, action-oriented checklist for turning the live
engine into a Prosperity submission. It is intentionally mechanical.
Anything that requires judgment lives in the phase notes, not here.

Phase 9 builds the *machinery* for packaging. It does **not** finalize
the submission content. Estimator choices, strategy names, config
values, and module inventory are all still in flux in the earlier
phases. The exporter is built to be flexible so changes there do not
require changes here.

**Status: audited and signed off.** The initial scaffold landed in
commit `7c32e23` under a `wip(phase-9)` label. A second pass closed
the five gaps that commit flagged as open (exporter self-check,
two-call smoke, soft size threshold, inline dev-only warning, split
CI gate) and the full submission-critical gate is green. See
[Hardening pass — audited](#hardening-pass--audited) below for the
exact feature list and the gate output.

---

## Pre-submit checklist

Run top-to-bottom before every upload.

- [ ] Working tree is clean (`git status`) — no stray edits in the live
      path that are not in a commit.
- [ ] All earlier phase gates are green (unit tests, backtest review,
      parameter sweep) — see the phase notes in `docs/`.
- [ ] `./scripts/check.sh` passes end-to-end.
- [ ] The bundled file at `outputs/submissions/trader_submission.py`
      was regenerated in this session, not left over from a previous
      run. The checker script regenerates it automatically; if you
      export manually, do it again after your last edit.
- [ ] You have read the top banner of the bundled file and confirmed
      `Datamodel mode: platform` and `Source modules:` matches what
      you expect.
- [ ] The dry-run smoke tests passed (they run as part of `pytest`).
- [ ] The bundled file is under the size budget in the validator
      report.
- [ ] You know which `ProductConfig` values were active at export
      time. Capture them in the commit message or the submission note.

Not part of Phase 9 (do not attempt to check these off here):

- [ ] Final estimator names / final strategy names / final config —
      these are owned by the earlier phases and are allowed to change
      between submissions.

---

## Commands

All commands assume you are in the repo root and have a working
Python environment (the scripts auto-detect `.venv/bin/python`).

### Build the bundle

```bash
# Platform-mode bundle (real submission artifact)
python -m src.scripts.export_submission

# Inline-mode bundle (self-contained, for local smoke testing)
python -m src.scripts.export_submission \
    --datamodel inline \
    --output outputs/submissions/trader_submission_inline.py
```

Default output: `outputs/submissions/trader_submission.py`.

### Validate the bundle

```bash
python -m src.scripts.validate_submission
# or, for a specific file:
python -m src.scripts.validate_submission path/to/file.py
```

Exit code is `0` on OK, `1` on FAIL.

### Dry-run smoke test

The dry run is already part of the test suite:

```bash
python -m pytest tests/test_submission_export.py -q
```

It exports the bundle into `tmp_path`, imports it in isolation with
`importlib.util.spec_from_file_location`, instantiates `Trader`, and
runs it on an empty `TradingState`.

### Full local CI gate

There are two gates in one script:

```bash
./scripts/check.sh                  # repo-wide, honest and noisy
./scripts/check.sh --submission     # submission-critical scope only
./scripts/check.sh --fast           # skip mypy (slowest step)
./scripts/check.sh --export-only    # only export + validate
```

Flags compose: `--submission --fast` runs the packaging scope without
mypy. Use `--submission` before every real upload — it is the signal
that "whatever is in the live path will bundle, validate, and run."
Use the default gate to see every pre-existing issue across the repo.

The script runs each step independently and reports every failure in
one pass, so a single broken lint doesn't mask a broken test.

**Submission-critical scope** (tracked in `SUBMISSION_PATHS` inside
`scripts/check.sh` — keep it aligned with the exporter's
`LIVE_MODULE_ORDER`):

- `src/datamodel.py`
- `src/trader.py`
- `src/core/`
- `src/strategies/`
- `src/scripts/export_submission.py`
- `src/scripts/validate_submission.py`
- `tests/test_submission_export.py`

---

## How the exporter works

Single-sentence version: it reads each live-path file as text, strips
`from __future__ import annotations` and `from src.*` imports, hoists
stdlib imports to the top of the bundle, and concatenates everything
in a hand-maintained dependency order.

Important properties:

- **Deterministic.** Two runs with the same inputs produce the same
  bundle. The tests assert this.
- **Explicit module order.** `LIVE_MODULE_ORDER` in
  `src/scripts/export_submission.py` is the only place that knows what
  the live path contains. Adding a new live module means adding one
  line here.
- **Self-checking.** Before any bundling work, the exporter walks
  every module in `LIVE_MODULE_ORDER`, parses its imports, and
  confirms every `from src.* import ...` target is either also in
  the list or is `src/datamodel.py`. If a live module imports
  something the list does not cover, the exporter raises a
  `RuntimeError` naming the missing module. This catches the #1
  long-term failure mode of a hand-maintained list: forgetting to
  register a new live module.
- **Two datamodel modes.** `platform` (the default, what Prosperity
  actually runs) emits `from datamodel import ...` and is the only
  mode suitable for real submissions. `inline` copies our local
  mirror into the bundle so the file can be imported and smoke-tested
  without any `sys.modules` monkey-patching — but the resulting
  bundle is **DEV-ONLY** and must not be uploaded. The validator
  raises a loud WARN if it sees the inline marker in the bundle
  header.
- **Refuses to "fix" broken input.** If a live module adds an import
  that violates the validator rules, the exporter bundles it
  unchanged and the validator flags it. The split means the exporter
  is simple and the validator is the single source of truth for
  what counts as "submission ready".

---

## What the validator checks

See the top docstring of `src/scripts/validate_submission.py` for the
authoritative list. In short:

**Errors (block the submission):**

- missing `class Trader` at module level
- missing `Trader.run` method
- imports in `FORBIDDEN_IMPORT_ROOTS` (network, subprocess,
  importlib, ctypes, multiprocessing, …)
- imports in `DEV_ONLY_IMPORT_ROOTS` (`src.backtest`, `src.scripts`,
  `tests`, `pytest`, `unittest`, …)
- residual `from src.*` lines (proof the exporter is broken)
- bare `open(...)` or `os.system` / `os.popen` calls
- file size above `MAX_SIZE_BYTES` (hard budget, 96 KiB)
- syntax errors

**Warnings (printed, do not block):**

- file size above `SOFT_SIZE_BYTES` (72 KiB) — operational
  early-warning as the live path grows
- `Datamodel mode: inline` marker in the bundle header —
  dev-only artifact, must not be uploaded
- `Trader.run` has no literal 3-tuple return (static check;
  the dry-run smoke test is the strict one)
- `print(...)` calls (likely debug artifacts — use `logging`)
- `.read_text` / `.write_text` / `.write_bytes` method calls
  (may be false positives)

The validator report header always shows the current size alongside
both thresholds and the percentage used, so size pressure is visible
on every run even when there is no WARN or ERROR.

---

## When things go wrong

| Symptom                                           | Likely cause                                                                            | Fix                                                                            |
| ------------------------------------------------- | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Exporter raises `FileNotFoundError`                | A module listed in `LIVE_MODULE_ORDER` was renamed or deleted                            | Update the list or revert the rename                                           |
| Validator: `residual_src_import`                   | A live module imports `from src.something` that the exporter did not recognise          | Check the import is top-level and uses `from src.x import y` shape             |
| Validator: `forbidden_import`                      | A live module pulled in a networking / subprocess / importlib dependency                | Move that code into `src/backtest/` or `src/scripts/` where it is allowed      |
| Dry-run smoke test fails at `dataclass` decorator   | Test loader forgot to register the module in `sys.modules` before `exec_module`         | The helper in `tests/test_submission_export.py` already does this — do not remove it |
| Bundled file is `> MAX_SIZE_BYTES`                  | Real growth (too much code in the live path) OR a stray large blob committed             | Move non-essential code out of the live path; do not raise the budget casually |

---

## What Phase 9 does not decide

- Which estimator wins for each product.
- Which strategy name maps to which product.
- Which config values to ship.
- Whether a bundled file is "the final" submission.

Those decisions live in later phases. This checklist only exists to
make "turning whatever is in the live path today into an uploadable
file" a zero-judgment operation.

---

## Hardening pass — audited

The initial Phase 9 scaffold shipped in commit `7c32e23` with a
`wip(phase-9)` prefix. That commit message explicitly listed five
gaps and said *"Phase 9 will get its own audit and sign-off commit
once the above gaps are closed."* This section is the audit record.

All five gaps were closed in the same commit as the scaffold (they
were bundled together because the session landing them ran in
parallel with the scaffold session and the `wip` framing was not
refreshed). The `wip` label is retained in commit history but is no
longer accurate as of this doc revision.

### The five hardenings

1. **Exporter self-check against an incomplete `LIVE_MODULE_ORDER`.**
   `verify_live_module_order()` in `src/scripts/export_submission.py`
   walks every module in the hand-maintained order list, parses its
   imports, and refuses to bundle if any `from src.* import …` target
   is not also on the list (with `src/datamodel.py` whitelisted for
   its own platform / inline handling). Unresolvable `src.*` imports
   are surfaced as errors too. This catches the #1 long-term failure
   mode of the explicit-order approach: forgetting to register a new
   live module.

2. **Two-call round-trip smoke test.**
   `test_dry_run_state_round_trips_across_two_calls` in
   `tests/test_submission_export.py` exports an inline bundle, loads
   it via `importlib.util.spec_from_file_location` (with the
   `sys.modules` registration dance required on Python ≥ 3.14 so
   dataclass decorators can resolve `cls.__module__`), instantiates
   `Trader`, and runs it twice. The second call feeds `traderData`
   from the first call back in, and the test asserts that
   per-product `recent_mids` grows from length 1 to length 2 across
   iterations. This is the strict proof that the `StateStore` inside
   the bundled artifact can parse its own output — a one-shot smoke
   cannot prove that.

3. **Soft size threshold.** `SOFT_SIZE_BYTES = 72 KiB` sits below the
   `MAX_SIZE_BYTES = 96 KiB` hard ceiling. The validator raises
   `WARN size_approaching_limit` between the two and
   `ERROR oversize` above. The report header always prints
   `Size: N bytes (soft X, hard Y, P% of soft / Q% of hard)` so the
   current budget posture is visible on every run, not only on
   threshold breach. Current bundle: `50,905 bytes` — 69 % of soft,
   52 % of hard.

4. **Inline datamodel mode marked dev-only.** `--datamodel=inline`
   CLI help now explicitly says the mode is dev-only and must not be
   uploaded. The exporter writes `Datamodel mode: inline` into the
   bundle's top comment banner, and the validator's
   `_check_inline_dev_only` scans the first 400 characters of the
   source for that marker. If present it emits a loud
   `WARN inline_datamodel_dev_only` pointing the operator back at
   `--datamodel=platform`. Both surfaces (CLI and validator) warn,
   not fail, so inline bundles still smoke-test cleanly.

5. **Split CI gate.** `scripts/check.sh` learned a `--submission`
   flag that narrows every step (ruff, black, mypy, pytest) to a
   hard-coded `SUBMISSION_PATHS` list tracking the live path plus
   the Phase 9 packaging surface. `pytest` in submission mode runs
   only `tests/test_submission_export.py`. Flags compose:
   `--submission --fast` runs the submission scope without mypy.
   This replaces the previous operational awkwardness where the
   honest repo-wide gate was always red on unrelated phase-3 WIP
   files and drowned out the submission signal.

### Audit gate result

`./scripts/check.sh --submission`, run against this doc's revision:

```
Scope: submission-critical (7 paths)
==> ruff                ok
==> black --check       ok
==> mypy                ok (Success: no issues found in 19 source files)
==> pytest (submission) ok (29 passed)
==> export_submission   ok
==> validate_submission OK
All checks passed.
```

Validator report on the resulting platform bundle:

```
Size: 50905 bytes (soft 73728, hard 98304, 69% of soft / 52% of hard)
Issues: 0 error(s), 0 warning(s)
Result: OK
```

### Phase 9 sign-off

With all five gaps closed and the submission gate green, Phase 9 is
**audited and ready for round-day use**. The only remaining judgment
calls (final estimators, strategy names, config values, submission
content) belong to later phases and are explicitly out of scope per
the ["What Phase 9 does not decide"](#what-phase-9-does-not-decide)
section above.

If a future change to the live path breaks any of the above
guarantees, the right response is to reopen this section, not to
paper over it.

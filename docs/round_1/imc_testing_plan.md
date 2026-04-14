# Round 1 — Phase 7 Official IMC Testing Plan

This document is the **testing plan** for the Round-1 official-site
upload pass. It covers what to record, in what order, and how to
interpret divergences between the local Phase-5 review-pack
predictions and the official-site results.

It is the companion to `docs/round_1/upload_plan.md`, which decided
*what* to upload. This document covers *how to test* what was
uploaded.

## Upload sequence (recap from Phase 6)

1. `outputs/submissions/round_1/trader_round1_baseline.py`
2. `outputs/submissions/round_1/trader_round1_promoted.py`
3. `outputs/submissions/round_1/trader_round1_alt.py`

Wait for each result before uploading the next.

## Per-submission results capture

For every submission, fill in this template before uploading the next
one. Save under `outputs/round_1/notes/imc_results_<variant>.md` once
filled.

```markdown
# IMC Round-1 official result — <variant>

## Identity
- Submission file: outputs/submissions/round_1/trader_round1_<variant>.py
- Bundle banner commit: <copy from "# Built : ... (commit XYZ)" header>
- Upload timestamp (local): YYYY-MM-DD HH:MM
- Round / day on the official site: <e.g. Round 1, full run>

## Headline metrics
- **Total official PnL:**
- **Per-product PnL (if reported):**
  - ASH_COATED_OSMIUM:
  - INTARIAN_PEPPER_ROOT:
- **Trade count (if reported):**
- **Final position (if reported):**
- **Cumulative-PnL curve shape:** monotone / volatile / clustered / unknown

## Stability / sanity flags
- Any submission errors or platform warnings:
- Any obvious divergence from local replay (huge inventory swing,
  zero-fill product, position-limit hit, etc.):
- Repeatability — if the official site allows multiple runs, was
  ranking consistent across runs?

## Free-text observations

```

## Comparisons to make as results arrive

After each upload completes, compare to the prior result(s) using the
table below. Fill in only the cells that are observable on the
official site.

| Comparison | Local (Phase 5) | Official (Phase 7) | Verdict |
|------------|-----------------|---------------------|---------|
| Baseline total PnL | +24 k (combined sample) | <fill> | (set the reference) |
| Promoted vs Baseline (ASH) | +6 447 vs +5 100 (Phase 3 ASH) | <fill> | promoted should win on ASH |
| Promoted vs Baseline (PEPPER) | +54 015 vs +16 418 | <fill> | promoted should clearly win |
| Promoted vs Baseline (total) | +60 k vs +24 k | <fill> | promoted should win |
| Alt vs Promoted (PEPPER) | +78 844 vs +54 015 | <fill> | alt wins iff drift persists & limit pinning is not penalised |
| Alt vs Promoted (ASH) | +7 747 vs +6 447 | <fill> | alt wins iff taker-heavy fills survive |
| Alt vs Baseline (total) | +87 k vs +24 k | <fill> | alt should win on PnL but cost more risk |

## Decision rules (per the implementation plan)

> **Trust IMC.** When local and official disagree, the official
> result is the source of truth. Use the local tools only to explain
> the divergence and to generate a better candidate next pass.

Specific reaction matrix:

| Pattern | Likely cause | Action |
|---------|--------------|--------|
| **Promoted ≪ baseline on ASH** | Local fill model is materially more generous than official; ewma_mid's markout edge does not translate. | Revert ASH default to wall_mid (baseline). Investigate fill-model assumptions before next pass. |
| **Promoted < baseline on PEPPER** | The +0.1/step drift does not exist on the official run, OR `linear_drift` warm-up is being penalised differently. | Compare PEPPER per-day PnL on the official site. If day -2 looks fine and day 0 does not, the drift broke. |
| **Promoted ≈ baseline on PEPPER, both negative** | Drift assumption invalid altogether on the official data. | Re-run the Phase-1 dossier on the official-data sample once available. Re-evaluate `depth_mid` / `ewma_mid` as primary. |
| **Alt ≫ promoted on PEPPER** | The official fill model rewards more aggressive inventory under drift; C2's directional bet paid off. | Promote alt's PEPPER config in a future pass after sweeping the inventory frontier wider in Phase 4.5. |
| **Alt ≪ promoted on PEPPER** | The drift paused / reversed at some point or near-limit pinning interacted badly with the official fill model. | Phase 4.5 should sweep `flatten_threshold` more granularly between 0.7 and 0.9. |
| **Alt ≈ promoted within noise on PEPPER** | The 4× extra near-limit exposure did not earn its keep; promoted's robustness wins. | No action; promoted remains the default. |
| **All three submissions wildly different from local replay** | Likely position-limit or cadence mismatch; the Phase-1 placeholder limit=50 is the most likely culprit. | Confirm the official limit, re-export all three bundles, retry. |
| **All three look reasonable but ranking is reversed** | Local replay is over-fitting to the 3-day sample. | Down-weight any future local-replay-only optimisation; consider shipping the baseline as the default in the next round until more official-data samples are available. |

## What not to do

Per the plan's "what not to do" section:

- Do not retune locally on a single official-PnL data point. One
  official run is one sample.
- Do not promote a config that beat baseline on the official site
  but was excluded from the Phase-6 shortlist on robustness grounds
  without re-running the Phase-5 review on the new official data.
- Do not modify `default_engine_config()` or the Round-1 factories
  in `src/core/config.py` based on a single official run; the
  factory functions are the named, audited Phase-6 configs and
  changing them silently breaks the audit trail.
- Do not upload a fourth file ad-hoc. If a result demands one, treat
  it as a Phase-4.5 / Phase-5.5 follow-up and re-run the relevant
  shortlist work first.

## Carry-outs for the round-1 final memo

Once all three submissions are recorded, populate
`docs/round_1/round1_research_memo.md` (Phase 8 deliverable) with:

- Per-product conclusions in light of the official results.
- Whether the local fill model is trustworthy for Round 2 work.
- Whether the +0.1/step PEPPER drift was a sample artefact or a
  durable feature.
- The recommended config for the **next** round's first MVB pass.

## Acceptance criteria (plan)

| Criterion | Status (now) | Definition of done (after uploads) |
|-----------|--------------|------------------------------------|
| Upload order recommended | PASS | n/a |
| Per-submission result template ready | PASS | One filled file per variant under `outputs/round_1/notes/` |
| Comparison framework explicit | PASS | Per-cell verdicts filled in the comparison table |
| Decision rules pre-committed | PASS | Each official-result pattern maps to a documented action |

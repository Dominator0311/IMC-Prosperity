# Round 1 — Phase 5 Review Plan

This note scopes Phase 5 **before** any review packs are generated.
Phase 5 is **not** another tuning phase. It is a **diagnostic phase**
whose job is to explain why the Phase-4 shortlist candidates win and
to eliminate the ones whose wins are fragile.

## Scope (fixed; do not expand without revising this plan)

### Candidates to review

| Product | Candidates | Purpose |
|---------|------------|---------|
| ASH_COATED_OSMIUM | C1 (wall_mid, maker=1.5, taker=0.5), C2 (ewma_mid, maker=1.0, taker=0.25) | Decide whether C1's higher PnL survives simulator-fill scrutiny or whether the zero-near-limit C2 is the genuine production pick. |
| INTARIAN_PEPPER_ROOT | C1 (linear_drift h=32, maker=1.0, taker=2.0, skew=2.0, flatten=0.8), C1b (same but flatten=0.7), C2 (skew=1.0, flatten=0.9 — raw-PnL peak), optionally C3 (skew=4.0 — zero-near-limit) | Decide whether the raw-PnL peak C2 has real edge or is a near-limit artefact. Decide between C1 and C1b on inventory cleanliness. |

Excluded PEPPER candidates (see `phase4_sweep_shortlist.md` for the
formal exclusion rationale): `depth_mid`, `hybrid_wall_micro`, `mid`,
`microprice`, `rolling_mid`, `weighted_mid`, `wall_mid`,
`filtered_wall_mid`. They fail the robust-fallback test on a product
without an `anchor_price`.

### Questions Phase 5 must answer

1. **Is PEPPER C2's +78 844 PnL real edge, or a limit-pinning
   artefact?** C2 spends 7 224 steps (24 %) at the position limit.
   The review must show whether PnL accrues **steadily across all
   three days and all four intraday quartiles**, or whether it comes
   from one segment where the drift aligns the inventory with the
   limit. A Pn-per-slice bar chart with the near-limit count per
   slice will decide this in one pass.
2. **C1 vs C1b for PEPPER** — which is the cleaner production
   candidate? C1 (flatten=0.8) and C1b (flatten=0.7) differ by ~4 %
   PnL and 57 % in near-limit count. We need to see whether C1b
   leaves money on the table because it flattens too early, or whether
   the lower limit exposure is "free" (same markout quality).
3. **ASH C1 vs C2** — is C1 (wall_mid) genuinely better, or does it
   rely on local-replay fill generosity that the official exchange
   will not reproduce? Diagnostic: trade-by-trade breakdown of C1's
   taker fills — specifically whether the winning trades are
   inside-touch (fills any market-maker would get) or tight-touch
   (fills that require aggressive taker priority which the official
   fill model may not grant). C2 is the natural fallback if C1's
   edge is fill-assumption-heavy.
4. **PEPPER day-boundary behaviour** — what happens on the +1 000
   overnight jump? Specifically, end-of-day positions, sign of
   position right before the jump, and PnL-per-day-transition impact.
   This also lets us decide whether adding a **flatten-before-boundary
   policy** (force flat on the last N steps of each day) would help
   or hurt.

### Questions Phase 5 must NOT re-open

- Does a different FV family beat `linear_drift` for PEPPER? (Closed
  in Phase 4 Stage A.)
- Does a different maker/taker edge beat the Stage-B peak? (Closed in
  Phase 4 Stage B; C2 skew=1.0 is intentionally kept as a high-upside
  alternate even though it was not the Stage-B edge winner.)
- Does a shorter history_length for PEPPER beat h=32? (Closed by the
  Stage-A history scan + Stage-B h=16 vs h=32 cross-check.)
- Does ASH benefit from a `rolling_mid` or `weighted_mid` primary?
  (Phase-1 dossier already showed they cluster around `wall_mid`.)

If new evidence in Phase 5 suggests we should re-open any of these,
that goes into a Phase 4.5 follow-up note — not into Phase 5.

## Deliverables

Per the plan, Phase 5 produces:

1. **Review packs** — one per candidate, using the existing
   `src.backtest.drilldown` + `drilldown_writer` + `drilldown_charts`
   pipeline. Each pack shows:
   - price vs fair
   - trades on chart
   - position path
   - cumulative PnL
   - suspicious timestamps (best/worst trades by markout)
   - concentration of PnL by slice
   - whether edge is steady or clustered
   - inventory behaviour
2. **A PEPPER day-boundary analysis** — a focused script that reports:
   - EOD position for each candidate on each day
   - per-day-transition PnL delta (attributable to overnight jump vs
     intraday trading)
   - expected PnL of a hypothetical flatten-before-boundary overlay
     applied after the fact to each candidate
   Target file: `src/scripts/round_1/run_round1_day_boundary_check.py`.
3. **Interpretation notes** per candidate:
   `outputs/round_1/research/<candidate>_review_notes.md` with:
   - verdict (promote / alternate / drop)
   - what the review showed
   - what remains uncertain
4. **Phase-5 shortlist update** — a revised shortlist that either:
   - confirms the Phase-4 promoted defaults, or
   - downgrades a candidate based on review findings, or
   - elevates an alternate.

File: `outputs/round_1/notes/phase5_review_shortlist.md`.

## Acceptance criteria (plan)

| Criterion | Status at Phase-5 end |
|-----------|-----------------------|
| Candidates evaluated visually and mechanically | Review pack + interpretation note per candidate |
| Weak / noisy candidates filtered out | Explicit verdict per candidate |
| Surviving shortlist small and explainable | Phase-5 shortlist names ≤ 3 per product |
| No broad tuning | No new sweep grids beyond the targeted day-boundary check |

## Phase 6 handoff (what this note does not decide)

The **upload ordering** and the **baseline/control choice** are Phase
6 decisions. Phase 5 only needs to produce the shortlist; Phase 6
sequences it.

## Rules of engagement for Phase 5 work

- **No new sweep grids.** If you're tempted to sweep a new parameter
  because a review pack surprised you, write it up as an open
  question and leave the sweep to a follow-up pass.
- **Every review pack must answer at least one of the four questions
  above**, otherwise it is out of scope for this phase.
- **Evidence calibration** (project CLAUDE.md): any claim like "the
  edge is real" must be phrased as "under the current local replay"
  or "leading hypothesis supported by current sample" until the
  official IMC exchange validates it.

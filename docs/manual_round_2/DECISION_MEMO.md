# P4-R2 Invest & Expand — Final Decision Memo (v2)

**Updated 2026-04-19** after integrating the IMC Prosperity 4 community
Discord poll signal (42 voters, closed 2026-04-18). Supersedes v1.

## TL;DR

**Primary submission: `(r=17, s=50, v=33)`**. Weighted-meta-regret
winner at E[PnL] = 209 954 XIREC under a Discord-informed prior mix.
Expected VoI on this pick is only 22k — the decision is robust.

**Backup (late-swap candidate): `(r=16, s=50, v=34)`** — near-tie on
expected PnL but breaks any v=33 Schelling tie in our favour. Switch
to this if we suspect a large cluster exactly at v=33.

**Do NOT submit** `(23, 77, 0)` — dominated on every realistic prior.

## What changed between v1 and v2

1. Integrated the IMC community Discord poll with 42 voters:
   - 17% at v=0 (coaster cluster)
   - 21% at v=90-100% (*critical upper tail, spite/trolling hypothesis*)
   - 34% at v=10-40% (rational middle)
2. Added three Discord-informed priors: `discord_poll_raw_p4r2`,
   `discord_poll_discounted_p4r2`, `discord_realistic_blend_p4r2`.
3. Explicit subjective prior weights (`default_subjective_weights()`).
4. Weighted meta-regret replaces minimax as the primary criterion.
5. VoI analysis quantifies how much future signal would improve the pick.
6. Confirmed gabsens P2-R3 Excel is NOT relevant (different mechanic).

## Weighted meta-regret top 7 (all on the v ∈ [33, 41] plateau)

| alloc | E[PnL] | worst PnL | worst prior |
|---|---:|---:|---|
| **(17, 50, 33)** | **209 954** | -6 160 | all_half_schelling |
| (16, 50, 34) | 207 091 | -7 027 | all_half_schelling |
| (16, 49, 35) | 204 182 | -7 887 | all_half_schelling |
| (16, 48, 36) | 201 181 | -8 746 | all_half_schelling |
| (16, 47, 37) | 198 089 | -9 606 | all_half_schelling |
| (15, 45, 40) | 195 223 | -12 152 | all_half_schelling |
| (15, 44, 41) | 193 943 | -12 993 | all_half_schelling |

The weighted optimum shifted **down** from (16, 48, 36) in v1 to
(17, 50, 33) in v2. The Discord-informed blends (55% cumulative
weight) select v=33 as BR because the naive-thirds cluster is a
strong Schelling point that tying into wins on μ without extra v-cost.

## Per-prior best response

| Prior | BR alloc | μ_exp | BR net PnL |
|---|---|---:|---:|
| discord_poll_raw | (18, 58, 24) | 0.46 | 188 305 |
| discord_poll_mild_discount (30%) | (16, 49, 35) | 0.59 | 200 322 |
| discord_poll_heavy_discount (70%) | (15, 46, 39) | 0.71 | 223 300 |
| discord_blend_35pct_engage | (17, 50, 33) | 0.57 | 200 792 |
| discord_blend_50pct_engage | (17, 50, 33) | 0.57 | 201 757 |
| discord_blend_20pct_engage | (17, 50, 33) | 0.57 | 199 828 |
| rjav1_blend_ensemble | (15, 45, 40) | 0.75 | 234 137 |
| maf_cluster_v5_heavy | (22, 70, 8)  | 0.55 | 316 656 |
| maf_cluster_v27_meme | (17, 50, 33) | 0.62 | 221 980 |
| all_coast | (23, 77, 0) | 0.90 | 618 097 |

## Value of information

| committed pick | E[VoI] | implication |
|---|---:|---|
| (17, 50, 33) | 22 543 | 11% of E[PnL]: robust |
| (16, 50, 34) | 25 406 | slightly more regret |
| (16, 49, 35) | 28 316 | more regret |

Biggest VoI for (17, 50, 33) concentrated in tail priors:
- Knowing `all_coast` true → switch to (23, 77, 0) for +273k (weight 5%)
- Knowing `all_half_schelling` true → switch to (13, 37, 50) for +222k (weight 2%)
- Knowing `maf_v5_heavy` true → switch to (22, 70, 8) for +60k (weight 5%)

The pick is DOMINANT under the discord_blend family (zero VoI) which
hold 45% of weight. Only tail scenarios would flip the pick; we
consider those unlikely.

## Execution plan

1. **T–24h (now)**: submit `(r=17, s=50, v=33)`.
2. **T–6h**: check late Discord/X signal or leaderboard access. If
   the v≥90 tail hypothesis gets corroboration (multiple public v=95
   commits), update prior and rerun:
   ```bash
   PYTHONPATH=. .venv/bin/python -m src.scripts.run_manual_invest_expand_final --n-opponents 4500
   ```
3. **T–1h**: final look. Hold v=33 unless signal decisively moved the
   field mean above 40.
4. **At lock**: Tier 1 submission, unless a signal has flipped it.

## Running the analytics

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_manual_invest_expand.py -v
PYTHONPATH=. .venv/bin/python -m src.scripts.run_manual_invest_expand        --n-opponents 4500
PYTHONPATH=. .venv/bin/python -m src.scripts.run_manual_invest_expand_sensitivity
PYTHONPATH=. .venv/bin/python -m src.scripts.run_manual_invest_expand_deep
PYTHONPATH=. .venv/bin/python -m src.scripts.run_manual_invest_expand_final  --n-opponents 4500
```

## Files (branch `round2-manual-challenge`)

```
src/manual_rounds/
  invest_expand.py                     core math, 300 LOC
  invest_expand_priors.py              17 priors incl. Discord-aware
  invest_expand_equilibrium.py         QRE + regret table
  invest_expand_deep.py                MC, level-k, adversarial, phase diagram
  invest_expand_decision.py            weighted meta-regret + VoI
src/scripts/
  run_manual_invest_expand.py          base runner
  run_manual_invest_expand_sensitivity.py
  run_manual_invest_expand_deep.py
  run_manual_invest_expand_final.py    final decision runner
tests/test_manual_invest_expand.py     52 tests, all passing
docs/manual_round_2/
  HANDOFF_CONTEXT.md                   original session brief
  DECISION_MEMO.md                     this file
Manual Round 2/                        untracked user-supplied inputs
  discord sunday.txt                   1935-line community chat log
  round 3 manual.xlsx                  gabsens P2-R3 sheet (not relevant)
```

## Subjective weights (commit explicit belief)

Dated **2026-04-19**, in `default_subjective_weights()`:

```
discord_poll_raw                   0.05   # raw poll probably biased
discord_poll_mild_discount         0.10   # small troll discount
discord_poll_heavy_discount        0.05   # heavy discount, less plausible
discord_blend_35pct_engage         0.25   # primary realistic guess
discord_blend_50pct_engage         0.10
discord_blend_20pct_engage         0.10
rjav1_blend_ensemble               0.10   # pre-Discord ensemble
maf_cluster_v5_heavy               0.05   # MAF fragility scenario
maf_cluster_v27_meme               0.05   # "speed=27" Discord meme
all_thirds_schelling               0.03   # Schelling worst-case
all_half_schelling                 0.02   # Schelling worst-case
all_coast                          0.05   # coasters Schelling
uniform_flat                       0.05   # no-info baseline
```

Swap to taste and re-run to sensitivity-test.

## What could still change the pick

1. **Live R2 leaderboard data** via API probing (in progress).
2. **Confirmed UI slider default value** — if defaults at v=50 or
   v=33, expect Schelling cluster at that value.
3. **Late Discord convergent public consensus at specific v != 33**.
4. **Official admin clarification** on tie-rule.

## Discord signal — critical analysis (not just noise)

**Valid signal** (high confidence):
- 17% at v=0 — consistent with quoted "73% got 0 last round"
- 21% at v=90-100% — from spite voters + "100 speed to grief coasters"
- Cluster at v=20-40 (34% of poll)
- "Speed=27" meme — multiple explicit mentions create Schelling

**Noise / discounted**:
- Self-selected Discord sample (42 ≠ 4500 field)
- "69%", "69420%" — obvious trolling
- "51% because math" — flawed reasoning
- "I'll grief" posturing probably partially theatre

## Do NOT submit

- `(23, 77, 0)` — dominated, 140k weighted mean
- `(22, 73, 5)` — MAF-fragility trap, 130k weighted mean
- `(13, 37, 50)` unless cluster-at-50 signal firms up — 181k weighted
  mean, 27k below Tier 1
- `v > 60` — waste of budget

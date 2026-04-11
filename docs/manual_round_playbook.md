# Manual Round Playbook

Round-day operator guide. Use this when a manual round opens on the
Prosperity portal. The goal is to go from "round page visible" to
"answer submitted" in under 90 minutes without introducing process
errors.

## Step 0 — Read the round page end-to-end before touching code

Do not start coding until you understand:

1. What you are being asked to submit (single number? list of bids?
   set of cells? position vector?).
2. What the payoff formula is (write it out on paper).
3. Whether other teams' answers affect yours.
4. What the fees / budgets / constraints are.

If any of those four is unclear, re-read. Misclassifying the round is
the single most expensive mistake.

## Step 1 — Classify the round (under 10 minutes)

Match the puzzle to one of the five recurring families:

| Symptoms | Family | Runner |
|---|---|---|
| A rate/conversion matrix over a small set of items, bounded trades, start/end nodes | **graph/path** | `run_manual_graph` |
| One or two sealed bids against a known reserve distribution, resale at fixed value, no opponent coupling | **bid** | `run_manual_bid` |
| A grid of cells with multipliers and base inhabitants, you pick 1–3, payoff dilutes when others pick the same cell | **crowding** | `run_manual_crowd` |
| A sealed-bid problem *plus* a penalty that depends on the average of other teams' bids | **hybrid_bid** | `run_manual_hybrid` |
| 9-ish named products, news PDF, integer % positions, quadratic fee, L1 budget (usually 100) | **news portfolio** | `run_manual_news` |

If the puzzle looks hybrid, pick the *dominant* family first. If it
looks like something new, fall back to pen and paper — do not force-fit
an existing runner.

## Step 2 — Write the input JSON

Each runner takes a single JSON file. Copy the worked example from
`src/manual_rounds/README.md` into `inputs/round_N.json` and edit only
the round-specific fields.

Templates for each family:

### Graph (`run_manual_graph`)

```json
{
  "round": "P4-R1",
  "currencies": ["A", "B", "C", "D"],
  "rates": [[1.0, 1.4, 0.5, 0.7], [0.7, 1.0, 0.3, 0.5],
            [1.9, 3.1, 1.0, 1.5], [1.3, 2.0, 0.6, 1.0]],
  "start": "D",
  "end": "D",
  "max_hops": 5,
  "top_k": 5
}
```

### Bid (`run_manual_bid`)

```json
{
  "round": "P4-R?",
  "distribution": {
    "type": "linear_ramp",
    "low": 900,
    "high": 1000
  },
  "resale_value": 1000,
  "bid_grid": {"start": 900, "stop": 1001, "step": 1},
  "n_bids": 2,
  "top_k": 10
}
```

`"type"` supports `uniform`, `linear_ramp`, and `bimodal`. For bimodal,
supply `low_a`, `high_a`, `low_b`, `high_b`, and optional `mass_low`.

### Crowding (`run_manual_crowd`)

```json
{
  "round": "P4-R2",
  "cells": [
    {"name": "C1",  "multiplier": 10, "inhabitants": 1},
    {"name": "C2",  "multiplier": 80, "inhabitants": 6},
    {"name": "C3",  "multiplier": 37, "inhabitants": 3}
  ],
  "base_treasure": 10000,
  "coupling": 100,
  "pick_fees": [0, 50000],
  "max_picks": 2
}
```

Tune `optimistic_exponent` (default 0.5) and `pessimistic_exponent`
(default 3.0) only if the round framing suggests a highly rational or
highly irrational crowd.

### Hybrid (`run_manual_hybrid`)

```json
{
  "round": "P4-R3",
  "distribution": {
    "type": "bimodal",
    "low_a": 160, "high_a": 200,
    "low_b": 250, "high_b": 320,
    "mass_low": 0.5
  },
  "resale_value": 320,
  "bid_grid": {"start": 160, "stop": 321, "step": 1},
  "alpha": 3.0,
  "mu_scenarios": {
    "base": 287,
    "optimistic": 280,
    "pessimistic": 300
  }
}
```

Use `alpha=1.0` for P2-R4-style linear penalty, `alpha=3.0` for
P3-R3-style cubic penalty.

### News (`run_manual_news`)

```json
{
  "round": "P4-R5",
  "capital_per_unit": 10000,
  "fee_coefficient": 120,
  "budget": 100,
  "products": [
    {"name": "Haystacks",   "expected_return": -0.005, "rationale": "neutral"},
    {"name": "Red Flags",   "expected_return":  0.050, "rationale": "bullish"}
  ],
  "sensitivity_shift": 0.02,
  "shrink_factor": 0.7
}
```

Per-product `expected_return` is your sentiment-derived estimate
(signed float, e.g. `+0.05` = +5%).

## Step 3 — Run the solver

```bash
PYTHONPATH=. python -m src.scripts.run_manual_crowd \
    --input inputs/round2_containers.json \
    --output outputs/manual_rounds/round2_containers
```

Runtime is milliseconds for every family. If it takes longer than a
second, something is wrong with the input.

## Step 4 — Read the artifacts

Every run produces exactly these five files in `<output_dir>`:

- `answer.json` — the chosen answer and its net value
- `top_alternatives.json` — ranked alternatives you considered
- `assumptions.json` — the exact inputs the solver saw (always re-read
  before submitting — catches typos in the round JSON)
- `sensitivity.json` — base / optimistic / pessimistic / robust
- `submission_note.md` — rendered markdown for the checklist

**Always diff `assumptions.json` against the round page before
submitting.** This is your defense against misreading a multiplier or a
fee by one digit.

## Step 5 — Decide: base or robust?

- **Graph & bid rounds**: the base answer and the robust answer are the
  same. Ship the base answer.
- **Crowding**: ship the robust bundle unless the base margin is very
  large (> 2x the additional-pick fee). If base is only marginally
  better than robust, robust wins.
- **Hybrid**: the hybrid runner's "best" is already the worst-case
  robust answer across your mu scenarios. Ship it.
- **News portfolio**: inspect both the base and the robust position
  vector. If they differ a lot, your sentiment estimates are fragile —
  re-read the news PDF before trusting either one.

## Step 6 — Submit, then paste the submission note into your notes

Submit via the Prosperity portal. Then copy `submission_note.md` into
`outputs/notes/round_N_manual.md` so you have an audit trail. If the
round later reveals the realised answer, diff your chosen answer
against what paid, and add the lesson to the round retrospective.

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError: inputs/round_N.json` | Input path typo | Use a relative path from repo root |
| Crowding scenarios all agree on a weird cell | Your `optimistic_exponent` / `pessimistic_exponent` aren't spreading the prior enough | Widen the exponents (e.g. 0.3 and 4.0) |
| News portfolio returns all zeros | Every `expected_return` is < `2 * fee_coefficient / capital_per_unit` in magnitude | Not a bug — the unconstrained optima are all at zero. Re-examine whether your sentiment estimates are actually that small |
| Hybrid runner exits without writing artifacts | Empty `mu_scenarios` dict | Supply at least one scenario |
| Artifacts written but `submission_note.md` looks wrong | You ran the wrong family's runner for the problem | Re-classify from Step 1 |

## What this playbook does NOT replace

- Reading the round PDF carefully.
- Writing out the payoff formula by hand.
- The sanity check before submission.
- Human judgment when a round is genuinely novel and doesn't fit any
  family above.

The runners are fast. Use the time they save to do the thinking that
actually decides the round.

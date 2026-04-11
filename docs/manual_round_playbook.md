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

## Step 1b — Out-of-distribution check (MANDATORY, non-negotiable)

Before you write the input JSON, scan the round page for any mechanic
the runner you picked does **not** model. If you find even one, **stop
and flag the mismatch rather than force-fitting it**.

The runners were built for the exact shape each family took in
Prosperity 1–3. Prosperity 4 may tweak the mechanics in ways that
break the assumptions silently. A silent misfit in a solver that
"runs fine" is the most dangerous failure mode in a manual round: the
artifacts look plausible, the submission note looks clean, and the
answer is wrong.

### Runner-specific OOD signals

**graph (`run_manual_graph`):**
- Non-deterministic rates, or rates that shift mid-round.
- Edge-dependent fees (a fixed cost per trade that is not just a
  multiplicative factor).
- Max-hops that depends on *which* edges are used, not just how many.
- Asymmetric start/end nodes where a subset of currencies is banned at
  specific positions in the path.
- Any leg that requires holding for multiple iterations.

**bid (`run_manual_bid`):**
- More than two tiers of bid (e.g. a three-tier sealed bid).
- A reserve distribution that is not uniform, linear-ramp, or
  bimodal-uniform (e.g. triangular, gaussian, explicitly sampled).
- Correlated reserves across counterparties.
- Fractional bids, or bids outside the integer grid.
- A resale value that depends on the bid (e.g. "sells for 10x your bid").
- Any form of partial fill or quantity splitting.

**crowding (`run_manual_crowd`):**
- Fees that tier on something other than pick count (e.g. per-cell
  fees, tiered by total multiplier sum).
- Payoff dilution that uses a formula other than
  `C * M / (I + k * p)` (e.g. winner-take-all, log-scaled, or a
  capped pot).
- Inhabitants or multipliers that change during the round.
- A max_picks value greater than 3 (the enumeration is still fine, but
  verify fees are well-defined).
- Shared pots across multiple cells.
- Any form of information asymmetry between teams.

**hybrid_bid (`run_manual_hybrid`):**
- Penalty forms that are not `((V - mu) / (V - p_h)) ** alpha`
  (e.g. piecewise, absolute-value-based, floor-capped).
- Coupling through something other than the average of other teams'
  high bids (e.g. median, max, quantile).
- Multi-round dynamics where `mu` evolves with your own prior answers.
- A low-bid leg that is also coupled to other teams' bids.

**news_portfolio (`run_manual_news`):**
- An L-infinity budget instead of L1 (cap per position, not total).
- A fee that is not `f * x^2` (e.g. linear, cubic, or asymmetric
  between long and short).
- Correlated returns across products (e.g. a factor structure).
- Products that interact (e.g. buying X reduces the return on Y).
- Position bounds that are asymmetric between long and short.
- Any non-integer position size.

### What "flagging the mismatch" looks like

If you find a signal from the lists above:

1. **Do not run the runner.** The artifacts it produces will be wrong
   and misleadingly official-looking.
2. Write a short note to yourself naming the exact mechanic that
   doesn't fit, under `outputs/manual_rounds/round_N_OOD.md`.
3. Solve the round with pen and paper, or write a one-off notebook
   that models the specific mechanic.
4. If you end up using a runner anyway because the OOD signal turned
   out to be cosmetic, **document why** in the OOD note so future-you
   has an audit trail.

The 60 seconds you spend on this check is the cheapest insurance the
toolkit has.

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

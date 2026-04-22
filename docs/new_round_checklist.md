# New Round Checklist

> **Scope**: Round-day action list — what to do, in what order, when a
> new round drops. Covers both algo and manual. Not a deep-dive on any
> single step; links to the relevant phase notes for that.

Last verified against commit `d48ec48`.

Work top-to-bottom; each step assumes the previous one is done.

All commands assume the repo root and an activated venv
(`source .venv/bin/activate`).

---

## 1. Data intake

- Download the round's price and trade CSV files from the Prosperity
  platform.
- Place them under `data/raw/round_N/` (e.g.
  `data/raw/round_1/prices_round_1_day_0.csv`).
- Verify the replay engine can parse them:

```bash
PYTHONPATH=. python -c "
from src.backtest.replay_engine import ReplayEngine
replay = ReplayEngine.from_files([
    'data/raw/round_N/prices_round_N_day_0.csv',
])
print(f'{len(replay.steps)} steps, products: {set(
    p for s in replay.steps for p in s.rows_by_product
)}')
"
```

---

## 2. Product discovery

Read the round spec and note for each new product:

- [ ] Product name (must match the CSV exactly)
- [ ] Position limit
- [ ] Tick size (usually 1)
- [ ] Any new mechanics: conversions, baskets, options, linked products

---

## 3. Manual round

Every round ships a closed-form manual puzzle alongside the algo
challenge. Handle it in parallel with algo work.

1. Classify the puzzle family against the 5-family table in
   `src/manual_rounds/README.md`:

   | Family | Module | Runner |
   |--------|--------|--------|
   | Graph / path arbitrage | `graph_arbitrage` | `src/scripts/run_manual_graph.py` |
   | Sealed bid | `bid_optimizer` | `src/scripts/run_manual_bid.py` |
   | Game-theoretic crowding | `nash_crowd` | `src/scripts/run_manual_crowd.py` |
   | Average-bid hybrid | `hybrid_bid` | `src/scripts/run_manual_hybrid.py` |
   | News / portfolio QP | `news_portfolio` | `src/scripts/run_manual_news.py` |

2. Follow the workflow in
   [docs/manual_round_playbook.md](manual_round_playbook.md): classify,
   solve naive, add crowd model, sweep, build submission note.

---

## 4. EDA

Run a first backtest on the new data with the default config to see
what the products look like:

```bash
PYTHONPATH=. python -m src.scripts.run_backtest
PYTHONPATH=. python -m src.scripts.run_review --label round_N_eda
```

Inspect the review pack under `outputs/review_packs/`:

- Price vs fair value charts — does the fair value track well?
- PnL curve — any blow-ups or flat stretches?
- Position plots — hitting limits too often?
- Trade markers — are fills happening at the right prices?

---

## 5. Algo product onboarding

For each new product, follow the decision tree in
[docs/adding_a_product.md](adding_a_product.md):

- **Path A** (config-only) for products that fit the `market_making`
  strategy with an existing estimator.
- **Path B** (new estimator) if a custom fair value computation is
  needed.
- **Path C** (new strategy) if the product needs fundamentally different
  logic.

---

## 6. Fair value inference

For each product, compare estimators side-by-side:

```bash
PYTHONPATH=. python -m src.scripts.compare_fair_values
```

This uses `FairValueEngine.estimate_all()` to run every registered
estimator on the same replay tape. Pick the one that best explains
realized markouts and PnL.

See [docs/phase_3_fair_value_note.md](phase_3_fair_value_note.md) for
the methodology.

---

## 7. Parameter tuning

Adapt the Phase 6 sweep scripts as templates for new products:

```bash
# Copy and edit one of these for the new product:
PYTHONPATH=. python -m src.scripts.run_phase6_emeralds_sweep --label round_N_product
PYTHONPATH=. python -m src.scripts.run_phase6_tomatoes_sweep --label round_N_product
```

Look for **plateau regions** (stable parameter bands), not the single
highest backtest peak. Intersect plateau bands across multiple days if
multi-day data is available.

See [docs/phase_6_robustness_note.md](phase_6_robustness_note.md) for
the sweep methodology and the promotion gate.

---

## 8. Review protocol

Generate a full review pack and inspect it:

```bash
PYTHONPATH=. python -m src.scripts.run_review --label round_N_final
```

Follow the 4-step review from
[docs/phase_4_review_discipline_note.md](phase_4_review_discipline_note.md):

1. **Metrics** — PnL, markouts at +1/+5/+20, entry edge, maker/taker
   mix, time near limits.
2. **Visual** — Price vs FV, PnL curve, position, trade markers.
3. **Step-through** — Sample best trades, worst trades, missed
   opportunities. Use `src/scripts/run_drilldown.py` for
   timestamp-level inspection.
4. **Decision note** — Keep, modify, or discard each config choice.

---

## 9. Submission

Follow the full checklist in
[docs/phase_9_submission_checklist.md](phase_9_submission_checklist.md).

Quick version:

```bash
# Export platform bundle
PYTHONPATH=. python -m src.scripts.export_submission

# Validate
PYTHONPATH=. python -m src.scripts.validate_submission

# Dry-run smoke test
PYTHONPATH=. python -m pytest tests/test_submission_export.py -q

# Full submission gate
./scripts/check.sh --submission
```

Verify the banner of `outputs/submissions/trader_submission.py` shows
`Datamodel mode: platform` and the expected module count.

---

## 10. Post-submission

- [ ] Commit with the active `ProductConfig` values in the message.
- [ ] Note which estimator and parameter choices were made and why.
- [ ] Archive the review pack output for retrospective.
- [ ] If the round introduced new mechanics not yet supported (options,
      conversions, baskets), file a TODO for the next phase.

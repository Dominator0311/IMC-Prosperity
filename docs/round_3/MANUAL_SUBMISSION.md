# R3 Manual Challenge — Celestial Gardeners' Guild Bio-Pod Bids

## Submission

| Scenario | b1 | b2 |
|---|---|---|
| **Integer bids accepted** | **751** | **841** |
| Multiples-of-5 forced | 755 | 840 |

**Default: submit 751 / 841 unless the UI forces multiples-of-5.**

## Rationale

- Pure EV optimum: b1=751, b2=836 → EV ≈ 84.33 per counterparty.
- Nudge b2 to 841 to sit above expected crowd cluster at ~835–840.
  Cost: 0.11 EV vs optimum. Benefit: avoids landing just below a dense
  integer cluster (see Lesson M3 from R2 post-mortem).
- If multiples-of-5 are forced: b1=755 (next multiple ≥ 751), b2=840
  (next multiple ≤ 841). EV ≈ 81.67.

## Expected P&L

~+4,200 shells (50 counterparties × 84 EV estimate).

## Submission checklist

- [ ] Verify bid-increment rule in Manual Challenge Overview UI.
- [ ] Submit b1 / b2 before R3 round close.
- [ ] Record actual submitted values below.

## Submitted values (fill in at submission time)

- b1 submitted: _____
- b2 submitted: _____
- Bid-increment rule observed: _____
- Submission timestamp: _____

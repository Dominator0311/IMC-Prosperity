# ASH_COATED_OSMIUM · C2 review notes

- **Config:** ewma_mid primary; fallbacks (mid, microprice); anchor_price=10 000 (retained as last-resort fallback); maker_edge=1.0; taker_edge=0.25; inventory_skew=4.0; flatten_threshold=0.7; history_length=48; position_limit=50 (placeholder); default ewma_alpha.
- **Pack:** `outputs/round_1/review_packs/20260414T140358Z_round1_ash_c2_ewma_mid_t025/`

## Headlines

| Metric | Value |
|--------|-------|
| Total PnL (3 days) | +6 447 |
| Per-day PnL | +2 189 / +2 124 / +2 134 |
| Cross-day σ | ≈ 28 |
| Final positions (d-2 / d-1 / 0) | +8 / +4 / +4 |
| Trade count | 472 |
| Maker share | 0.3 % |
| Near-limit steps | **0** |
| Avg entry edge | +0.80 |
| Markouts (h=1/5/20) | +2.08 / +1.94 / +1.93 |
| Lag-1 autocorr (step PnL) | −0.448 |
| Tail-20% PnL share | 21.1 % |

## What the review pack shows

- **Extraordinary cross-day consistency.** +2 189, +2 124, +2 134 —
  σ/mean ≈ 1.3 %. Every day produces the same PnL within ±65. This
  is the most stable candidate in the entire shortlist.
- **Markouts are the best of any ASH candidate** at every horizon
  (+2.08 / +1.94 / +1.93). C1's taker-heavier behaviour produces
  more fills but lower markout-per-trade.
- **Entry edge is only +0.80.** Much lower than C1's +2.08. ewma_mid
  tracks the mid very closely, so the fair-mid gap is narrow. The
  strategy earns its PnL by capturing the residual mean-reversion
  after each fill, not by finding large up-front edges.
- **Zero near-limit steps across 30 000 snapshots.** The combination
  of a softer signal and a less aggressive taker_edge keeps the book
  off the wall at all times.
- **Trade count 472 vs C1's 766 (-38 %).** Less churn; each trade is
  worth more.
- **Tail-20% share 21.1 % is the steadiest accrual profile.** PnL
  arrives evenly throughout the replay.

## What remains uncertain

1. **Is markout strength preserved under a different fill model?**
   The +2.0 markouts argue that ewma_mid's quote placement is
   selecting genuinely good fills; this is a more fill-model-
   agnostic edge than C1's taker-heavy edge. But we can't verify
   that without official data.
2. **Low entry edge could mean narrow safety margin.** If the
   official exchange is less forgiving on exact price levels, +0.80
   of edge is only a tick; any systematic skid turns this into
   losses.
3. **Maker share is still just 0.3 %.** Despite the "ewma + tight
   taker" framing, the engine still lifts the spread almost every
   fill because the ewma residual alone is enough. If we want a
   maker-heavier ASH variant we need to widen taker_edge further —
   but that was Phase-4 territory.

## Verdict

**Promote as Round-1 ASH default.** Rationale:

- Cross-day PnL variance is negligible (±28 vs C1's ±455).
- Markouts at every horizon are better than C1's.
- Zero near-limit steps means no inventory-driven PnL path.
- 17 % less total PnL but every other risk dimension is cleaner.

C1 is an interesting higher-upside alternative if the official fill
model confirms the extra fills are real. For baseline promotion, C2
is the safer pick and matches the plan's "don't ship a candidate
that depends heavily on local fill assumptions" rule.

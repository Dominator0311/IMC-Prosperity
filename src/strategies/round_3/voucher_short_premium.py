"""Voucher short-premium strategy — HOLD-TO-END.

Short deep-OTM voucher premium once at round open, HOLD to final tick.
End-of-round mark against hidden FV is where we harvest the edge.

Evidence from submission 381248 (v4 aggressive, covered at t=90K):
  We successfully shorted 201 qty on K=5400, 201 on K=5500, 115 on K=5300.
  Then covered all via taker buys → paid bid-ask spread both ways →
  lost $228+$319+$201 = $748 purely to spread costs. Marks never kicked in.

The whole point of short-premium is to NOT flatten — the hidden FV does
that for us. Whatever mark model the platform uses (intrinsic / BSM fair /
end-mid), it's ≤ open-mid for OTM options, so shorting and holding has
bounded downside (= bid-ask spread on entry ≈ $200 per strike) and
meaningful upside (potentially $2K-10K per strike).

Strategy (revised v5):
  1. Build short position ONCE at round open, primarily via passive ask
     (zero spread cost) plus ONE bid-hit per strike per tick for the first
     ~5 ticks (small, bounded spread cost to seed the position).
  2. Once position reaches target, STOP issuing short orders.
  3. NEVER cover. Let the end-of-round liquidation mark us.
  4. No delta hedging with VELVET. The cover-and-flatten cost vastly
     exceeded any hedge benefit in submission 381248.

No K=5200 short — too close to ATM, gamma risk too high.
No K=6000/K=6500 — bid=0 means maker-ask never fills, bid-hit at 0 yields
zero cash.

Returns orders; orchestrator integrates with R3DeltaBudget for safety cap.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.datamodel import Order


@dataclass(frozen=True)
class ShortTarget:
    strike: int
    target_position: int     # NEGATIVE = desired short position
    seed_bid_hit_qty: int    # one-time aggressive bid-hit at round start
    seed_ticks: int          # number of ticks we allow aggressive seeding
    entry_window_end: int    # stop adding shorts after this ts (passive only)


# Targets sized conservatively to BOUND the entry spread-cost while still
# getting meaningful positions. Example: K=5400 spread=2, seed 80 qty via
# bid-hit → max spread cost = 2×80 = $160. Intrinsic payoff if OTM at end:
# 16×80 = $1,280. Net EV = +$1,120 per strike.
_SHORT_TARGETS: tuple[ShortTarget, ...] = (
    # Deep OTM — safe to short big.
    # K=5500 spread 1, open mid 6.5. Seed 200 = $200 entry cost, $1300 intrinsic upside.
    ShortTarget(strike=5500, target_position=-300, seed_bid_hit_qty=200, seed_ticks=5, entry_window_end=50_000),
    # OTM. K=5400 spread 2, open mid 17. Seed 200 = $400 entry, $3400 intrinsic upside.
    ShortTarget(strike=5400, target_position=-300, seed_bid_hit_qty=200, seed_ticks=5, entry_window_end=40_000),
    # Slightly OTM. K=5300 spread 2, open mid 53. Seed 100 = $200 entry, $5300 intrinsic upside.
    # Smaller seed than 5400/5500 because real directional risk if S rips up.
    ShortTarget(strike=5300, target_position=-200, seed_bid_hit_qty=100, seed_ticks=4, entry_window_end=25_000),
)


def voucher_short_premium_orders(
    snapshots: dict[int, "NormalizedSnapshot"],
    positions: dict[int, int],
    timestamp: int,
) -> list[Order]:
    """Generate short-premium orders for each voucher target.

    Build-only strategy: seeds a bounded short at round open (accepting one
    round of bid-hit spread cost), then TOP UP with passive ask orders
    through the entry window. NEVER covers — the end-of-round liquidation
    mark is how we harvest. Covering destroys the edge by paying the
    bid-ask spread on the way out (see submission 381248 postmortem).

    ``snapshots``: strike → NormalizedSnapshot
    ``positions``: strike → current position (signed)
    """
    from src.core.types import NormalizedSnapshot  # local, avoid cycle

    orders: list[Order] = []
    # Ticks elapsed since round start, assuming step=100.
    tick_num = timestamp // 100

    for target in _SHORT_TARGETS:
        snap: NormalizedSnapshot | None = snapshots.get(target.strike)
        if snap is None or snap.best_bid is None or snap.best_ask is None:
            continue
        symbol = f"VEV_{target.strike}"
        current = positions.get(target.strike, 0)

        # Skip if already at/below target — hold position.
        if current <= target.target_position:
            continue

        # Skip if past the entry window entirely.
        if timestamp >= target.entry_window_end:
            continue

        remaining = current - target.target_position  # positive = how much to sell more

        # --- SEED: one aggressive bid-hit in the first few ticks ---
        if tick_num < target.seed_ticks and current > -target.seed_bid_hit_qty:
            seed_qty = min(target.seed_bid_hit_qty + current, remaining)
            if seed_qty > 0:
                orders.append(Order(symbol, snap.best_bid.price, -seed_qty))

        # --- PASSIVE ASK: always active during entry window ---
        # Post a sell at the current best ask. Zero spread cost. If market
        # lifts, we fill. If not, no loss.
        passive_qty = min(50, remaining)
        if passive_qty > 0:
            orders.append(Order(symbol, snap.best_ask.price, -passive_qty))

    return orders

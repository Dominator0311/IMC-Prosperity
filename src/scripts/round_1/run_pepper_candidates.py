"""Demonstration runner for the 5 new PEPPER candidates.

This is a research runner, not an export script. It:

1. Iterates over every candidate in ``CANDIDATE_FACTORIES``.
2. Instantiates it against a minimal synthetic ``NormalizedSnapshot``
   sequence (drift + noise) to verify each strategy produces
   reasonable intent shapes end-to-end.
3. Prints a one-line summary of each candidate's first 5 decisions
   so differences in behavior are visible.

For full evaluation, this should be replaced with a
``ReplayEngine``-driven run against real tapes plus the calibrated
fill model. The V3 export path
(``src/scripts/round_1/export_round1_v3_nearhold.py``) remains the
reference for turning any winner into an official submission bundle.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_pepper_candidates
"""

from __future__ import annotations

from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import BookLevel, NormalizedSnapshot, ProductMemory, TradePrint
from src.strategies.base import StrategyContext
from src.strategies.round_1_pepper_candidates import (
    CANDIDATE_FACTORIES,
    PEPPER,
    pepper_product_config,
)


def _synthetic_snapshot(
    tick: int,
    *,
    position: int,
    mid: float,
    spread: int = 14,
    depth: int = 20,
) -> NormalizedSnapshot:
    bid = int(mid - spread / 2)
    ask = int(mid + spread / 2)
    # One sample market trade every 3 ticks to exercise FlowOverlay.
    trades: tuple[TradePrint, ...] = ()
    if tick % 3 == 0:
        trades = (
            TradePrint(
                price=bid + 1,
                quantity=3,
                timestamp=tick * 100,
                source="market",
            ),
        )
    return NormalizedSnapshot(
        product=PEPPER,
        timestamp=tick * 100,
        bids=(BookLevel(bid, depth),),
        asks=(BookLevel(ask, depth),),
        position=position,
        trades=trades,
    )


def _one_line(name: str, tick: int, intent) -> str:
    q = intent.quote
    bid_desc = f"B{q.bid_size}@{q.bid_price}" if q and q.bid_size > 0 else "B-"
    ask_desc = f"A{q.ask_size}@{q.ask_price}" if q and q.ask_size > 0 else "A-"
    tk_buy = f"tkB<={intent.buy_below}" if intent.buy_below is not None else "tkB-"
    tk_sell = f"tkS>={intent.sell_above}" if intent.sell_above is not None else "tkS-"
    return (
        f"  t={tick:2d} fv={intent.fair_value.price:.1f} {bid_desc:14s} "
        f"{ask_desc:14s} {tk_buy:14s} {tk_sell:14s}"
    )


def run_demo() -> None:
    fv_engine = FairValueEngine()
    signal_engine = SignalEngine()
    config = pepper_product_config()

    for name, factory in CANDIDATE_FACTORIES.items():
        print(f"\n=== {name} ===")
        strategy = factory(fv_engine, signal_engine)
        memory = ProductMemory()
        position = 0

        for tick in range(6):
            # Mid drifts up by 0.5/tick (10× real rate for visible
            # movement in a 6-tick demo — real tape is +0.1).
            mid = 12_000.0 + 0.5 * tick
            snapshot = _synthetic_snapshot(tick, position=position, mid=mid)
            ctx = StrategyContext(
                product=PEPPER,
                snapshot=snapshot,
                memory=memory,
                config=config,
            )
            intent = strategy.generate_intent(ctx)
            print(_one_line(name, tick, intent))

            # Append mid to memory so linear_drift warms up.
            memory.recent_mids.append(mid)

            # Crude fill simulation: assume passive bid fills when
            # snapshot mid is below the quote, passive ask when above.
            # Also cross taker against the best ask / bid if set.
            if intent.quote and intent.quote.bid_price is not None:
                if intent.quote.bid_price >= snapshot.best_ask.price - 1:
                    # aggressive passive — fill up to quote size.
                    position = min(80, position + intent.quote.bid_size)
            if intent.buy_below is not None and snapshot.best_ask is not None:
                if snapshot.best_ask.price <= intent.buy_below:
                    position = min(
                        80,
                        position + min(snapshot.best_ask.volume, config.max_aggressive_size),
                    )
            if intent.sell_above is not None and snapshot.best_bid is not None:
                if snapshot.best_bid.price >= intent.sell_above:
                    position = max(
                        -80,
                        position - min(snapshot.best_bid.volume, config.max_aggressive_size),
                    )


if __name__ == "__main__":  # pragma: no cover
    run_demo()

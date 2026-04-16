"""Tests for general-mode FV recovery (any-position trader, not just hold-1).

Validates that ``build_fact_table(mode='general')`` correctly recovers
server FV from a trader whose position changes over time, by
reconstructing the cash and position trajectories from the trade
history and inverting:

    server_fv(t) = (pnl(t) - cash(t)) / position(t)
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence

import pytest

from src.analysis.calibration.extract_fv import build_fact_table
from src.analysis.calibration.types import TradeRow

BOT_SEAT = "TEAM_X"
SEED = 20260420


def _build_records_and_trades_changing_position() -> tuple[list, list[TradeRow]]:
    """Synthetic trader that buys 2 at t=0, sells 1 at t=500,
    sells the remaining 1 at t=900 (position 0 from t=900 onward).

    FV is a Gaussian RW starting at 5000, sigma=0.5.
    """
    rng = random.Random(SEED)
    fv = 5000.0
    activity = []
    trades: list[TradeRow] = []

    def gauss() -> float:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    # Decide entry/exit prices ahead of time so the test is stable.
    entry_buy_price_t0 = 5005   # we buy 2 here
    sell_price_t500 = None       # populated below
    sell_price_t900 = None

    position = 0
    cash = 0.0

    for tick in range(1000):
        ts = tick * 100
        if tick > 0:
            fv += 0.5 * gauss()

        # Generate a simple inner book around fv.
        bid_price = round(fv) - 2
        ask_price = round(fv) + 2

        # Apply own trades at this tick (they would have already been logged
        # by the IMC platform in tradeHistory).
        if ts == 0:
            # Buy 2 at entry_buy_price_t0
            position += 2
            cash -= 2 * entry_buy_price_t0
            trades.append(TradeRow(
                timestamp=ts, product="P", price=entry_buy_price_t0,
                quantity=2, buyer=BOT_SEAT, seller="MARKET",
            ))
        if ts == 50000:
            # Sell 1 at the current ask
            sell_price_t500 = ask_price
            position -= 1
            cash += 1 * sell_price_t500
            trades.append(TradeRow(
                timestamp=ts, product="P", price=sell_price_t500,
                quantity=1, buyer="MARKET", seller=BOT_SEAT,
            ))
        if ts == 90000:
            sell_price_t900 = bid_price
            position -= 1
            cash += 1 * sell_price_t900
            trades.append(TradeRow(
                timestamp=ts, product="P", price=sell_price_t900,
                quantity=1, buyer="MARKET", seller=BOT_SEAT,
            ))

        # IMC's PnL marks position to fv at each tick.
        pnl = cash + position * fv

        activity.append({
            "day": 0, "timestamp": ts, "product": "P",
            "bid_price_1": bid_price, "bid_volume_1": 5,
            "bid_price_2": None, "bid_volume_2": None,
            "bid_price_3": None, "bid_volume_3": None,
            "ask_price_1": ask_price, "ask_volume_1": 5,
            "ask_price_2": None, "ask_volume_2": None,
            "ask_price_3": None, "ask_volume_3": None,
            "mid_price": 0.5 * (bid_price + ask_price),
            "profit_and_loss": pnl,
            # Ground-truth FV embedded for the test only.
            "_truth_fv": fv,
        })

    return activity, trades


def test_general_mode_recovers_fv_with_changing_position():
    activity, trades = _build_records_and_trades_changing_position()
    facts_by_product = build_fact_table(
        activity, own_trade_records=trades,
        bot_seat=BOT_SEAT, mode="general",
    )
    assert "P" in facts_by_product
    facts = facts_by_product["P"]
    # Position trajectory: 2 for ticks 0..499, 1 for ticks 500..899,
    # 0 for ticks 900..999. Recoverable = 500 + 400 = 900.
    assert len(facts) == 900, (
        f"expected 900 recoverable ticks (1000 - 100 with position=0), got {len(facts)}"
    )
    truth_by_ts = {row["timestamp"]: row["_truth_fv"] for row in activity}
    for fact in facts:
        truth = truth_by_ts[fact.timestamp]
        assert abs(fact.server_fv - truth) < 1e-6, (
            f"FV mismatch at t={fact.timestamp}: "
            f"recovered {fact.server_fv:.6f}, truth {truth:.6f}"
        )


def test_general_mode_handles_zero_position_gap_in_middle():
    """Trader buys 1, sells 1, buys 1 — position is 0 in the middle."""
    rng = random.Random(SEED)

    def gauss() -> float:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    fv = 5000.0
    activity = []
    trades = []
    position = 0
    cash = 0.0
    for tick in range(300):
        ts = tick * 100
        if tick > 0:
            fv += 0.5 * gauss()
        if ts == 0:
            position += 1
            cash -= 5005
            trades.append(TradeRow(
                timestamp=ts, product="P", price=5005, quantity=1,
                buyer=BOT_SEAT, seller="MARKET",
            ))
        if ts == 10000:
            position -= 1
            cash += 5006
            trades.append(TradeRow(
                timestamp=ts, product="P", price=5006, quantity=1,
                buyer="MARKET", seller=BOT_SEAT,
            ))
        if ts == 20000:
            position += 1
            cash -= 5008
            trades.append(TradeRow(
                timestamp=ts, product="P", price=5008, quantity=1,
                buyer=BOT_SEAT, seller="MARKET",
            ))
        pnl = cash + position * fv
        activity.append({
            "day": 0, "timestamp": ts, "product": "P",
            "bid_price_1": int(fv - 2), "bid_volume_1": 5,
            "bid_price_2": None, "bid_volume_2": None,
            "bid_price_3": None, "bid_volume_3": None,
            "ask_price_1": int(fv + 2), "ask_volume_1": 5,
            "ask_price_2": None, "ask_volume_2": None,
            "ask_price_3": None, "ask_volume_3": None,
            "mid_price": fv,
            "profit_and_loss": pnl,
            "_truth_fv": fv,
        })

    facts_by_product = build_fact_table(
        activity, own_trade_records=trades,
        bot_seat=BOT_SEAT, mode="general",
    )
    facts = facts_by_product["P"]
    # Position 1 for ticks 0..99 (100 ticks), 0 for 100..199 (100 ticks),
    # 1 for 200..299 (100 ticks). Recoverable = 200.
    assert len(facts) == 200, (
        f"expected 200 ticks (zero-position middle gap dropped), got {len(facts)}"
    )
    # No fact at the gap timestamps.
    fact_ts = {f.timestamp for f in facts}
    assert 15000 not in fact_ts, "tick t=15000 (position=0) should be dropped"


def test_auto_mode_picks_hold_one_for_unit_buy_at_t0():
    """When trades match the hold-1 pattern exactly, auto mode uses fast path."""
    activity = [
        {"day": 0, "timestamp": 0, "product": "P",
         "bid_price_1": 4998, "bid_volume_1": 5,
         "bid_price_2": None, "bid_volume_2": None,
         "bid_price_3": None, "bid_volume_3": None,
         "ask_price_1": 5002, "ask_volume_1": 5,
         "ask_price_2": None, "ask_volume_2": None,
         "ask_price_3": None, "ask_volume_3": None,
         "mid_price": 5000, "profit_and_loss": -2.0},
    ]
    trades = [TradeRow(
        timestamp=0, product="P", price=5002, quantity=1,
        buyer=BOT_SEAT, seller="MARKET",
    )]
    facts_by_product = build_fact_table(
        activity, own_trade_records=trades, bot_seat=BOT_SEAT, mode="auto",
    )
    facts = facts_by_product["P"]
    assert len(facts) == 1
    # Recovered fv = pnl + buy_price = -2 + 5002 = 5000.
    assert abs(facts[0].server_fv - 5000.0) < 1e-9


def test_auto_mode_falls_back_to_general_for_multi_trade():
    """Multiple trades → must use general path."""
    activity = [
        {"day": 0, "timestamp": 0, "product": "P",
         "bid_price_1": 4998, "bid_volume_1": 5,
         "bid_price_2": None, "bid_volume_2": None,
         "bid_price_3": None, "bid_volume_3": None,
         "ask_price_1": 5002, "ask_volume_1": 5,
         "ask_price_2": None, "ask_volume_2": None,
         "ask_price_3": None, "ask_volume_3": None,
         "mid_price": 5000, "profit_and_loss": -2.0},
        {"day": 0, "timestamp": 100, "product": "P",
         "bid_price_1": 4999, "bid_volume_1": 5,
         "bid_price_2": None, "bid_volume_2": None,
         "bid_price_3": None, "bid_volume_3": None,
         "ask_price_1": 5003, "ask_volume_1": 5,
         "ask_price_2": None, "ask_volume_2": None,
         "ask_price_3": None, "ask_volume_3": None,
         "mid_price": 5001, "profit_and_loss": -1.0},
    ]
    trades = [
        TradeRow(timestamp=0, product="P", price=5002, quantity=1,
                 buyer=BOT_SEAT, seller="MARKET"),
        TradeRow(timestamp=100, product="P", price=5004, quantity=1,
                 buyer=BOT_SEAT, seller="MARKET"),
    ]
    facts_by_product = build_fact_table(
        activity, own_trade_records=trades, bot_seat=BOT_SEAT, mode="auto",
    )
    facts = facts_by_product["P"]
    # General path: at t=0, position=1, cash=-5002, pnl=-2 → fv=(-2-(-5002))/1=5000.
    # At t=100, position=2, cash=-10006, pnl=-1 → fv=(-1-(-10006))/2=5002.5.
    assert len(facts) == 2
    assert abs(facts[0].server_fv - 5000.0) < 1e-9
    assert abs(facts[1].server_fv - 5002.5) < 1e-9

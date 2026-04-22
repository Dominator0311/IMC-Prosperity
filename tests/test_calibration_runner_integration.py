"""End-to-end integration test for the calibration runner.

Generates a synthetic IMC-format activity log JSON, invokes the
``run_calibration`` CLI, and verifies that the output artifacts are
produced and contain the expected fit values.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from src.scripts.calibration.run_calibration import main as run_calibration_main

N_TICKS = 2000  # smaller than unit test for runner speed
SEED = 20260417


def _build_synthetic_activity_log(out_path: Path) -> None:
    """Write a fake IMC activity log JSON with EMERALDS + TOMATOES.

    EMERALDS: stationary at 10000, simple symmetric bots.
    TOMATOES: random walk starting at 5000, asymmetric inner bots.

    Both products have a hold-1 trader buying at t=0 best_ask.
    """
    rng = random.Random(SEED)
    activity_logs = []
    trade_history = []

    def gauss() -> float:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    em_fv = 10000.0
    tom_fv = 5000.0
    em_buy_price = None
    tom_buy_price = None

    for tick in range(N_TICKS):
        ts = tick * 100
        if tick > 0:
            tom_fv += 0.5 * gauss()  # tomato random walk
            # emerald stays put

        # Build EMERALDS book
        em_inner_bid = round(em_fv) - 8
        em_inner_ask = round(em_fv) + 8
        em_outer_bid = round(em_fv) - 10
        em_outer_ask = round(em_fv) + 10

        if em_buy_price is None:
            em_buy_price = em_inner_ask
        em_pnl = em_fv - em_buy_price

        activity_logs.append({
            "day": 0,
            "timestamp": ts,
            "product": "EMERALDS",
            "bid_price_1": em_inner_bid,
            "bid_volume_1": rng.randint(10, 15),
            "bid_price_2": em_outer_bid,
            "bid_volume_2": rng.randint(20, 30),
            "bid_price_3": None,
            "bid_volume_3": None,
            "ask_price_1": em_inner_ask,
            "ask_volume_1": rng.randint(10, 15),
            "ask_price_2": em_outer_ask,
            "ask_volume_2": rng.randint(20, 30),
            "ask_price_3": None,
            "ask_volume_3": None,
            "mid_price": 0.5 * (em_inner_bid + em_inner_ask),
            "profit_and_loss": em_pnl,
        })

        # Build TOMATOES book with asymmetric inner bots.
        tom_inner_bid = math.floor(tom_fv + 0.75) - 7
        tom_inner_ask = math.ceil(tom_fv + 0.25) + 6
        tom_outer_bid = round(tom_fv) - 8
        tom_outer_ask = round(tom_fv) + 8

        if tom_buy_price is None:
            tom_buy_price = tom_inner_ask
        tom_pnl = tom_fv - tom_buy_price

        activity_logs.append({
            "day": 0,
            "timestamp": ts,
            "product": "TOMATOES",
            "bid_price_1": tom_inner_bid,
            "bid_volume_1": rng.randint(5, 10),
            "bid_price_2": tom_outer_bid,
            "bid_volume_2": rng.randint(15, 25),
            "bid_price_3": None,
            "bid_volume_3": None,
            "ask_price_1": tom_inner_ask,
            "ask_volume_1": rng.randint(5, 10),
            "ask_price_2": tom_outer_ask,
            "ask_volume_2": rng.randint(15, 25),
            "ask_price_3": None,
            "ask_volume_3": None,
            "mid_price": 0.5 * (tom_inner_bid + tom_inner_ask),
            "profit_and_loss": tom_pnl,
        })

        # Trade arrivals.
        for product, ask, bid, p_active in (
            ("EMERALDS", em_inner_ask, em_inner_bid, 0.02),
            ("TOMATOES", tom_inner_ask, tom_inner_bid, 0.04),
        ):
            if rng.random() < p_active:
                is_buy = rng.random() < 0.47
                qty = rng.randint(2, 6)
                trade_history.append({
                    "timestamp": ts,
                    "symbol": product,
                    "price": ask if is_buy else bid,
                    "quantity": qty,
                    "buyer": "" if is_buy else "BOT_X",
                    "seller": "BOT_Y" if is_buy else "",
                })

    payload = {
        "activityLogs": activity_logs,
        "tradeHistory": trade_history,
        "sandboxLogs": [],
    }
    out_path.write_text(json.dumps(payload))


def test_runner_end_to_end(tmp_path: Path) -> None:
    log_path = tmp_path / "synthetic_log.json"
    out_dir = tmp_path / "calibration_out"
    _build_synthetic_activity_log(log_path)

    rc = run_calibration_main([
        "--log", str(log_path),
        "--out", str(out_dir),
        "--no-plots",  # plot rendering is tested elsewhere
    ])
    assert rc == 0

    fits_path = out_dir / "fits.json"
    report_path = out_dir / "calibration_report.md"
    assert fits_path.exists(), "fits.json was not written"
    assert report_path.exists(), "calibration_report.md was not written"

    fits = json.loads(fits_path.read_text())
    assert "EMERALDS" in fits, f"EMERALDS missing from fits: {list(fits.keys())}"
    assert "TOMATOES" in fits, f"TOMATOES missing from fits: {list(fits.keys())}"

    # EMERALDS: fair value should be near 10000 with sigma very small (constant).
    em_fv = fits["EMERALDS"]["fair_value"]
    assert em_fv["sigma"] < 0.01, (
        f"EMERALDS expected near-zero sigma, got {em_fv['sigma']:.4f}"
    )
    assert 9999.5 < em_fv["fv_min"] <= em_fv["fv_max"] < 10000.5

    # TOMATOES: fair value should be a random walk with sigma ~ 0.5.
    tom_fv = fits["TOMATOES"]["fair_value"]
    assert 0.4 < tom_fv["sigma"] < 0.6, (
        f"TOMATOES sigma off: {tom_fv['sigma']:.4f}"
    )

    # TOMATOES should have at least 2 bid + 2 ask depth bands detected.
    bands = fits["TOMATOES"]["depth_bands"]
    bid_bands = [b for b in bands if b["side"] == "bid"]
    ask_bands = [b for b in bands if b["side"] == "ask"]
    assert len(bid_bands) >= 2, (
        f"expected >= 2 TOMATOES bid bands, got {len(bid_bands)}"
    )
    assert len(ask_bands) >= 2, (
        f"expected >= 2 TOMATOES ask bands, got {len(ask_bands)}"
    )

    # Quote rules should achieve high match rate on both products.
    for product in ("EMERALDS", "TOMATOES"):
        rules = fits[product]["quote_rules"]
        for rule in rules:
            if rule["n_samples"] >= 100:
                assert rule["match_rate"] > 0.95, (
                    f"{product} {rule['bot_name']} match rate "
                    f"{rule['match_rate']:.2%} too low"
                )

    # Trade arrivals.
    em_arr = fits["EMERALDS"]["trade_arrivals"]
    assert 0.01 < em_arr["p_active"] < 0.04, em_arr
    tom_arr = fits["TOMATOES"]["trade_arrivals"]
    assert 0.025 < tom_arr["p_active"] < 0.06, tom_arr

    # Report contains structured headers per product.
    report = report_path.read_text()
    assert "## EMERALDS" in report
    assert "## TOMATOES" in report
    assert "Quote rules" in report

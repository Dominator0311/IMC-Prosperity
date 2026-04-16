"""End-to-end tests for the calibration pipeline using synthetic data.

We generate a fake tutorial-style day from KNOWN parameters, then run
the full pipeline and assert the recovered parameters match what we
put in. If this test fails, the pipeline is broken before we ever
look at real IMC data.

Synthetic generators mirror chrispyroberts's tutorial findings:
    - FV: Gaussian random walk, sigma=0.50, starts at 5000
    - Bot 1 (outer): bid = round(FV) - 8, ask = round(FV) + 8, vol U[15,25]
    - Bot 2 (inner): bid = floor(FV + 0.75) - 7,
                     ask = ceil(FV + 0.25) + 6, vol U[5,10]
    - Trades: Bernoulli per tick (p=0.04), 47% buy, qty U[2,5]
"""
from __future__ import annotations

import math
import random
from collections.abc import Sequence

import pytest

from src.analysis.calibration.bot_classifier import detect_depth_bands
from src.analysis.calibration.fair_value_fit import fit_fair_value_process
from src.analysis.calibration.rule_search import (
    fit_volume_distribution,
    predict_price,
    search_quote_rule,
)
from src.analysis.calibration.trade_fit import (
    fit_trade_arrivals,
    fit_trade_locations,
    fit_trade_sizes,
)
from src.analysis.calibration.types import BookLevel, FactRow, TradeRow

# Truth parameters used by the generators below.
TRUE_SIGMA = 0.50
TRUE_FV0 = 5000.0
TRUE_BOT1_OFFSET = 8
TRUE_BOT1_VOL_MIN, TRUE_BOT1_VOL_MAX = 15, 25
TRUE_BOT2_BID_OFFSET = -7  # in formula floor(fv + 0.75) - 7
TRUE_BOT2_ASK_OFFSET = 6   # in formula ceil(fv + 0.25) + 6
TRUE_BOT2_VOL_MIN, TRUE_BOT2_VOL_MAX = 5, 10
TRUE_P_ACTIVE = 0.04
TRUE_P_BUY = 0.47
TRUE_TRADE_SIZE_MIN, TRUE_TRADE_SIZE_MAX = 2, 5

N_TICKS = 5000  # smaller than tutorial 10k to keep tests quick
SEED = 20260416


def _generate_synthetic_facts() -> tuple[list[FactRow], list[TradeRow]]:
    rng = random.Random(SEED)
    fv = TRUE_FV0
    facts: list[FactRow] = []
    trades: list[TradeRow] = []

    # Gaussian step generator using Box-Muller for determinism.
    def gauss() -> float:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    for tick in range(N_TICKS):
        ts = tick * 100
        if tick > 0:
            fv += TRUE_SIGMA * gauss()

        bot1_bid_price = round(fv) - TRUE_BOT1_OFFSET
        bot1_ask_price = round(fv) + TRUE_BOT1_OFFSET
        bot2_bid_price = math.floor(fv + 0.75) + TRUE_BOT2_BID_OFFSET
        bot2_ask_price = math.ceil(fv + 0.25) + TRUE_BOT2_ASK_OFFSET
        bot1_vol = rng.randint(TRUE_BOT1_VOL_MIN, TRUE_BOT1_VOL_MAX)
        bot2_vol = rng.randint(TRUE_BOT2_VOL_MIN, TRUE_BOT2_VOL_MAX)

        # Inner bid (Bot 2) is closer to FV → best bid.
        bids = (
            BookLevel(price=bot2_bid_price, volume=bot2_vol),
            BookLevel(price=bot1_bid_price, volume=bot1_vol),
        )
        asks = (
            BookLevel(price=bot2_ask_price, volume=bot2_vol),
            BookLevel(price=bot1_ask_price, volume=bot1_vol),
        )
        mid = 0.5 * (bids[0].price + asks[0].price)

        # Hold-1 trader bought at best_ask of t=0.
        if tick == 0:
            buy_price = bot2_ask_price
            facts.append(FactRow(
                timestamp=ts, product="SYNTH", server_fv=fv,
                bids=bids, asks=asks, mid_price=mid, pnl=fv - buy_price,
            ))
            continue

        pnl = fv - buy_price  # unit position marked to FV
        facts.append(FactRow(
            timestamp=ts, product="SYNTH", server_fv=fv,
            bids=bids, asks=asks, mid_price=mid, pnl=pnl,
        ))

        # Trade arrivals: Bernoulli per tick.
        if rng.random() < TRUE_P_ACTIVE:
            is_buy = rng.random() < TRUE_P_BUY
            qty = rng.randint(TRUE_TRADE_SIZE_MIN, TRUE_TRADE_SIZE_MAX)
            # Price the trade against the inner book. Buy = hits ask.
            price = bot2_ask_price if is_buy else bot2_bid_price
            buyer = "" if is_buy else "BOT_X"
            seller = "BOT_Y" if is_buy else ""
            trades.append(TradeRow(
                timestamp=ts, product="SYNTH",
                price=price, quantity=qty,
                buyer=buyer, seller=seller,
            ))

    return facts, trades


@pytest.fixture(scope="module")
def synthetic_data() -> tuple[Sequence[FactRow], Sequence[TradeRow]]:
    return _generate_synthetic_facts()


def test_fv_process_recovers_sigma(synthetic_data):
    facts, _ = synthetic_data
    fit = fit_fair_value_process(facts)
    # 1-sigma SE for sigma estimator at N=5000 returns: sigma / sqrt(2N) ~ 0.005
    assert abs(fit.sigma - TRUE_SIGMA) < 0.025, (
        f"sigma mismatch: fitted {fit.sigma:.4f} vs true {TRUE_SIGMA:.4f}"
    )
    # Mean return should be near zero (no drift in generator).
    assert abs(fit.mean_return) < 3 * fit.sigma / math.sqrt(fit.n_returns), (
        f"unexpected drift: {fit.mean_return:.4f}"
    )
    # AR(1) phi is approximately zero for a true random walk.
    assert abs(fit.ar1_phi) < 4 * fit.ar1_phi_se, (
        f"unexpected AR(1) signal: phi={fit.ar1_phi:+.4f} +/- {fit.ar1_phi_se:.4f}"
    )
    # Variance ratio at every horizon should be near 1.
    for k, vr in zip(fit.vr_horizons, fit.variance_ratio):
        assert 0.7 < vr < 1.3, f"VR({k})={vr:.3f} outside [0.7, 1.3]"


def test_ar1_phi_demeaned_no_drift_bias():
    """AR(1) phi should be ~0 even when FV has strong drift.

    Reproduces the PEPPER bug: a pure random walk with drift +0.1/tick
    was producing phi=+0.21 because the AR(1) estimator was not
    demeaning. After the fix, phi should be near 0 within standard error.
    """
    rng = random.Random(SEED + 1)

    def gauss() -> float:
        u1 = max(rng.random(), 1e-12)
        u2 = rng.random()
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    fv = 12000.0
    facts: list[FactRow] = []
    for tick in range(5000):
        ts = tick * 100
        if tick > 0:
            fv += 0.1 + 0.5 * gauss()  # drift +0.1, sigma 0.5, NO autocorr
        facts.append(FactRow(
            timestamp=ts, product="DRIFT", server_fv=fv,
            bids=(), asks=(), mid_price=fv, pnl=0.0,
        ))
    fit = fit_fair_value_process(facts)
    assert abs(fit.mean_return - 0.1) < 0.02, (
        f"drift recovery off: mean={fit.mean_return:.4f}"
    )
    # Phi must be statistically zero (within ~4 SE) once we demean.
    assert abs(fit.ar1_phi) < 4 * fit.ar1_phi_se, (
        f"AR(1) phi appears nonzero with drift present "
        f"(should be near 0 after demean fix): "
        f"phi={fit.ar1_phi:+.4f} +/- {fit.ar1_phi_se:.4f}"
    )


def test_bimodal_rank_splits_into_sub_bands():
    """When two bots share a rank with separated offsets, bands split.

    Constructs ASK level1 with two populations:
      - 70% of ticks: 'wall' bot at offset +8
      - 30% of ticks: 'inside' bot at offset +1

    Expected: detect_depth_bands emits two ASK bands at rank 1.
    """
    rng = random.Random(SEED + 2)
    facts: list[FactRow] = []
    for tick in range(2000):
        fv = 5000.0
        if rng.random() < 0.30:
            ask_price = int(fv) + 1  # inside bot
        else:
            ask_price = int(fv) + 8  # wall bot
        bid_price = int(fv) - 8
        facts.append(FactRow(
            timestamp=tick * 100, product="P", server_fv=fv,
            bids=(BookLevel(price=bid_price, volume=10),),
            asks=(BookLevel(price=ask_price, volume=10),),
            mid_price=fv, pnl=0.0,
        ))
    bands = detect_depth_bands(facts)
    ask_bands_at_rank1 = [
        b for b in bands
        if b.side == "ask" and b.name.startswith("level1_")
    ]
    assert len(ask_bands_at_rank1) == 2, (
        f"expected 2 sub-bands at ask rank 1, got "
        f"{[b.name for b in ask_bands_at_rank1]}"
    )
    centers = sorted(
        0.5 * (b.offset_min + b.offset_max) for b in ask_bands_at_rank1
    )
    assert 0 <= centers[0] <= 2, (
        f"low sub-band center {centers[0]:.2f} not near +1"
    )
    assert 7 <= centers[1] <= 9, (
        f"high sub-band center {centers[1]:.2f} not near +8"
    )


def test_depth_bands_are_detected(synthetic_data):
    facts, _ = synthetic_data
    bands = detect_depth_bands(facts)
    bid_bands = [b for b in bands if b.side == "bid"]
    ask_bands = [b for b in bands if b.side == "ask"]
    assert len(bid_bands) == 2, (
        f"expected 2 bid bands (Bot 1 outer, Bot 2 inner); got {len(bid_bands)}: "
        f"{[b.name for b in bid_bands]}"
    )
    assert len(ask_bands) == 2, (
        f"expected 2 ask bands; got {len(ask_bands)}: "
        f"{[b.name for b in ask_bands]}"
    )
    # Outer band centered near +/- 8.
    assert any(
        b.side == "bid" and -8.5 <= 0.5 * (b.offset_min + b.offset_max) <= -7.5
        for b in bands
    ), f"no Bot 1 bid band near -8: {bands}"
    assert any(
        b.side == "ask" and 7.5 <= 0.5 * (b.offset_min + b.offset_max) <= 8.5
        for b in bands
    ), f"no Bot 1 ask band near +8: {bands}"


def _truth_bot1_bid(fv: float) -> int:
    return round(fv) - TRUE_BOT1_OFFSET


def _truth_bot1_ask(fv: float) -> int:
    return round(fv) + TRUE_BOT1_OFFSET


def _truth_bot2_bid(fv: float) -> int:
    return math.floor(fv + 0.75) + TRUE_BOT2_BID_OFFSET


def _truth_bot2_ask(fv: float) -> int:
    return math.ceil(fv + 0.25) + TRUE_BOT2_ASK_OFFSET


def _assert_rule_equivalent_to_truth(
    rule, truth_fn, facts: Sequence[FactRow], *, label: str
) -> None:
    """Predicted price must match truth on the actual sampled FV values.

    Equivalence on a synthetic grid is too strict because formulas can
    differ on measure-zero discontinuity points (half-integers for
    round vs floor+0.5; quarter-integers for ceil vs floor+1) that the
    continuous FV process never visits. We test against the realized
    FV values to capture only the disagreements that actually matter.
    """
    sample_fvs = [f.server_fv for f in facts]
    mismatches = [
        (fv, predict_price(rule, fv), truth_fn(fv))
        for fv in sample_fvs
        if predict_price(rule, fv) != truth_fn(fv)
    ]
    # Allow at most 0.5% mismatch (measure-zero coincidences from
    # floating-point edge cases).
    threshold = max(1, int(0.005 * len(sample_fvs)))
    assert len(mismatches) <= threshold, (
        f"{label}: predicted prices diverge from truth on "
        f"{len(mismatches)}/{len(sample_fvs)} sampled FV values "
        f"(threshold {threshold}). "
        f"First mismatch: fv={mismatches[0][0]}, "
        f"predicted={mismatches[0][1]}, truth={mismatches[0][2]}. "
        f"Rule: {rule.round_fn}(fv {rule.shift:+.2f}) {rule.offset:+d}"
    )


def test_quote_rule_search_recovers_bot1(synthetic_data):
    facts, _ = synthetic_data
    bands = detect_depth_bands(facts)
    outer_bid = next(
        b for b in bands
        if b.side == "bid" and 0.5 * (b.offset_min + b.offset_max) < -7
    )
    outer_ask = next(
        b for b in bands
        if b.side == "ask" and 0.5 * (b.offset_min + b.offset_max) > 7
    )
    rule_bid = search_quote_rule(facts, outer_bid)
    rule_ask = search_quote_rule(facts, outer_ask)
    assert rule_bid.match_rate > 0.95, (
        f"Bot 1 bid match {rule_bid.match_rate:.2%} too low; "
        f"got {rule_bid.round_fn}(fv {rule_bid.shift:+.2f}) {rule_bid.offset:+d}"
    )
    assert rule_ask.match_rate > 0.95, (
        f"Bot 1 ask match {rule_ask.match_rate:.2%} too low; "
        f"got {rule_ask.round_fn}(fv {rule_ask.shift:+.2f}) {rule_ask.offset:+d}"
    )
    # Functional equivalence on the realized FV trajectory.
    _assert_rule_equivalent_to_truth(rule_bid, _truth_bot1_bid, facts, label="Bot1 bid")
    _assert_rule_equivalent_to_truth(rule_ask, _truth_bot1_ask, facts, label="Bot1 ask")
    # Canonical shift is in [0, 1).
    assert 0.0 <= rule_bid.shift < 1.0
    assert 0.0 <= rule_ask.shift < 1.0


def test_quote_rule_search_recovers_bot2_asymmetric(synthetic_data):
    facts, _ = synthetic_data
    bands = detect_depth_bands(facts)
    inner_bid = next(
        b for b in bands
        if b.side == "bid"
        and -7.5 < 0.5 * (b.offset_min + b.offset_max) < -5.5
    )
    inner_ask = next(
        b for b in bands
        if b.side == "ask"
        and 5.5 < 0.5 * (b.offset_min + b.offset_max) < 7.5
    )
    rule_bid = search_quote_rule(facts, inner_bid)
    rule_ask = search_quote_rule(facts, inner_ask)
    assert rule_bid.match_rate > 0.95, (
        f"Bot 2 bid match {rule_bid.match_rate:.2%} too low: "
        f"{rule_bid.round_fn}(fv {rule_bid.shift:+.2f}) {rule_bid.offset:+d}"
    )
    assert rule_ask.match_rate > 0.95, (
        f"Bot 2 ask match {rule_ask.match_rate:.2%} too low: "
        f"{rule_ask.round_fn}(fv {rule_ask.shift:+.2f}) {rule_ask.offset:+d}"
    )
    # Functional equivalence with the asymmetric truth.
    _assert_rule_equivalent_to_truth(rule_bid, _truth_bot2_bid, facts, label="Bot2 bid")
    _assert_rule_equivalent_to_truth(rule_ask, _truth_bot2_ask, facts, label="Bot2 ask")
    # Canonical shift in [0, 1).
    assert 0.0 <= rule_bid.shift < 1.0
    assert 0.0 <= rule_ask.shift < 1.0


def test_volume_fit_recovers_uniform(synthetic_data):
    facts, _ = synthetic_data
    bands = detect_depth_bands(facts)
    inner_bid = next(
        b for b in bands
        if b.side == "bid"
        and -7.5 < 0.5 * (b.offset_min + b.offset_max) < -5.5
    )
    fit = fit_volume_distribution(facts, inner_bid)
    assert fit.min_volume == TRUE_BOT2_VOL_MIN
    assert fit.max_volume == TRUE_BOT2_VOL_MAX
    # Uniformity should not be rejected (p > 0.01) for a true uniform sample.
    assert fit.p_value_uniform > 0.01, (
        f"Bot 2 vol fit rejected uniform: chi2={fit.chi_squared:.2f}, p={fit.p_value_uniform:.4f}"
    )


def test_trade_arrivals_recover_p(synthetic_data):
    facts, trades = synthetic_data
    arr = fit_trade_arrivals(facts, trades)
    # 95% CI for binomial proportion at p=0.04, n=5000: SE ~ 0.0028
    assert abs(arr.p_active - TRUE_P_ACTIVE) < 0.01, (
        f"p_active mismatch: {arr.p_active:.4f} vs true {TRUE_P_ACTIVE:.4f}"
    )
    # KS vs geometric should be small (well-fit).
    assert arr.geometric_ks_stat < 0.10, (
        f"geometric KS stat too large: {arr.geometric_ks_stat:.4f}"
    )


def test_trade_sizes_recover_uniform(synthetic_data):
    _, trades = synthetic_data
    fit_buy = fit_trade_sizes(trades, side="buy")
    fit_sell = fit_trade_sizes(trades, side="sell")
    for fit, label in ((fit_buy, "buy"), (fit_sell, "sell")):
        assert fit.n_samples > 0, f"no {label} trades classified"
        assert min(fit.sizes) >= TRUE_TRADE_SIZE_MIN
        assert max(fit.sizes) <= TRUE_TRADE_SIZE_MAX


def test_trade_locations_concentrate_at_walls(synthetic_data):
    facts, trades = synthetic_data
    loc_buy = fit_trade_locations(facts, trades, side="buy")
    loc_sell = fit_trade_locations(facts, trades, side="sell")
    edges = list(loc_buy.bin_edges)
    # Buy trades hit ask wall: location should be in the +6 to +8 range.
    centers = [0.5 * (edges[i] + edges[i + 1]) for i in range(len(edges) - 1)]
    buy_in_target = sum(
        c for c, n in zip(centers, loc_buy.counts) if 5.5 <= c <= 8.5 and n > 0
    )
    assert buy_in_target > 0, (
        "no buy trades in target ask-wall range (+6 to +8)"
    )
    sell_in_target = sum(
        abs(c) for c, n in zip(centers, loc_sell.counts) if -8.5 <= c <= -5.5 and n > 0
    )
    assert sell_in_target > 0, (
        "no sell trades in target bid-wall range (-8 to -6)"
    )

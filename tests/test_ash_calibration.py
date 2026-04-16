"""Unit tests for ``src.analysis.ash_calibration``.

Tests use synthetic fixtures with *known* parameters and assert the
calibration primitives recover them within tolerance. No real
market-data reads here — those are driven by the runner's integration
path and not pinned to exact expected values.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from src.analysis.ash_calibration import (
    FillIntensity,
    MarkoutCurve,
    OFIFit,
    OUParams,
    _bid_ask_from_snapshot,
    _order_flow_increment,
    _residual_value,
    fit_fill_intensity,
    fit_ou,
    fit_residual_markout,
)
from src.core.types import BookLevel, NormalizedSnapshot

# ------------------------------------------------------------------ fixtures


def _ou_path(theta: float, mu: float, sigma: float, n: int, dt: int, seed: int) -> list[float]:
    """Simulate a discrete OU path ``ds = theta*(mu-s)*dt + sigma*sqrt(dt)*eps``.

    Uses the exact discretisation ``s_{t+1} = mu + (s_t - mu)*exp(-theta*dt)
    + sigma*sqrt((1 - exp(-2 theta dt)) / (2 theta)) * eps``.
    """

    rng = np.random.default_rng(seed)
    beta = math.exp(-theta * dt)
    sd = sigma * math.sqrt((1.0 - math.exp(-2.0 * theta * dt)) / (2.0 * theta))
    xs = [mu]
    for _ in range(n - 1):
        eps = float(rng.standard_normal())
        xs.append(mu + (xs[-1] - mu) * beta + sd * eps)
    return xs


def _make_snapshot(
    ts: int,
    best_bid_price: int,
    best_bid_volume: int,
    best_ask_price: int,
    best_ask_volume: int,
) -> NormalizedSnapshot:
    return NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=ts,
        bids=(BookLevel(price=best_bid_price, volume=best_bid_volume),),
        asks=(BookLevel(price=best_ask_price, volume=best_ask_volume),),
    )


# ------------------------------------------------------------------ fit_ou


def test_fit_ou_recovers_known_params() -> None:
    theta_true = 0.02
    mu_true = 10_000.0
    sigma_true = 5.0
    path = _ou_path(theta=theta_true, mu=mu_true, sigma=sigma_true, n=5_000, dt=1, seed=11)
    fit = fit_ou(path, dt=1)
    assert isinstance(fit, OUParams)
    # MLE is consistent but noisy at n=5000 for slow reversion; tolerances
    # here are generous but tight enough that a broken implementation
    # would fail by orders of magnitude. AR(1) OLS standard error on
    # beta is ~sqrt(1-beta^2)/sqrt(n) ≈ 0.003 for these params, which
    # translates to roughly 30% relative error on theta.
    assert fit.theta == pytest.approx(theta_true, rel=0.4)
    assert fit.mu == pytest.approx(mu_true, abs=15.0)
    assert fit.sigma == pytest.approx(sigma_true, rel=0.2)
    assert fit.half_life == pytest.approx(math.log(2.0) / theta_true, rel=0.4)
    assert fit.n_samples == 5_000
    assert fit.residual_rmse > 0.0


def test_fit_ou_on_constant_series_returns_degenerate_flag() -> None:
    path = [10_000.0] * 500
    fit = fit_ou(path, dt=1)
    # Constant series: no reversion signal, degenerate=True, theta/sigma undefined but finite.
    assert fit.degenerate is True
    assert fit.sigma == pytest.approx(0.0, abs=1e-9)


def test_fit_ou_with_dt_multiplier_rescales_theta() -> None:
    """If the caller declares dt=100, theta should be expressed per dt=1 tick."""
    theta_true = 0.002  # per tick
    mu_true = 10_000.0
    sigma_true = 2.5
    # Generate a dense path at dt=1, then downsample to dt=100 and refit.
    dense = _ou_path(theta=theta_true, mu=mu_true, sigma=sigma_true, n=10_000, dt=1, seed=17)
    sparse = dense[::100]
    fit = fit_ou(sparse, dt=100)
    assert fit.theta == pytest.approx(theta_true, rel=0.6)
    assert fit.mu == pytest.approx(mu_true, abs=20.0)


# --------------------------------------------------------- fit_fill_intensity


def test_fit_fill_intensity_recovers_exponential() -> None:
    # Synthetic intensity: lambda(delta) = A * exp(-k * delta).
    a_true, k_true = 0.5, 0.4
    offsets = (0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    fit_points = tuple((d, a_true * math.exp(-k_true * d)) for d in offsets)
    fit = FillIntensity.from_points(fit_points)
    assert isinstance(fit, FillIntensity)
    assert fit.a == pytest.approx(a_true, rel=1e-3)
    assert fit.k == pytest.approx(k_true, rel=1e-3)
    assert fit.r_squared > 0.99


def test_fit_fill_intensity_real_path() -> None:
    """End-to-end fit from a contrived snapshots+trades pair.

    Constructs a trade tape where trades at price = mid - delta happen at
    known rates, then checks that the measured intensity is monotonic
    in delta and the fit parameters are plausible.
    """
    offsets = (1.0, 2.0, 3.0, 5.0)
    snapshots: list[NormalizedSnapshot] = []
    trades_by_ts: dict[int, list[tuple[int, int]]] = {}  # ts -> [(price, qty)]
    n_snaps = 1_000
    base_mid = 10_000
    rng = random.Random(23)
    # Seed higher rates at small offsets (lots of trades at mid-1), lower rates at large.
    rates = {1.0: 0.5, 2.0: 0.25, 3.0: 0.1, 5.0: 0.02}
    for ts in range(n_snaps):
        snapshots.append(_make_snapshot(ts, best_bid_price=base_mid - 8,
                                        best_bid_volume=10,
                                        best_ask_price=base_mid + 8,
                                        best_ask_volume=10))
        trades_here: list[tuple[int, int]] = []
        for d, rate in rates.items():
            if rng.random() < rate:
                # Sell trade at mid - d (a buyer at our bid would eat it).
                trades_here.append((int(base_mid - d), 1))
        trades_by_ts[ts] = trades_here

    fit = fit_fill_intensity(
        snapshots=snapshots,
        trades_by_ts=trades_by_ts,
        offsets=offsets,
        side="bid",
        fair_of_snapshot=lambda s: float(s.mid) if s.mid is not None else 0.0,
    )
    assert isinstance(fit, FillIntensity)
    # Intensity monotone decreasing in delta.
    rates_measured = dict(fit.fit_points)
    offsets_sorted = sorted(rates_measured)
    from itertools import pairwise
    for a, b in pairwise(offsets_sorted):
        assert rates_measured[a] >= rates_measured[b] - 0.02
    assert fit.k > 0.0
    assert fit.a > 0.0


# ------------------------------------------------------------------ OFI


def test_order_flow_increment_cases() -> None:
    """Cont-Stoikov-Talreja increment, exhaustive over bid-side cases."""
    # Same price, volume up: +1
    assert _order_flow_increment(
        prev_bid_price=100, prev_bid_volume=10,
        curr_bid_price=100, curr_bid_volume=11,
        prev_ask_price=110, prev_ask_volume=10,
        curr_ask_price=110, curr_ask_volume=10,
    ) == 1
    # Bid price up: full new volume contributes to +
    assert _order_flow_increment(
        prev_bid_price=100, prev_bid_volume=10,
        curr_bid_price=101, curr_bid_volume=5,
        prev_ask_price=110, prev_ask_volume=10,
        curr_ask_price=110, curr_ask_volume=10,
    ) == 5
    # Bid price down: -prev_bid_volume
    assert _order_flow_increment(
        prev_bid_price=100, prev_bid_volume=10,
        curr_bid_price=99, curr_bid_volume=7,
        prev_ask_price=110, prev_ask_volume=10,
        curr_ask_price=110, curr_ask_volume=10,
    ) == -10
    # Ask price down: +new_ask_volume (aggressive seller)
    assert _order_flow_increment(
        prev_bid_price=100, prev_bid_volume=10,
        curr_bid_price=100, curr_bid_volume=10,
        prev_ask_price=110, prev_ask_volume=10,
        curr_ask_price=109, curr_ask_volume=4,
    ) == 4
    # Ask same, volume up: -1 (more supply at ask)
    assert _order_flow_increment(
        prev_bid_price=100, prev_bid_volume=10,
        curr_bid_price=100, curr_bid_volume=10,
        prev_ask_price=110, prev_ask_volume=10,
        curr_ask_price=110, curr_ask_volume=12,
    ) == -2


def test_fit_ofi_signal_recovers_planted_slope() -> None:
    rng = np.random.default_rng(31)
    n = 3_000
    # Synthetic OFI and a planted linear relationship.
    ofi = rng.normal(0.0, 3.0, size=n)
    beta_true = 0.12
    noise = rng.normal(0.0, 0.4, size=n)
    d_mid = beta_true * ofi + noise
    out = OFIFit.from_pairs(ofi_series=ofi.tolist(), d_mid_series=d_mid.tolist(),
                            horizon=1)
    assert isinstance(out, OFIFit)
    assert out.slope == pytest.approx(beta_true, rel=0.15)
    assert out.horizon == 1
    assert 0.3 < out.r_squared < 0.9  # with the noise level set above
    assert out.n_samples == n


def test_fit_ofi_signal_no_signal_gives_low_r_squared() -> None:
    rng = np.random.default_rng(41)
    n = 2_000
    ofi = rng.normal(0.0, 3.0, size=n)
    d_mid = rng.normal(0.0, 1.0, size=n)  # independent
    out = OFIFit.from_pairs(ofi_series=ofi.tolist(), d_mid_series=d_mid.tolist(),
                            horizon=1)
    assert out.r_squared < 0.05


# ----------------------------------------------------------- markout curve


def test_residual_value_wall_mid_matches_manual_formula() -> None:
    snap = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=9_990, volume=10), BookLevel(price=9_985, volume=30)),
        asks=(BookLevel(price=10_010, volume=10), BookLevel(price=10_015, volume=30)),
    )
    # Residual = mid - wall_mid (strategy-code convention).
    wall_mid = (9_985 + 10_015) / 2.0
    expected = float(snap.mid) - wall_mid  # type: ignore[arg-type]
    resid = _residual_value(snap, fv_method="wall_mid")
    assert resid == pytest.approx(expected)


def test_fit_residual_markout_bucketed_reversion_is_monotone() -> None:
    """Plant ``forward_return = -0.3 * residual + noise`` and verify recovery.

    By construction the (residual, forward-return) correlation is negative
    and the markout curve should be monotone-decreasing in the residual
    decile index (first bucket = most negative residual = largest positive
    markout; last bucket = most positive residual = largest negative
    markout).
    """

    rng = np.random.default_rng(53)
    n = 2_000
    snapshots = []
    next_mids = []
    for i in range(n):
        # Inside book (volume 1) is symmetric around 10 000; the *wall*
        # levels (volume 30) are shifted by ``shift`` on both sides so
        # wall_mid = mid + shift. Under the strategy-code residual
        # convention (residual = mid - fair = mid - wall_mid) this
        # gives residual = -shift.
        r = float(rng.normal(0.0, 1.5))
        shift = round(r)
        best_bid = 10_000 - 4
        best_ask = 10_000 + 4
        wall_bid_price = best_bid - 8 + shift
        wall_ask_price = best_ask + 8 + shift
        bids = (
            BookLevel(price=best_bid, volume=1),
            BookLevel(price=wall_bid_price, volume=30),
        )
        asks = (
            BookLevel(price=best_ask, volume=1),
            BookLevel(price=wall_ask_price, volume=30),
        )
        snap = NormalizedSnapshot(
            product="ASH_COATED_OSMIUM", timestamp=i, bids=bids, asks=asks,
        )
        snapshots.append(snap)
        mid_now = float(snap.mid)  # type: ignore[arg-type]
        # Plant a dossier-style negative corr(residual, fwd_return).
        # Under this convention: residual = -shift, so choose
        # fwd_return = +0.5 * shift + noise  → fwd_return = -0.5 * residual.
        next_mids.append(mid_now + 0.5 * float(shift) + float(rng.normal(0, 0.2)))

    curve = fit_residual_markout(
        snapshots=snapshots,
        future_mids_by_horizon={1: next_mids},
        fv_method="wall_mid",
        n_deciles=10,
    )
    assert isinstance(curve, MarkoutCurve)
    assert curve.fv_method == "wall_mid"
    assert curve.residual_sigma > 0.0
    first_decile_markout = curve.deciles[0][1][1]
    last_decile_markout = curve.deciles[-1][1][1]
    assert first_decile_markout > last_decile_markout  # most-neg residual → most-positive fwd_ret
    assert curve.correlation_by_horizon[1] < -0.3  # dossier-style negative corr


# ------------------------------------------------------ helper sanity checks


def test_bid_ask_from_snapshot_returns_none_when_one_sided() -> None:
    snap = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=9_990, volume=10),),
        asks=(),
    )
    assert _bid_ask_from_snapshot(snap) is None
    snap_ok = NormalizedSnapshot(
        product="ASH_COATED_OSMIUM",
        timestamp=0,
        bids=(BookLevel(price=9_990, volume=10),),
        asks=(BookLevel(price=10_010, volume=10),),
    )
    out = _bid_ask_from_snapshot(snap_ok)
    assert out == (9_990, 10, 10_010, 10)

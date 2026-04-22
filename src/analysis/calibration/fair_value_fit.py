"""Fit the latent fair-value process model from recovered server FV.

Model: discrete-time Gaussian random walk

    FV(t+1) = FV(t) + sigma * Z_t,   Z_t ~ N(0, 1)  i.i.d.

Estimators:
    - sigma   = sample std of Delta-FV (1-tick increments)
    - mean    = sample mean of Delta-FV (should be near zero)
    - ar1_phi = OLS of r(t+1) on r(t), with asymptotic SE
    - VR(k)   = Var(Delta-FV over k ticks) / [k * Var(Delta-FV 1-tick)]

Diagnostics:
    - quantization grid: smallest non-zero gap in sorted unique FV values
    - variance ratio over default horizons {2, 5, 10, 20, 50, 100}

The fit explicitly does not include drift (the mean is reported but
not used by the simulator) and does not include AR(1) corrections (φ
is reported for transparency; chrispyroberts confirmed |φ| ≈ 0.18 on
tutorial data and elected to ignore it because (a) it's marginal in
significance and (b) including it does not measurably improve the
simulator's downstream diagnostics).
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from src.analysis.calibration.types import FactRow, FairValueFit

DEFAULT_VR_HORIZONS: tuple[int, ...] = (2, 5, 10, 20, 50, 100)


def fit_fair_value_process(
    facts: Sequence[FactRow],
    *,
    vr_horizons: tuple[int, ...] = DEFAULT_VR_HORIZONS,
    quantization_atoms: int = 16,
) -> FairValueFit:
    """Fit the FV random-walk model and return a frozen FairValueFit.

    Args:
        facts: Per-tick fact rows for one product (sorted by timestamp).
        vr_horizons: k values for the variance ratio test.
        quantization_atoms: Minimum number of distinct FV values that
            must be present for the quantization grid estimate to be
            considered meaningful. Below this, returns None.

    Raises:
        ValueError: if fewer than 3 fact rows are provided (not enough
            to compute returns).
    """
    if len(facts) < 3:
        raise ValueError(
            f"Need at least 3 fact rows to fit FV process; got {len(facts)}"
        )
    fv = np.asarray([f.server_fv for f in facts], dtype=float)
    returns = np.diff(fv)
    sigma = float(np.std(returns, ddof=1))
    mean_return = float(np.mean(returns))

    # AR(1) is fit on demeaned returns. Failing to demean introduces a
    # spurious positive phi when the series has any drift: both x_t and
    # x_{t+1} are biased above zero so their cross-product is biased up.
    # We saw exactly this on PEPPER (drift +0.094/tick produced a fake
    # phi=+0.21). Demeaning isolates true autocorrelation from drift.
    phi, phi_se = _ar1_fit(returns - mean_return)
    vr = tuple(_variance_ratio(returns, k) for k in vr_horizons)
    grid = _detect_quantization(fv, min_atoms=quantization_atoms)

    return FairValueFit(
        sigma=sigma,
        mean_return=mean_return,
        n_returns=len(returns),
        ar1_phi=phi,
        ar1_phi_se=phi_se,
        vr_horizons=vr_horizons,
        variance_ratio=vr,
        quantization_grid=grid,
        fv_min=float(np.min(fv)),
        fv_max=float(np.max(fv)),
    )


# ----------------------------------------------------------- internals


def _ar1_fit(returns: np.ndarray) -> tuple[float, float]:
    """OLS fit of r(t+1) = phi * r(t), with asymptotic SE.

    Returns (phi, se_phi). When sample is too small or degenerate
    (zero variance), returns (0.0, inf) so callers can handle gracefully.
    """
    if len(returns) < 4:
        return (0.0, math.inf)
    x = returns[:-1]
    y = returns[1:]
    denom = float(np.dot(x, x))
    if denom == 0.0:
        return (0.0, math.inf)
    phi = float(np.dot(x, y) / denom)
    # Asymptotic SE under H0 of white noise: 1/sqrt(N).
    # When phi is nonzero, standard correction is sqrt((1-phi^2)/N).
    n = len(returns) - 1
    se = math.sqrt(max(1.0 - phi * phi, 1e-12) / n)
    return (phi, se)


def _variance_ratio(returns: np.ndarray, k: int) -> float:
    """Lo-MacKinlay variance ratio at horizon k.

    Aggregates returns into non-overlapping k-tick blocks and computes
    Var(block) / (k * Var(1-tick)). For a random walk, VR -> 1 for all k.
    """
    if k < 2 or len(returns) < 2 * k:
        return float("nan")
    var1 = float(np.var(returns, ddof=1))
    if var1 == 0.0:
        return float("nan")
    n_blocks = len(returns) // k
    blocks = returns[: n_blocks * k].reshape(n_blocks, k).sum(axis=1)
    var_k = float(np.var(blocks, ddof=1))
    return var_k / (k * var1)


def _detect_quantization(fv: np.ndarray, *, min_atoms: int) -> float | None:
    """Find the smallest non-zero gap between sorted unique FV values.

    If fewer than ``min_atoms`` distinct values exist, returns None
    (sample is too small for the estimate to be meaningful).
    """
    unique = np.unique(fv)
    if len(unique) < min_atoms:
        return None
    diffs = np.diff(unique)
    nonzero = diffs[diffs > 0]
    if len(nonzero) == 0:
        return None
    return float(np.min(nonzero))

"""Brute-force search for bot quote-placement rules.

For each detected depth band, search over the family of formulas

    price = round_fn(server_fv + shift) + offset

where round_fn ∈ {floor, ceil, round}, shift ∈ a fine grid, and offset
is constrained to integers within the band's empirical range. The
candidate with the highest match rate wins.

Why brute force works:
    The hypothesis class is small (typically <100 candidates per side
    per bot) and the data is large (10000+ ticks). Under a wrong
    hypothesis, predicted prices can take ~17 plausible integer values
    so chance match rate is ~6%. Winning hypotheses score 96-99%.
    Signal-to-noise is overwhelming; this is exact rule recovery, not
    statistical fitting.

Match-rate threshold:
    A rule with match rate >= 0.95 is considered structurally recovered.
    Below that, the bot may have stochastic placement, multiple sub-
    populations, or a more complex rule family. Caller decides what
    to do with low-match-rate rules (typically: report them but flag).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Callable

import numpy as np

from src.analysis.calibration.types import (
    BookLevel,
    DepthBand,
    FactRow,
    QuoteRule,
    VolumeFit,
)

# Search ordering matters: when multiple (round_fn, shift, offset) tuples
# achieve the same match rate, the FIRST one found wins. We bias the order
# so that the most "natural" forms — chrispyroberts's preferred canonical
# representation — are tried first. This avoids reporting equivalent but
# weird-looking formulas like ``floor(fv + 0.5) + 7`` when ``round(fv) + 8``
# is the cleaner equivalent.
DEFAULT_SHIFTS: tuple[float, ...] = (
    0.0,    # natural for round
    0.5,    # natural for round / floor
    0.25,   # natural for ceil (Bot 2 ask)
    0.75,   # natural for floor (Bot 2 bid)
    -0.25, -0.5, -0.75, -1.0, 1.0,
)

# round first, so round-based formulas win ties.
ROUND_FNS: dict[str, Callable[[float], int]] = {
    "round": lambda x: int(round(x)),
    "floor": lambda x: int(math.floor(x)),
    "ceil": lambda x: int(math.ceil(x)),
}


def search_quote_rule(
    facts: Sequence[FactRow],
    band: DepthBand,
    *,
    shifts: tuple[float, ...] = DEFAULT_SHIFTS,
) -> QuoteRule:
    """Find the best-matching formula for a single depth band.

    The search space is {floor, ceil, round} x shifts x integer offsets
    in the band's empirical range. Returns the candidate with highest
    match rate over all (timestamp, observed_price) pairs falling in
    the band.
    """
    samples = _collect_band_samples(facts, band)
    if not samples:
        return QuoteRule(
            bot_name=band.name,
            side=band.side,
            round_fn="round",
            shift=0.0,
            offset=0,
            match_rate=0.0,
            n_samples=0,
        )

    # Determine integer offset range from the band's empirical bounds.
    offset_min = int(math.floor(band.offset_min))
    offset_max = int(math.ceil(band.offset_max))
    offset_candidates = range(offset_min, offset_max + 1)

    best = QuoteRule(
        bot_name=band.name,
        side=band.side,
        round_fn="round",
        shift=0.0,
        offset=0,
        match_rate=0.0,
        n_samples=len(samples),
    )
    for round_name, round_fn in ROUND_FNS.items():
        for shift in shifts:
            for offset in offset_candidates:
                rate = _match_rate(samples, round_fn=round_fn, shift=shift, offset=offset)
                if rate > best.match_rate:
                    best = QuoteRule(
                        bot_name=band.name,
                        side=band.side,
                        round_fn=round_name,
                        shift=shift,
                        offset=offset,
                        match_rate=rate,
                        n_samples=len(samples),
                    )
    return canonicalize_rule(best)


def canonicalize_rule(rule: QuoteRule) -> QuoteRule:
    """Normalize rule to a canonical representation.

    The transformation ``floor(fv + s + 1) - 1 == floor(fv + s)`` (and
    similarly for ``ceil`` and ``round``) means many distinct
    (round_fn, shift, offset) tuples produce identical predictions.
    We normalize ``shift`` into ``[0, 1)`` and adjust ``offset`` to
    compensate, which gives a single canonical form per equivalence
    class. Match rate and n_samples are preserved.
    """
    shift = rule.shift
    offset = rule.offset
    while shift < 0:
        shift += 1.0
        offset -= 1
    while shift >= 1.0:
        shift -= 1.0
        offset += 1
    # Snap shift to nearest grid value (floating-point hygiene).
    shift = round(shift * 100) / 100
    return QuoteRule(
        bot_name=rule.bot_name,
        side=rule.side,
        round_fn=rule.round_fn,
        shift=shift,
        offset=offset,
        match_rate=rule.match_rate,
        n_samples=rule.n_samples,
    )


def predict_price(rule: QuoteRule, server_fv: float) -> int:
    """Evaluate a QuoteRule on a single FV value."""
    fn = ROUND_FNS[rule.round_fn]
    return fn(server_fv + rule.shift) + rule.offset


def fit_volume_distribution(
    facts: Sequence[FactRow], band: DepthBand
) -> VolumeFit:
    """Empirical volume distribution for one band, with uniformity test.

    Returns ``min_volume``, ``max_volume``, sample size, and a
    chi-squared statistic + p-value testing the null that volumes are
    uniform on [min, max].
    """
    volumes = _collect_band_volumes(facts, band)
    if not volumes:
        return VolumeFit(
            bot_name=band.name,
            side=band.side,
            min_volume=0,
            max_volume=0,
            n_samples=0,
            chi_squared=0.0,
            p_value_uniform=1.0,
        )
    arr = np.asarray(volumes, dtype=int)
    vmin = int(arr.min())
    vmax = int(arr.max())
    chi2, p = _chi_squared_uniform(arr, vmin=vmin, vmax=vmax)
    return VolumeFit(
        bot_name=band.name,
        side=band.side,
        min_volume=vmin,
        max_volume=vmax,
        n_samples=len(arr),
        chi_squared=chi2,
        p_value_uniform=p,
    )


# ----------------------------------------------------------- internals


def _collect_band_samples(
    facts: Sequence[FactRow], band: DepthBand
) -> list[tuple[float, int]]:
    """Return [(server_fv, observed_price), ...] for levels at this band's rank.

    Uses the rank embedded in the band name (``level1_*``, ``level2_*``,
    etc.) to pick the correct level rather than offset windowing — this
    avoids cross-contamination between adjacent bots whose offset
    distributions may abut.
    """
    rank = _rank_from_name(band.name)
    out: list[tuple[float, int]] = []
    for fact in facts:
        levels = fact.bids if band.side == "bid" else fact.asks
        if len(levels) >= rank:
            level = levels[rank - 1]
            out.append((fact.server_fv, level.price))
    return out


def _collect_band_volumes(
    facts: Sequence[FactRow], band: DepthBand
) -> list[int]:
    rank = _rank_from_name(band.name)
    out: list[int] = []
    for fact in facts:
        levels = fact.bids if band.side == "bid" else fact.asks
        if len(levels) >= rank:
            out.append(levels[rank - 1].volume)
    return out


def _rank_from_name(name: str) -> int:
    head = name.split("_", 1)[0]  # 'level2'
    return int(head.replace("level", ""))


def _match_rate(
    samples: Sequence[tuple[float, int]],
    *,
    round_fn: Callable[[float], int],
    shift: float,
    offset: int,
) -> float:
    if not samples:
        return 0.0
    n_match = 0
    for fv, observed in samples:
        predicted = round_fn(fv + shift) + offset
        if predicted == observed:
            n_match += 1
    return n_match / len(samples)


def _chi_squared_uniform(
    arr: np.ndarray, *, vmin: int, vmax: int
) -> tuple[float, float]:
    """Pearson chi-squared test against discrete uniform on [vmin, vmax]."""
    k = vmax - vmin + 1
    if k < 2:
        return (0.0, 1.0)
    n = len(arr)
    expected = n / k
    if expected < 1.0:
        # Underpowered; report stat but mark p as inconclusive (NaN-equivalent).
        observed_counts = np.bincount(arr - vmin, minlength=k)
        chi2 = float(np.sum((observed_counts - expected) ** 2 / expected))
        return (chi2, math.nan)
    observed_counts = np.bincount(arr - vmin, minlength=k)
    chi2 = float(np.sum((observed_counts - expected) ** 2 / expected))
    df = k - 1
    p = _chi2_sf(chi2, df=df)
    return (chi2, p)


def _chi2_sf(chi2: float, *, df: int) -> float:
    """Survival function of chi-squared distribution (1 - CDF).

    Computed via the regularized upper incomplete gamma function.
    """
    if chi2 <= 0:
        return 1.0
    # Use math.erfc for df=1 special case; otherwise series via gammainc.
    # We'll use the series form computed manually to avoid scipy dep.
    return _gammainc_upper(df / 2.0, chi2 / 2.0)


def _gammainc_upper(s: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(s, x) = Gamma(s, x) / Gamma(s).

    Uses the continued fraction expansion for x > s + 1, otherwise the
    power series for the lower incomplete and complements.
    """
    if x < 0 or s < 0:
        raise ValueError("Negative argument to incomplete gamma.")
    if x == 0:
        return 1.0
    if x < s + 1:
        return 1.0 - _gammainc_lower_series(s, x)
    return _gammainc_upper_cf(s, x)


def _gammainc_lower_series(s: float, x: float) -> float:
    """Power series for regularized lower incomplete gamma P(s, x)."""
    term = 1.0 / s
    total = term
    for n in range(1, 200):
        term *= x / (s + n)
        total += term
        if abs(term) < abs(total) * 1e-12:
            break
    return total * math.exp(-x + s * math.log(x) - math.lgamma(s))


def _gammainc_upper_cf(s: float, x: float) -> float:
    """Continued fraction for regularized upper incomplete gamma Q(s, x)."""
    eps = 1e-12
    fpmin = 1e-300
    b = x + 1.0 - s
    c = 1.0 / fpmin
    d = 1.0 / b
    h = d
    for i in range(1, 200):
        an = -i * (i - s)
        b += 2.0
        d = an * d + b
        if abs(d) < fpmin:
            d = fpmin
        c = b + an / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h * math.exp(-x + s * math.log(x) - math.lgamma(s))

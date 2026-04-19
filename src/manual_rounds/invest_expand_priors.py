"""Opponent v-distribution priors for Invest & Expand.

Each function returns a ``VPrior`` (tuple of 101 floats summing to 1)
representing the probability that a randomly-drawn opposing team picks
``v = i``. These are intentionally simple and transparent so the
call-site can audit which assumption dominates its recommendation.

Taxonomy:

- ``naive_*``          - unsophisticated-but-plausible field behaviour
- ``optimising_*``     - what a quant team would pick given some mu belief
- ``mixture``          - linear combination for heterogeneous fields
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from src.manual_rounds.invest_expand import MAX_PCT, VPrior


def _normalize_pmf(weights: Sequence[float]) -> VPrior:
    if len(weights) != MAX_PCT + 1:
        raise ValueError(f"weights must have {MAX_PCT + 1} entries")
    total = sum(weights)
    if total <= 0:
        raise ValueError("prior weights must sum to > 0")
    return tuple(w / total for w in weights)


def spike(v: int) -> VPrior:
    """All mass at a single integer v."""
    if v < 0 or v > MAX_PCT:
        raise ValueError(f"v={v} outside [0, {MAX_PCT}]")
    weights = [0.0] * (MAX_PCT + 1)
    weights[v] = 1.0
    return tuple(weights)


def uniform(v_lo: int = 0, v_hi: int = MAX_PCT) -> VPrior:
    """Uniform distribution on integer ``[v_lo, v_hi]``.

    ``uniform()`` is uniform on ``[0, 100]``.
    """
    if v_lo < 0 or v_hi > MAX_PCT or v_lo > v_hi:
        raise ValueError(f"bad range [{v_lo}, {v_hi}]")
    weights = [0.0] * (MAX_PCT + 1)
    for i in range(v_lo, v_hi + 1):
        weights[i] = 1.0
    return _normalize_pmf(weights)


def naive_thirds() -> VPrior:
    """All mass at ``v = 33``. Represents the "split evenly" heuristic.

    Players who treat the three pillars as symmetric and allocate
    approximately 33/33/33.
    """
    return spike(33)


def naive_ignore_speed() -> VPrior:
    """All mass at ``v = 0``. Player thinks "speed is a rank game I
    won't win, skip it"."""
    return spike(0)


def bimodal_split_vs_zero(
    zero_share: float,
    high_v: int = 33,
) -> VPrior:
    """Two-spike field: some fraction at v=0, rest at ``high_v``.

    Common adversarial prior when the field splits between "skip
    speed" and "naive thirds" heuristics.
    """
    if zero_share < 0 or zero_share > 1:
        raise ValueError(f"zero_share={zero_share} outside [0, 1]")
    weights = [0.0] * (MAX_PCT + 1)
    weights[0] = zero_share
    weights[high_v] = 1 - zero_share
    return _normalize_pmf(weights)


def trimodal_naive(
    zero_share: float = 0.3,
    thirds_share: float = 0.4,
    half_share: float = 0.3,
) -> VPrior:
    """Naive field with mass at ``v in {0, 33, 50}``.

    Represents a field of "skip speed / split evenly / put half on
    speed" heuristics. Default weights are a plausible naive-field
    guess absent empirical data.
    """
    weights = [0.0] * (MAX_PCT + 1)
    weights[0] = zero_share
    weights[33] = thirds_share
    weights[50] = half_share
    return _normalize_pmf(weights)


def nice_number_heavy() -> VPrior:
    """Mass concentrated at "nice" integers: 0, 10, 20, 25, 33, 50, 100.

    Players who don't optimise tend to pick round numbers. This prior
    captures the *locations* of that tendency; quant-heavy fields
    flatten out.
    """
    nice = {0: 0.25, 10: 0.1, 20: 0.1, 25: 0.1, 33: 0.15, 50: 0.15, 100: 0.15}
    weights = [0.0] * (MAX_PCT + 1)
    for v, w in nice.items():
        weights[v] = w
    return _normalize_pmf(weights)


def optimising_at_mu(mu_belief: float) -> VPrior:
    """A single-spike prior at the v a *rational* team would play
    given they believe the achieved mu will be ``mu_belief``.

    Derivation: setting the marginal returns equal along the r-curve
    and the s-direction yields ``s = 125 * mu_belief``; with
    ``r + s + v = 100`` and ``s = (1+r) ln(1+r)``, solve for r and v
    numerically.
    """
    if mu_belief <= 0 or mu_belief > 1.0:
        raise ValueError(f"mu_belief={mu_belief} outside (0, 1]")
    # From FOC: s = 125 * mu_belief (subject to s <= 100)
    target_s = min(100.0, 125 * mu_belief)
    # From s = (1+r) ln(1+r) solve for r (monotone increasing for r >= 0)
    # Start with bisection on r in [0, 100].
    lo, hi = 0.0, 100.0
    for _ in range(80):
        mid = (lo + hi) / 2
        f = (1 + mid) * math.log(1 + mid)
        if f < target_s:
            lo = mid
        else:
            hi = mid
    r_star = int(round((lo + hi) / 2))
    s_star = int(round(target_s))
    v_star = max(0, MAX_PCT - r_star - s_star)
    return spike(v_star)


def quant_cluster(
    mu_beliefs: Sequence[float] = (0.3, 0.5, 0.7, 0.9),
    weights: Sequence[float] | None = None,
) -> VPrior:
    """Mixture of optimising spikes under different mu beliefs.

    Represents a heterogeneous quant field where teams disagree on
    what mu to expect and therefore pick different optimising v.
    """
    if weights is None:
        weights = [1.0] * len(mu_beliefs)
    if len(weights) != len(mu_beliefs):
        raise ValueError("weights length must match mu_beliefs length")
    spikes = [(w, optimising_at_mu(m)) for m, w in zip(mu_beliefs, weights)]
    return mixture(spikes)


def mixture(components: Sequence[tuple[float, VPrior]]) -> VPrior:
    """Weighted mixture of priors. Weights do not need to sum to 1."""
    if not components:
        raise ValueError("components must be non-empty")
    weights_sum = sum(w for w, _ in components)
    if weights_sum <= 0:
        raise ValueError("component weights must sum to > 0")
    acc = [0.0] * (MAX_PCT + 1)
    for w, p in components:
        if w < 0:
            raise ValueError("component weights must be >= 0")
        for i, pi in enumerate(p):
            acc[i] += w * pi / weights_sum
    return tuple(acc)


def truncated_geometric(mean_v: float) -> VPrior:
    """Geometric-like prior with a user-specified mean on ``[0, 100]``.

    Useful when you believe most teams under-spend on speed but a
    long tail goes aggressive. ``mean_v`` must be in ``(0, 100)``.
    """
    if mean_v <= 0 or mean_v >= MAX_PCT:
        raise ValueError(f"mean_v={mean_v} outside (0, {MAX_PCT})")
    # Geometric pmf: P(v=k) proportional to (1-p)**k for k >= 0.
    # For large support, E[v] ~= (1-p)/p, so p = 1/(1+mean).
    p = 1.0 / (1.0 + mean_v)
    weights = [((1 - p) ** k) for k in range(MAX_PCT + 1)]
    return _normalize_pmf(weights)


def semi_naive_insurance_cluster(
    center: int = 5,
    spread: int = 5,
    cluster_share: float = 0.4,
    coast_share: float = 0.15,
    high_share: float = 0.15,
) -> VPrior:
    """MAF-fragility prior: a big cluster at ``v = center +- spread``
    from teams who FOC-solve (23, 77, 0), then "add a little v for
    insurance" and land at v in {5, 10, 15}.

    Defaults model ~40% of the field at v in [0, 10] (peaked at 5),
    15% pure coasters, 15% aggressive high-v, 30% uniform spread. This
    is the scenario the IMC MAF guidance explicitly warns against.
    """
    if not (0 <= cluster_share + coast_share + high_share <= 1):
        raise ValueError("share sum must be in [0, 1]")
    if center - spread < 0 or center + spread > MAX_PCT:
        raise ValueError(f"cluster [{center-spread},{center+spread}] out of range")
    residual = 1 - cluster_share - coast_share - high_share

    weights = [0.0] * (MAX_PCT + 1)
    # Cluster: triangular on [center-spread, center+spread]
    half = spread
    tri_total = sum(max(0, half - abs(center - v) + 1) for v in range(center - spread, center + spread + 1))
    for v in range(center - spread, center + spread + 1):
        w = max(0, half - abs(center - v) + 1) / tri_total
        weights[v] += cluster_share * w
    # Coasters at v=0
    weights[0] += coast_share
    # High-v at v in [50, 70]
    high_range = list(range(50, 71))
    for v in high_range:
        weights[v] += high_share / len(high_range)
    # Uniform residual
    if residual > 0:
        for v in range(MAX_PCT + 1):
            weights[v] += residual / (MAX_PCT + 1)
    return _normalize_pmf(weights)


def consensus_cluster(center: int, cluster_share: float = 0.4) -> VPrior:
    """Single sharp spike at ``center`` plus uniform on the rest.

    Used for focal-cluster stress tests: how bad is it if a big chunk
    of the field rationally converges on one specific v?
    """
    if not (0 <= cluster_share <= 1):
        raise ValueError(f"cluster_share={cluster_share} outside [0, 1]")
    if not (0 <= center <= MAX_PCT):
        raise ValueError(f"center={center} outside [0, {MAX_PCT}]")
    weights = [0.0] * (MAX_PCT + 1)
    weights[center] += cluster_share
    for v in range(MAX_PCT + 1):
        weights[v] += (1 - cluster_share) / (MAX_PCT + 1)
    return _normalize_pmf(weights)


def leapfrog_adversary(beat_v: int) -> VPrior:
    """Adversarial prior designed to punish candidates that play
    ``v < beat_v``. Concentrates mass just above ``beat_v`` so
    anyone at or below lands in the worst rank band.

    Used for worst-case stress testing: "what if the field plays
    exactly one tick above my bid?"
    """
    if not (0 <= beat_v < MAX_PCT):
        raise ValueError(f"beat_v={beat_v} outside [0, {MAX_PCT-1}]")
    weights = [0.0] * (MAX_PCT + 1)
    # 70% at beat_v+1, 30% at beat_v+2 (linear fall-off)
    weights[beat_v + 1] = 0.7
    if beat_v + 2 <= MAX_PCT:
        weights[beat_v + 2] = 0.3
    else:
        weights[beat_v + 1] += 0.3
    return _normalize_pmf(weights)


def empirical_from_samples(samples: Iterable[int]) -> VPrior:
    """Empirical PMF from integer samples. Zero-pads if some v unseen."""
    counts = [0] * (MAX_PCT + 1)
    n = 0
    for x in samples:
        if not isinstance(x, int):
            raise TypeError(f"sample must be int, got {type(x).__name__}")
        if x < 0 or x > MAX_PCT:
            raise ValueError(f"sample {x} outside [0, {MAX_PCT}]")
        counts[x] += 1
        n += 1
    if n == 0:
        raise ValueError("samples must be non-empty")
    return tuple(c / n for c in counts)

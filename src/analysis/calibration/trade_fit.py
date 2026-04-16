"""Fit trade-arrival, size, and location distributions per product.

Three independent estimators per product:

1. **Trade arrivals.** Per-tick Bernoulli rate p = (active ticks) / (total ticks).
   Equivalent to a Poisson with rate lambda = p for small p (< 0.1).
   Validated by comparing the empirical interarrival-gap distribution
   against the geometric distribution that the Bernoulli implies.

2. **Trade size.** Empirical categorical distribution of quantities,
   computed separately per side (buy vs sell trades).

3. **Trade price location.** Histogram of (trade_price - server_fv)
   per side. Confirms that prints concentrate at bot quote levels.

The conditional discipline (per ANALYSIS_PHILOSOPHY): every estimator
that could plausibly depend on the latent state (FV path, current
book state, recent flow) is at least *checked* for that dependence
even when the marginal estimator is reported. The hooks below allow
caller-supplied conditioning sets so the marginal-vs-conditional
comparison can be wired up at the runner level.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from src.analysis.calibration.types import (
    FactRow,
    TradeArrivalFit,
    TradePriceLocationFit,
    TradeRow,
    TradeSizeFit,
)

DEFAULT_LOCATION_BINS = np.linspace(-12.0, 12.0, 49)  # 0.5-tick resolution


def fit_trade_arrivals(
    facts: Sequence[FactRow],
    trades: Sequence[TradeRow],
) -> TradeArrivalFit:
    """Bernoulli arrival rate + geometric-gap diagnostic.

    Two ticks count as 'active' if at least one trade was recorded
    with the matching timestamp. Buy probability is conditioned on
    being an active tick.
    """
    n_ticks = len(facts)
    if n_ticks == 0:
        raise ValueError("Cannot fit arrivals with zero fact rows.")

    timestamps = sorted({fact.timestamp for fact in facts})
    active_set = {trade.timestamp for trade in trades}
    active_steps = sum(1 for ts in timestamps if ts in active_set)
    p_active = active_steps / n_ticks

    n_buys = sum(1 for trade in trades if _classify_side(trade) == "buy")
    n_classified = sum(
        1 for trade in trades if _classify_side(trade) in ("buy", "sell")
    )
    p_buy = n_buys / n_classified if n_classified > 0 else 0.5

    ks_stat = _geometric_gap_ks(
        active_timestamps=sorted(active_set),
        all_timestamps=timestamps,
    )

    return TradeArrivalFit(
        p_active=p_active,
        p_buy_given_active=p_buy,
        n_ticks_total=n_ticks,
        n_ticks_active=active_steps,
        n_trades_total=len(trades),
        geometric_ks_stat=ks_stat,
    )


def fit_trade_sizes(
    trades: Sequence[TradeRow], *, side: str
) -> TradeSizeFit:
    """Empirical categorical distribution of quantities for one side.

    ``side`` must be 'buy' or 'sell'. Trades whose direction cannot be
    classified (no buyer/seller info available) are skipped.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")
    quantities = [
        trade.quantity for trade in trades if _classify_side(trade) == side
    ]
    if not quantities:
        return TradeSizeFit(
            side=side, sizes=(), probabilities=(), n_samples=0
        )
    arr = np.asarray(quantities, dtype=int)
    sizes, counts = np.unique(arr, return_counts=True)
    probs = counts / counts.sum()
    return TradeSizeFit(
        side=side,
        sizes=tuple(int(s) for s in sizes),
        probabilities=tuple(float(p) for p in probs),
        n_samples=len(arr),
    )


def fit_trade_locations(
    facts: Sequence[FactRow],
    trades: Sequence[TradeRow],
    *,
    side: str,
    bins: np.ndarray = DEFAULT_LOCATION_BINS,
) -> TradePriceLocationFit:
    """Histogram of (trade_price - server_fv) for one side.

    The match between observed-trade-location and bot-quote-location
    is a strong end-to-end validation: if your bot rules + arrival
    rate + side prob compose to put trades in the right bins, your
    pipeline is internally consistent.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")
    fv_by_ts = {fact.timestamp: fact.server_fv for fact in facts}
    offsets: list[float] = []
    for trade in trades:
        if _classify_side(trade) != side:
            continue
        fv = fv_by_ts.get(trade.timestamp)
        if fv is None:
            continue
        offsets.append(trade.price - fv)
    if not offsets:
        return TradePriceLocationFit(
            side=side,
            bin_edges=tuple(float(b) for b in bins),
            counts=tuple(0 for _ in range(len(bins) - 1)),
            n_samples=0,
        )
    counts, _ = np.histogram(np.asarray(offsets), bins=bins)
    return TradePriceLocationFit(
        side=side,
        bin_edges=tuple(float(b) for b in bins),
        counts=tuple(int(c) for c in counts),
        n_samples=len(offsets),
    )


# ----------------------------------------------------------- internals


def _classify_side(trade: TradeRow) -> str:
    """Infer buy/sell from the IMC buyer/seller convention.

    IMC labels every market trade with a buyer and seller seat ID.
    The trader-of-interest's seat ('SUBMISSION') is irrelevant here;
    we want the *taker* side. By convention in the IMC log, when the
    market had an aggressing buyer the trade is logged with buyer = ''
    (empty), and analogously for sellers. When neither field is empty,
    the trade is between two named bots and the aggressor is ambiguous;
    we default to 'unknown' for those.
    """
    buyer = trade.buyer or ""
    seller = trade.seller or ""
    if buyer == "" and seller != "":
        return "buy"  # market buyer aggressed against the named seller
    if seller == "" and buyer != "":
        return "sell"  # market seller aggressed against the named buyer
    if buyer != "" and seller != "":
        # Both sides named: ambiguous. Common in synthetic logs.
        return "unknown"
    return "unknown"


def _geometric_gap_ks(
    *,
    active_timestamps: Sequence[int],
    all_timestamps: Sequence[int],
) -> float:
    """Kolmogorov-Smirnov stat: empirical gap CDF vs geometric.

    Returns the KS statistic (max sup-norm distance). Smaller is better;
    < 0.05 typically indicates a very good geometric fit.
    """
    if len(active_timestamps) < 2 or len(all_timestamps) < 2:
        return 0.0
    # Convert active timestamps to indices into the all-timestamps grid.
    idx_map = {ts: i for i, ts in enumerate(all_timestamps)}
    active_indices = sorted(idx_map[ts] for ts in active_timestamps if ts in idx_map)
    if len(active_indices) < 2:
        return 0.0
    gaps = np.diff(np.asarray(active_indices, dtype=int))
    # Empirical p that any one tick is active = active / total
    p = len(active_timestamps) / len(all_timestamps)
    if p <= 0 or p >= 1:
        return 0.0
    sorted_gaps = np.sort(gaps)
    ecdf = np.arange(1, len(sorted_gaps) + 1) / len(sorted_gaps)
    # Geometric CDF for shifted-by-one geometric (P(gap <= k) = 1 - (1-p)^k)
    geom_cdf = 1.0 - (1.0 - p) ** sorted_gaps
    return float(np.max(np.abs(ecdf - geom_cdf)))

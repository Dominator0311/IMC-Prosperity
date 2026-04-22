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

    fv_by_ts = {f.timestamp: f.server_fv for f in facts}
    n_buys = 0
    n_classified = 0
    for trade in trades:
        side = _classify_side(trade)
        if side == "unknown" and trade.timestamp in fv_by_ts:
            side = classify_side_by_fv(trade, fv_by_ts[trade.timestamp])
        if side == "buy":
            n_buys += 1
            n_classified += 1
        elif side == "sell":
            n_classified += 1
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
    trades: Sequence[TradeRow],
    *,
    side: str,
    facts: Sequence[FactRow] | None = None,
) -> TradeSizeFit:
    """Empirical categorical distribution of quantities for one side.

    ``side`` must be 'buy' or 'sell'. Trades are classified by buyer/
    seller fields when populated; when blank (the standard IMC
    market-trades CSV format), classification falls back to comparing
    print price against server FV (requires ``facts`` argument).
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")
    fv_by_ts = {f.timestamp: f.server_fv for f in facts} if facts else {}
    quantities: list[int] = []
    for trade in trades:
        classified = _classify_side(trade)
        if classified == "unknown" and trade.timestamp in fv_by_ts:
            classified = classify_side_by_fv(trade, fv_by_ts[trade.timestamp])
        if classified == side:
            quantities.append(trade.quantity)
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

    Trade direction is classified from buyer/seller fields when
    populated, otherwise inferred from price-vs-FV.
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell'; got {side!r}")
    fv_by_ts = {fact.timestamp: fact.server_fv for fact in facts}
    offsets: list[float] = []
    for trade in trades:
        fv = fv_by_ts.get(trade.timestamp)
        if fv is None:
            continue
        classified = _classify_side(trade)
        if classified == "unknown":
            classified = classify_side_by_fv(trade, fv)
        if classified != side:
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

    Two scenarios:

    1. **Activity log tradeHistory** (synthetic + real): buyer/seller
       fields populated. Per IMC convention, the empty side is the
       aggressor; e.g. ``buyer="" seller="BOT_X"`` -> market buyer
       aggressed BOT_X -> ``buy``.

    2. **IMC market trades CSV** (``trades_round_*_day_*.csv``): the
       buyer/seller fields are typically all blank because the book is
       anonymized for the player. Returns ``unknown`` here; callers
       should use ``classify_side_by_fv`` for those rows.
    """
    buyer = trade.buyer or ""
    seller = trade.seller or ""
    if buyer == "" and seller != "":
        return "buy"
    if seller == "" and buyer != "":
        return "sell"
    if buyer != "" and seller != "":
        return "unknown"
    return "unknown"


def classify_side_by_fv(trade: TradeRow, server_fv: float) -> str:
    """Classify trade direction by comparing print price to server FV.

    Convention: a trade printed *above* server FV was a market buyer
    aggressing into the ask wall; a trade *below* server FV was a
    market seller hitting the bid wall. Trades exactly at FV are
    ambiguous and returned as 'unknown'.

    Used when buyer/seller fields are anonymized (the IMC market-trades
    CSV format).
    """
    if trade.price > server_fv:
        return "buy"
    if trade.price < server_fv:
        return "sell"
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

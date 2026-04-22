"""Diagnostic plots that mirror chrispyroberts's validation pack.

Each plot tests one specific claim about the calibration. Plots are
arranged from "most upstream" (FV process) to "most downstream"
(trade prints relative to fair) so that any disagreement points back
to the layer where the model breaks.

Plot inventory (per product, in order of dependency):

    1. fv_path                — recovered server fair value over time
    2. return_law             — Delta-FV histogram + Gaussian overlay
    3. local_volatility       — rolling sigma window
    4. variance_accumulation  — cumulative variance / linear ref
    5. quote_laws             — observed offset vs frac(FV) per band
    6. spread_distribution    — empirical top-of-book spread histogram
    7. trades_per_step        — count distribution + Poisson overlay
    8. gap_survival           — interarrival survival vs geometric
    9. trade_size_buy/sell    — empirical size histograms
   10. trade_location_buy/sell — (price - fv) histograms

All plots write PNGs into the supplied output directory. No state is
mutated; the caller controls the destination.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from src.analysis.calibration.types import (
    DepthBand,
    FactRow,
    FairValueFit,
    QuoteRule,
    TradeArrivalFit,
    TradePriceLocationFit,
    TradeRow,
    TradeSizeFit,
)


def render_all_plots(
    *,
    facts: Sequence[FactRow],
    trades: Sequence[TradeRow],
    fair: FairValueFit,
    bands: Sequence[DepthBand],
    rules: Sequence[QuoteRule],
    arrivals: TradeArrivalFit,
    sizes_buy: TradeSizeFit,
    sizes_sell: TradeSizeFit,
    locations_buy: TradePriceLocationFit,
    locations_sell: TradePriceLocationFit,
    out_dir: Path,
    product: str,
) -> None:
    """Render the full validation pack to ``out_dir``.

    Imports matplotlib lazily so the rest of the calibration package
    can be used in headless / non-plotting contexts.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = product.lower()

    _plot_fv_path(facts, plt=plt, fair=fair).savefig(
        out_dir / f"{prefix}_01_fv_path.png", dpi=120, bbox_inches="tight"
    )
    _plot_return_law(facts, plt=plt, fair=fair).savefig(
        out_dir / f"{prefix}_02_return_law.png", dpi=120, bbox_inches="tight"
    )
    _plot_local_vol(facts, plt=plt).savefig(
        out_dir / f"{prefix}_03_local_volatility.png", dpi=120, bbox_inches="tight"
    )
    _plot_variance_accumulation(facts, plt=plt, fair=fair).savefig(
        out_dir / f"{prefix}_04_variance_accumulation.png",
        dpi=120,
        bbox_inches="tight",
    )
    _plot_quote_laws(facts, plt=plt, bands=bands, rules=rules).savefig(
        out_dir / f"{prefix}_05_quote_laws.png", dpi=120, bbox_inches="tight"
    )
    _plot_spread_distribution(facts, plt=plt).savefig(
        out_dir / f"{prefix}_06_spread_distribution.png",
        dpi=120,
        bbox_inches="tight",
    )
    _plot_trades_per_step(facts, trades, plt=plt, arrivals=arrivals).savefig(
        out_dir / f"{prefix}_07_trades_per_step.png",
        dpi=120,
        bbox_inches="tight",
    )
    _plot_gap_survival(facts, trades, plt=plt, arrivals=arrivals).savefig(
        out_dir / f"{prefix}_08_gap_survival.png", dpi=120, bbox_inches="tight"
    )
    _plot_trade_sizes(sizes_buy, sizes_sell, plt=plt).savefig(
        out_dir / f"{prefix}_09_trade_sizes.png", dpi=120, bbox_inches="tight"
    )
    _plot_trade_locations(locations_buy, locations_sell, plt=plt).savefig(
        out_dir / f"{prefix}_10_trade_locations.png",
        dpi=120,
        bbox_inches="tight",
    )
    plt.close("all")


# ----------------------------------------------------------- plot funcs


def _plot_fv_path(
    facts: Sequence[FactRow], *, plt, fair: FairValueFit
):
    fig, ax = plt.subplots(figsize=(10, 4))
    ts = [f.timestamp for f in facts]
    fv = [f.server_fv for f in facts]
    ax.plot(ts, fv, linewidth=0.8, color="C0")
    ax.set_title(
        f"Recovered server fair value (sigma={fair.sigma:.4f}, "
        f"phi={fair.ar1_phi:+.3f}+/-{fair.ar1_phi_se:.3f})"
    )
    ax.set_xlabel("timestamp")
    ax.set_ylabel("server_fv")
    ax.grid(True, alpha=0.3)
    return fig


def _plot_return_law(
    facts: Sequence[FactRow], *, plt, fair: FairValueFit
):
    fv = np.asarray([f.server_fv for f in facts])
    returns = np.diff(fv)
    fig, ax = plt.subplots(figsize=(7, 4))
    if fair.sigma < 1e-9 or returns.min() == returns.max():
        # Degenerate case: FV is effectively constant. Just bar at zero.
        ax.bar([0.0], [1.0], width=0.5, color="C0", edgecolor="black")
        ax.set_title("Delta-FV return law (constant FV)")
        ax.set_xlim(-1, 1)
    else:
        bins = max(20, int(np.sqrt(len(returns))))
        ax.hist(
            returns, bins=bins, density=True, alpha=0.6, color="C0",
            edgecolor="black", label="empirical",
        )
        xs = np.linspace(returns.min(), returns.max(), 200)
        pdf = (
            1.0
            / (fair.sigma * math.sqrt(2 * math.pi))
            * np.exp(-0.5 * (xs / fair.sigma) ** 2)
        )
        ax.plot(
            xs, pdf, color="C3", linewidth=2,
            label=f"N(0, {fair.sigma:.3f})",
        )
        ax.set_title("Delta-FV return law")
        ax.legend()
    ax.set_xlabel("Delta server_fv")
    ax.set_ylabel("density")
    ax.grid(True, alpha=0.3)
    return fig


def _plot_local_vol(facts: Sequence[FactRow], *, plt, window: int = 400):
    fv = np.asarray([f.server_fv for f in facts])
    returns = np.diff(fv)
    if len(returns) < window:
        window = max(2, len(returns) // 4)
    fig, ax = plt.subplots(figsize=(10, 4))
    if returns.min() == returns.max():
        ax.text(
            0.5, 0.5, "constant FV",
            ha="center", va="center", transform=ax.transAxes,
        )
    else:
        rolling = np.array([
            np.std(returns[max(0, i - window) : i], ddof=1)
            if i >= 2
            else math.nan
            for i in range(1, len(returns) + 1)
        ])
        ax.plot(rolling, linewidth=0.8, color="C0")
    ax.set_title(f"Local volatility (rolling sigma, window={window})")
    ax.set_xlabel("step")
    ax.set_ylabel("sigma(Delta server_fv)")
    ax.grid(True, alpha=0.3)
    return fig


def _plot_variance_accumulation(
    facts: Sequence[FactRow], *, plt, fair: FairValueFit
):
    fv = np.asarray([f.server_fv for f in facts])
    returns = np.diff(fv)
    fig, ax = plt.subplots(figsize=(7, 4))
    cum_var = np.cumsum(returns**2)
    if cum_var.size == 0 or cum_var[-1] <= 0:
        ax.text(
            0.5, 0.5, "constant FV (no variance)",
            ha="center", va="center", transform=ax.transAxes,
        )
    else:
        cum_var_normalized = cum_var / cum_var[-1]
        linear = np.linspace(0, 1, len(cum_var_normalized))
        ax.plot(
            cum_var_normalized, linewidth=1.0, color="C0", label="empirical"
        )
        ax.plot(
            linear, linewidth=1.0, color="C3",
            linestyle="--", label="linear ref",
        )
        ax.legend()
    ax.set_title("Variance accumulation")
    ax.set_xlabel("step")
    ax.set_ylabel("fraction of realized variance")
    ax.grid(True, alpha=0.3)
    return fig


def _plot_quote_laws(
    facts: Sequence[FactRow],
    *,
    plt,
    bands: Sequence[DepthBand],
    rules: Sequence[QuoteRule],
):
    """Median observed (price - fv) as a function of frac(fv), per band."""
    fig, ax = plt.subplots(figsize=(8, 5))
    rule_by_band = {r.bot_name: r for r in rules}
    frac_bins = np.linspace(0, 1, 21)
    centers = 0.5 * (frac_bins[:-1] + frac_bins[1:])
    for band in bands:
        offsets_by_bin: list[list[float]] = [[] for _ in centers]
        for fact in facts:
            levels = fact.bids if band.side == "bid" else fact.asks
            for level in levels:
                offset = level.price - fact.server_fv
                if band.offset_min <= offset <= band.offset_max:
                    frac = fact.server_fv - math.floor(fact.server_fv)
                    idx = int(min(frac * (len(centers)), len(centers) - 1))
                    offsets_by_bin[idx].append(offset)
                    break
        medians = [
            float(np.median(b)) if b else math.nan for b in offsets_by_bin
        ]
        rule = rule_by_band.get(band.name)
        label = band.name
        if rule is not None and rule.match_rate > 0:
            label = (
                f"{band.name} ({rule.match_rate:.1%}: "
                f"{rule.round_fn}(fv{rule.shift:+.2f})"
                f"{rule.offset:+d})"
            )
        ax.plot(centers, medians, marker="o", label=label)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_title("Quote laws — observed offset vs fractional FV")
    ax.set_xlabel("frac(server_fv)")
    ax.set_ylabel("observed (price - server_fv)")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    return fig


def _plot_spread_distribution(facts: Sequence[FactRow], *, plt):
    spreads: list[int] = []
    for fact in facts:
        if fact.bids and fact.asks:
            spreads.append(fact.asks[0].price - fact.bids[0].price)
    fig, ax = plt.subplots(figsize=(7, 4))
    if spreads:
        arr = np.asarray(spreads)
        unique, counts = np.unique(arr, return_counts=True)
        ax.bar(unique, counts / counts.sum(), color="C0", edgecolor="black")
        ax.set_xticks(unique)
    ax.set_title("Top-of-book spread distribution")
    ax.set_xlabel("spread (ticks)")
    ax.set_ylabel("probability")
    ax.grid(True, alpha=0.3, axis="y")
    return fig


def _plot_trades_per_step(
    facts: Sequence[FactRow],
    trades: Sequence[TradeRow],
    *,
    plt,
    arrivals: TradeArrivalFit,
):
    timestamps = sorted({f.timestamp for f in facts})
    counts = {ts: 0 for ts in timestamps}
    for trade in trades:
        if trade.timestamp in counts:
            counts[trade.timestamp] += 1
    arr = np.asarray(list(counts.values()))
    max_count = max(int(arr.max()), 2)
    bins = np.arange(0, max_count + 2) - 0.5
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(
        arr, bins=bins, density=True, alpha=0.6, color="C0",
        edgecolor="black", label="empirical",
    )
    p = arrivals.p_active
    xs = np.arange(0, max_count + 1)
    poisson = np.exp(-p) * p**xs / np.array([math.factorial(int(k)) for k in xs])
    ax.plot(xs, poisson, "ro-", label=f"Poisson(lambda={p:.4f})")
    ax.set_title("Trades per step")
    ax.set_xlabel("count")
    ax.set_ylabel("probability")
    ax.legend()
    ax.grid(True, alpha=0.3)
    return fig


def _plot_gap_survival(
    facts: Sequence[FactRow],
    trades: Sequence[TradeRow],
    *,
    plt,
    arrivals: TradeArrivalFit,
):
    timestamps = sorted({f.timestamp for f in facts})
    idx_map = {ts: i for i, ts in enumerate(timestamps)}
    active_indices = sorted(
        idx_map[t.timestamp] for t in trades if t.timestamp in idx_map
    )
    if len(active_indices) < 2:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.text(
            0.5, 0.5, "insufficient trades for gap survival",
            ha="center", va="center", transform=ax.transAxes,
        )
        return fig
    gaps = np.diff(np.asarray(active_indices))
    sorted_gaps = np.sort(gaps)
    survival = 1.0 - np.arange(1, len(sorted_gaps) + 1) / len(sorted_gaps)
    p = arrivals.p_active
    geom = (1.0 - p) ** sorted_gaps
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.semilogy(sorted_gaps, survival, "k-", linewidth=1.0, label="empirical")
    ax.semilogy(
        sorted_gaps, geom, "b--", linewidth=1.0,
        label=f"geometric(p={p:.4f})",
    )
    ax.set_title(f"Active-timestamp gap survival (KS={arrivals.geometric_ks_stat:.3f})")
    ax.set_xlabel("gap in steps")
    ax.set_ylabel("P(gap >= x)")
    ax.legend()
    ax.grid(True, alpha=0.3, which="both")
    return fig


def _plot_trade_sizes(
    sizes_buy: TradeSizeFit, sizes_sell: TradeSizeFit, *, plt
):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, fit, title in (
        (axes[0], sizes_buy, "Buy trade size"),
        (axes[1], sizes_sell, "Sell trade size"),
    ):
        if fit.n_samples == 0:
            ax.text(
                0.5, 0.5, "no trades",
                ha="center", va="center", transform=ax.transAxes,
            )
        else:
            ax.bar(fit.sizes, fit.probabilities, color="C0", edgecolor="black")
            ax.set_xticks(fit.sizes)
        ax.set_title(f"{title} (n={fit.n_samples})")
        ax.set_xlabel("quantity")
        ax.set_ylabel("probability")
        ax.grid(True, alpha=0.3, axis="y")
    return fig


def _plot_trade_locations(
    loc_buy: TradePriceLocationFit, loc_sell: TradePriceLocationFit, *, plt
):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    for ax, fit, title in (
        (axes[0], loc_buy, "Buy"),
        (axes[1], loc_sell, "Sell"),
    ):
        if fit.n_samples == 0:
            ax.text(
                0.5, 0.5, "no trades",
                ha="center", va="center", transform=ax.transAxes,
            )
        else:
            edges = np.asarray(fit.bin_edges)
            counts = np.asarray(fit.counts)
            centers = 0.5 * (edges[:-1] + edges[1:])
            widths = np.diff(edges)
            total = counts.sum() or 1
            ax.bar(
                centers, counts / total, width=widths,
                color="C0", edgecolor="black", align="center",
            )
        ax.axvline(0, color="C3", linewidth=1, linestyle="--", alpha=0.6)
        ax.set_title(f"{title} trade price - fair (n={fit.n_samples})")
        ax.set_xlabel("price - server_fv")
        ax.set_ylabel("probability")
        ax.grid(True, alpha=0.3, axis="y")
    return fig

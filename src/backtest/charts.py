"""Chart generation for review packs.

Renders six PNG artifacts from a ``SimulationResult`` under a supplied
directory. Matplotlib is imported **lazily** inside the render
functions so the live Prosperity runtime (and any offline pipeline
that doesn't ask for charts) remains matplotlib-free.

All plots use the non-interactive ``Agg`` backend, pinned once at
module load time when matplotlib is actually imported. This keeps
tests headless on CI and on macOS without a display.

Design rules:

- One PNG per plotter, fixed 150 dpi, modest width so review packs
  stay small.
- Plotters are pure functions: they take the already-computed
  ``SimulationResult`` and a target ``Path``. They do not reach back
  into the simulator or read anything from disk.
- Products with no trades skip the trade-marker and markout plots.
- A total-PnL chart is always drawn, even if individual products
  have empty series, because the top-level PnL is the fastest thing
  to eyeball.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from src.backtest.metrics import ProductResult, SimulationResult, TradeRecord

CHART_DPI = 150
CHART_FIGSIZE = (9, 4)
MARKOUTS_FIGSIZE = (10, 3.2)
MAKER_TAKER_FIGSIZE = (8, 3.2)


def render_review_charts(
    result: SimulationResult,
    *,
    out_dir: Path | str,
    markout_horizons: Iterable[int] = (1, 5, 20),
) -> list[Path]:
    """Render the full review chart suite under ``out_dir``.

    Returns the list of files written. Missing data for a given
    product simply skips that chart; the caller can diff the returned
    list against a baseline if strict checking is required.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Total PnL chart is always attempted (even if one product is empty).
    total_path = out_path / "pnl_over_time_total.png"
    if render_total_pnl(result, total_path):
        written.append(total_path)

    for product, product_result in sorted(result.per_product.items()):
        pvf_path = out_path / f"price_vs_fair_{product}.png"
        if render_price_vs_fair(result, product, pvf_path):
            written.append(pvf_path)

        pnl_path = out_path / f"pnl_over_time_{product}.png"
        if render_pnl_over_time(result, product, pnl_path):
            written.append(pnl_path)

        pos_path = out_path / f"position_over_time_{product}.png"
        if render_position_over_time(result, product, product_result, pos_path):
            written.append(pos_path)

        if product_result.trade_count > 0:
            mt_path = out_path / f"maker_taker_{product}.png"
            if render_maker_taker(product_result, mt_path):
                written.append(mt_path)

            mk_path = out_path / f"markouts_{product}.png"
            if render_markouts(result, product, mk_path, horizons=tuple(markout_horizons)):
                written.append(mk_path)

    return written


# --------------------------------------------------------- individual plotters


def render_price_vs_fair(result: SimulationResult, product: str, out: Path) -> bool:
    plt = _plt()
    mid_series = result.mid_series.get(product, ())
    fv_series = result.fair_value_series.get(product, ())
    if not mid_series and not fv_series:
        return False

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE)
    if mid_series:
        ts = [ts for ts, _ in mid_series]
        mids = [mid for _, mid in mid_series]
        ax.plot(ts, mids, label="mid", color="#1f77b4", linewidth=1.2)
    if fv_series:
        fts = [ts for ts, _ in fv_series]
        fvs = [fv for _, fv in fv_series]
        ax.plot(fts, fvs, label="fair value", color="#ff7f0e", linewidth=1.0, alpha=0.85)

    taker_buys, taker_sells, maker_buys, maker_sells = _split_trades_by_side(
        [r for r in result.trade_records if r.product == product]
    )
    for records, marker, color, label, alpha in (
        (taker_buys, "^", "#2ca02c", "taker buy", 0.9),
        (taker_sells, "v", "#d62728", "taker sell", 0.9),
        (maker_buys, "^", "#2ca02c", "maker buy", 0.35),
        (maker_sells, "v", "#d62728", "maker sell", 0.35),
    ):
        if not records:
            continue
        xs = [r.fill_timestamp for r in records]
        ys = [r.price for r in records]
        sizes = [max(20, 10 * r.quantity) for r in records]
        ax.scatter(xs, ys, marker=marker, color=color, s=sizes, alpha=alpha, label=label)

    ax.set_title(f"{product} — price vs fair value")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("price")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    _save(fig, out)
    return True


def render_pnl_over_time(result: SimulationResult, product: str, out: Path) -> bool:
    series = result.pnl_series.get(product, ())
    if not series:
        return False
    plt = _plt()
    fig, ax = plt.subplots(figsize=CHART_FIGSIZE)
    ts = [ts for ts, _ in series]
    pnl = [pnl for _, pnl in series]
    ax.plot(ts, pnl, color="#1f77b4", linewidth=1.3)
    ax.axhline(0, color="#888", linewidth=0.7, linestyle="--")
    ax.set_title(f"{product} — PnL over time")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("PnL (cash + position * mark)")
    ax.grid(alpha=0.2)
    _save(fig, out)
    return True


def render_position_over_time(
    result: SimulationResult,
    product: str,
    product_result: ProductResult,
    out: Path,
) -> bool:
    """Reconstruct per-step position by walking trade records.

    Trade records are ordered in simulation time, so a running
    cumulative sum of signed quantities is the position path.
    """
    del product_result  # reserved for future use (e.g., limit from config)
    series = result.pnl_series.get(product, ())
    if not series:
        return False

    plt = _plt()
    # Build a step-indexed position path.
    timestamps = [ts for ts, _ in series]
    record_by_ts: dict[int, int] = {}
    for record in result.trade_records:
        if record.product != product:
            continue
        delta = record.quantity if record.side == "buy" else -record.quantity
        record_by_ts[record.fill_timestamp] = record_by_ts.get(record.fill_timestamp, 0) + delta

    position = 0
    path: list[int] = []
    for ts in timestamps:
        position += record_by_ts.get(ts, 0)
        path.append(position)

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE)
    ax.plot(timestamps, path, color="#9467bd", linewidth=1.3)
    ax.axhline(0, color="#888", linewidth=0.7, linestyle="--")
    ax.set_title(f"{product} — position over time")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("position")
    ax.grid(alpha=0.2)
    _save(fig, out)
    return True


def render_total_pnl(result: SimulationResult, out: Path) -> bool:
    if not result.pnl_series:
        return False
    plt = _plt()
    # Union-of-timestamps per-step sum. Products with missing steps
    # inherit their last-seen value so the total line stays gap-free.
    all_timestamps = sorted(
        {ts for series in result.pnl_series.values() for ts, _ in series}
    )
    if not all_timestamps:
        return False

    last_value: dict[str, float] = dict.fromkeys(result.pnl_series, 0.0)
    per_product_by_ts: dict[str, dict[int, float]] = {
        product: dict(series) for product, series in result.pnl_series.items()
    }

    totals: list[float] = []
    for ts in all_timestamps:
        total = 0.0
        for product in result.pnl_series:
            if ts in per_product_by_ts[product]:
                last_value[product] = per_product_by_ts[product][ts]
            total += last_value[product]
        totals.append(total)

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE)
    ax.plot(all_timestamps, totals, color="#000", linewidth=1.4)
    ax.axhline(0, color="#888", linewidth=0.7, linestyle="--")
    ax.set_title("Total PnL over time")
    ax.set_xlabel("timestamp")
    ax.set_ylabel("PnL")
    ax.grid(alpha=0.2)
    _save(fig, out)
    return True


def render_maker_taker(product_result: ProductResult, out: Path) -> bool:
    total_qty = (
        product_result.taker_trade_quantity + product_result.maker_trade_quantity
    )
    if total_qty <= 0:
        return False
    plt = _plt()
    fig, ax = plt.subplots(figsize=MAKER_TAKER_FIGSIZE)
    labels = ["buy", "sell"]
    taker_side = [product_result.taker_trade_quantity, 0]
    maker_side = [product_result.maker_trade_quantity, 0]
    # We don't separately track buy-vs-sell by mode in aggregates; show
    # buy/sell totals stacked by mode instead, which is what the
    # chart in the plan described.
    buy_total = product_result.buy_trade_quantity
    sell_total = product_result.sell_trade_quantity
    taker_ratio = (
        product_result.taker_trade_quantity / total_qty if total_qty else 0.0
    )
    maker_ratio = (
        product_result.maker_trade_quantity / total_qty if total_qty else 0.0
    )
    taker_side = [buy_total * taker_ratio, sell_total * taker_ratio]
    maker_side = [buy_total * maker_ratio, sell_total * maker_ratio]

    ax.barh(labels, taker_side, color="#1f77b4", label="taker")
    ax.barh(labels, maker_side, left=taker_side, color="#ff7f0e", label="maker")
    ax.set_title(f"{product_result.product} — maker/taker decomposition")
    ax.set_xlabel("quantity")
    ax.legend(loc="best", fontsize=8)
    ax.grid(axis="x", alpha=0.2)
    _save(fig, out)
    return True


def render_markouts(
    result: SimulationResult,
    product: str,
    out: Path,
    *,
    horizons: tuple[int, ...],
) -> bool:
    """Three histograms side by side: per-trade markouts at each horizon."""
    mid_series = result.mid_series.get(product, ())
    if not mid_series:
        return False
    index_by_ts = {ts: idx for idx, (ts, _) in enumerate(mid_series)}
    records = [r for r in result.trade_records if r.product == product]
    if not records:
        return False

    per_horizon: dict[int, list[float]] = {h: [] for h in horizons}
    for record in records:
        fill_index = index_by_ts.get(record.fill_timestamp)
        if fill_index is None:
            continue
        sign = 1.0 if record.side == "buy" else -1.0
        for h in horizons:
            future_index = fill_index + h
            if future_index < 0 or future_index >= len(mid_series):
                continue
            future_mid = mid_series[future_index][1]
            per_horizon[h].append(sign * (future_mid - record.price))

    if not any(per_horizon.values()):
        return False

    plt = _plt()
    fig, axes = plt.subplots(1, len(horizons), figsize=MARKOUTS_FIGSIZE, sharey=True)
    if len(horizons) == 1:
        axes = [axes]
    for ax, h in zip(axes, horizons, strict=True):
        values = per_horizon.get(h, [])
        if values:
            ax.hist(values, bins=min(20, max(5, len(values) // 2)), color="#1f77b4", alpha=0.85)
            mean_val = sum(values) / len(values)
            ax.axvline(
                mean_val,
                color="#d62728",
                linestyle="--",
                linewidth=1.2,
                label=f"mean {mean_val:+.2f}",
            )
            ax.legend(fontsize=8, loc="best")
        ax.set_title(f"markout +{h}")
        ax.set_xlabel("p&l per share")
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("fills")
    fig.suptitle(f"{product} — markouts", y=1.02)
    _save(fig, out, bbox_inches="tight")
    return True


# ------------------------------------------------------------ helpers


def _split_trades_by_side(
    records: list[TradeRecord],
) -> tuple[
    list[TradeRecord],
    list[TradeRecord],
    list[TradeRecord],
    list[TradeRecord],
]:
    taker_buys: list[TradeRecord] = []
    taker_sells: list[TradeRecord] = []
    maker_buys: list[TradeRecord] = []
    maker_sells: list[TradeRecord] = []
    for record in records:
        if record.mode == "taker" and record.side == "buy":
            taker_buys.append(record)
        elif record.mode == "taker" and record.side == "sell":
            taker_sells.append(record)
        elif record.mode == "maker" and record.side == "buy":
            maker_buys.append(record)
        else:
            maker_sells.append(record)
    return taker_buys, taker_sells, maker_buys, maker_sells


def _plt():  # type: ignore[no-untyped-def]
    """Lazy matplotlib import pinned to the Agg backend."""
    import matplotlib

    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt

    return plt


def _save(fig, out: Path, **savefig_kwargs) -> None:  # type: ignore[no-untyped-def]
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=CHART_DPI, **savefig_kwargs)
    # Release the matplotlib figure handle to avoid leaking memory on
    # long review-pack runs.
    _plt().close(fig)

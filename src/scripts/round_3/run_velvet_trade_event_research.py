"""Market-trade event research for the R3 VELVET/options sleeve.

The passive-anchor official uploads showed that passive fills are real but too
small to be the main alpha source. Those fills are still useful labels: they
occur when visible market flow crosses the book. This harness asks whether
that flow is predictive enough to trade causally on the next book snapshot.

For each public Round 3 trade print we infer aggressor side from the local
book, then measure markouts and simulate simple event-follow / event-fade
rules with fixed holding horizons. The simulation intentionally enters on the
next timestamp after the print, not the same timestamp.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.scripts.round_3.run_velvet_new_family_research import (
    POS_LIMITS,
    PRODUCTS,
    TICKS_PER_DAY,
    UNDERLYING,
    WINDOW,
    BookPath,
    EvalResult,
    PortfolioSim,
    discover_data_dir,
    load_prices,
    make_paths,
    markdown_table,
    take_buys,
    take_sells,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_trade_event_research"

TRADED_PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)


@dataclass(frozen=True)
class Event:
    day: int
    timestamp: int
    product: str
    side: int  # +1 buyer-initiated / -1 seller-initiated
    price: float
    quantity: int
    bid: float
    ask: float
    mid: float
    side_quality: str


@dataclass(frozen=True)
class EventStrategyConfig:
    product: str
    mode: str
    hold_ticks: int
    max_order: int
    min_quantity: int = 1
    levels: int = 1
    side_filter: str = "both"

    @property
    def name(self) -> str:
        return (
            f"{self.product}_{self.mode}_h{self.hold_ticks}_mo{self.max_order}"
            f"_mq{self.min_quantity}_{self.side_filter}_l{self.levels}"
        )


def load_trades(data_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day in (0, 1, 2):
        path = data_dir / f"trades_round_3_day_{day}.csv"
        frame = pd.read_csv(path, sep=";")
        frame["day"] = day
        frames.append(frame)
    trades = pd.concat(frames, ignore_index=True)
    trades = trades[trades["symbol"].isin(TRADED_PRODUCTS)].copy()
    for column in ("day", "timestamp", "price", "quantity"):
        trades[column] = pd.to_numeric(trades[column], errors="coerce")
    trades = trades.dropna(subset=["day", "timestamp", "price", "quantity"])
    trades["day"] = trades["day"].astype(int)
    trades["timestamp"] = trades["timestamp"].astype(int)
    trades["quantity"] = trades["quantity"].astype(int)
    return trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)


def infer_events(prices: pd.DataFrame, trades: pd.DataFrame) -> list[Event]:
    book = prices[
        [
            "day",
            "timestamp",
            "product",
            "bid_price_1",
            "ask_price_1",
            "mid_price",
        ]
    ].copy()
    merged = trades.merge(
        book,
        left_on=["day", "timestamp", "symbol"],
        right_on=["day", "timestamp", "product"],
        how="left",
    )
    events: list[Event] = []
    for row in merged.itertuples(index=False):
        bid = float(row.bid_price_1)
        ask = float(row.ask_price_1)
        mid = float(row.mid_price)
        price = float(row.price)
        if not (math.isfinite(bid) and math.isfinite(ask) and math.isfinite(mid)):
            continue
        if price >= ask:
            side = 1
            quality = "at_or_above_ask"
        elif price <= bid:
            side = -1
            quality = "at_or_below_bid"
        elif price > mid:
            side = 1
            quality = "above_mid_inside"
        elif price < mid:
            side = -1
            quality = "below_mid_inside"
        else:
            continue
        events.append(
            Event(
                day=int(row.day),
                timestamp=int(row.timestamp),
                product=str(row.symbol),
                side=side,
                price=price,
                quantity=int(row.quantity),
                bid=bid,
                ask=ask,
                mid=mid,
                side_quality=quality,
            )
        )
    return events


def event_markout_summary(events: list[Event], paths: list[BookPath]) -> pd.DataFrame:
    path_by_day_full = {
        path.day: path
        for path in paths
        if path.start == 0 and path.end == TICKS_PER_DAY
    }
    rows: list[dict] = []
    horizons = (1000, 3000, 5000, 10000, 30000)
    for event in events:
        path = path_by_day_full.get(event.day)
        if path is None or event.product not in path.mid:
            continue
        idx = _index_for_timestamp(path, event.timestamp)
        if idx is None:
            continue
        row = {
            "day": event.day,
            "timestamp": event.timestamp,
            "product": event.product,
            "side": event.side,
            "price": event.price,
            "quantity": event.quantity,
            "quality": event.side_quality,
        }
        for horizon in horizons:
            future_idx = min(path.n - 1, idx + max(1, horizon // 100))
            future_mid = float(path.mid[event.product][future_idx])
            row[f"follow_edge_h{horizon}"] = (
                future_mid - event.price if event.side > 0 else event.price - future_mid
            )
            row[f"fade_edge_h{horizon}"] = -row[f"follow_edge_h{horizon}"]
        rows.append(row)
    detail = pd.DataFrame(rows)
    if detail.empty:
        return pd.DataFrame()
    summary_rows = []
    for (product, side, quality), group in detail.groupby(["product", "side", "quality"]):
        out = {
            "product": product,
            "side": int(side),
            "quality": quality,
            "events": int(len(group)),
            "qty": int(group["quantity"].sum()),
        }
        for horizon in horizons:
            edge = group[f"follow_edge_h{horizon}"]
            weights = group["quantity"]
            out[f"follow_mean_h{horizon}"] = float(edge.mean())
            out[f"follow_wmean_h{horizon}"] = float(np.average(edge, weights=weights))
            out[f"follow_positive_h{horizon}"] = int((edge > 0).sum())
        summary_rows.append(out)
    return pd.DataFrame(summary_rows).sort_values(["product", "side", "quality"])


def product_grid(product: str) -> list[EventStrategyConfig]:
    if product == UNDERLYING:
        orders = (8, 16, 32, 64)
    elif product in {"VEV_4000", "VEV_4500"}:
        orders = (2, 5, 10, 20)
    elif product in {"VEV_5000", "VEV_5100", "VEV_5200"}:
        orders = (2, 5, 10, 20, 40)
    else:
        orders = (2, 5, 10, 20)
    configs: list[EventStrategyConfig] = []
    for mode in ("follow", "fade"):
        for hold_ticks in (1000, 3000, 5000, 10000, 20000, 40000):
            for max_order in orders:
                for min_quantity in (1, 4, 8):
                    for side_filter in ("both", "buy", "sell"):
                        configs.append(
                            EventStrategyConfig(
                                product=product,
                                mode=mode,
                                hold_ticks=hold_ticks,
                                max_order=max_order,
                                min_quantity=min_quantity,
                                side_filter=side_filter,
                            )
                        )
    return configs


def evaluate_config(
    paths: list[BookPath],
    events_by_key: dict[tuple[int, int, str], list[Event]],
    config: EventStrategyConfig,
) -> list[EvalResult]:
    results: list[EvalResult] = []
    for path in paths:
        results.append(_evaluate_path(path, events_by_key, config))
    return results


def _evaluate_path(
    path: BookPath,
    events_by_key: dict[tuple[int, int, str], list[Event]],
    config: EventStrategyConfig,
) -> EvalResult:
    product = config.product
    sim = PortfolioSim((product,))
    exits: list[tuple[int, int, int]] = []  # exit_index, side_to_close, qty

    for index, timestamp in enumerate(path.timestamps):
        timestamp_int = int(timestamp)
        if product not in path.mid:
            continue

        if exits:
            remaining: list[tuple[int, int, int]] = []
            for exit_index, close_side, qty in exits:
                if index >= exit_index:
                    if close_side > 0:
                        take_buys(sim, path, product, index, 10**12, qty, levels=config.levels)
                    else:
                        take_sells(sim, path, product, index, -1, qty, levels=config.levels)
                else:
                    remaining.append((exit_index, close_side, qty))
            exits = remaining

        for event in events_by_key.get((path.day, timestamp_int, product), []):
            if event.quantity < config.min_quantity:
                continue
            if config.side_filter == "buy" and event.side < 0:
                continue
            if config.side_filter == "sell" and event.side > 0:
                continue
            entry_index = index + 1
            if entry_index >= path.n:
                continue
            trade_side = event.side if config.mode == "follow" else -event.side
            pos = sim.position.get(product, 0)
            if trade_side > 0:
                capacity = POS_LIMITS[product] - pos
                ask_qty = int(path.ask_volumes[product][entry_index][0])
                qty = min(config.max_order, event.quantity, capacity, ask_qty)
                if qty > 0:
                    filled = take_buys(
                        sim,
                        path,
                        product,
                        entry_index,
                        10**12,
                        qty,
                        levels=config.levels,
                    )
                    if filled > 0:
                        exits.append(
                            (
                                min(path.n - 1, entry_index + max(1, config.hold_ticks // 100)),
                                -1,
                                filled,
                            )
                        )
            else:
                capacity = POS_LIMITS[product] + pos
                bid_qty = int(path.bid_volumes[product][entry_index][0])
                qty = min(config.max_order, event.quantity, capacity, bid_qty)
                if qty > 0:
                    filled = take_sells(
                        sim,
                        path,
                        product,
                        entry_index,
                        -1,
                        qty,
                        levels=config.levels,
                    )
                    if filled > 0:
                        exits.append(
                            (
                                min(path.n - 1, entry_index + max(1, config.hold_ticks // 100)),
                                1,
                                filled,
                            )
                        )
        sim.observe(path, index)

    final_pnl = sim.pnl(path, path.n - 1) if path.n else 0.0
    return EvalResult(
        family="trade_event",
        name=config.name,
        day=path.day,
        start=path.start,
        end=path.end,
        pnl=float(final_pnl),
        max_drawdown=float(sim.max_drawdown),
        trade_count=sim.trade_count,
        abs_quantity=sim.abs_quantity,
        final_gross_position=abs(sim.position.get(product, 0)),
        final_positions_json=json.dumps({product: sim.position.get(product, 0)}, sort_keys=True),
    )


def summarize(results: list[EvalResult]) -> pd.DataFrame:
    df = pd.DataFrame([asdict(result) for result in results])
    windows = df[df["end"] - df["start"] == WINDOW]
    full = df[df["end"] - df["start"] == TICKS_PER_DAY]
    sim = df[(df["day"] == 2) & (df["start"] == 0) & (df["end"] == WINDOW)]
    rows = []
    for name, group in df.groupby("name", sort=False):
        w = windows[windows["name"] == name]
        f = full[full["name"] == name]
        s = sim[sim["name"] == name]
        if w.empty or f.empty or s.empty:
            continue
        product = str(name).split("_", 1)[0]
        if product == "VELVETFRUIT":
            product = UNDERLYING
        sim_row = s.iloc[0]
        row = {
            "product": product,
            "name": name,
            "simulator_pnl": float(sim_row["pnl"]),
            "simulator_drawdown": float(sim_row["max_drawdown"]),
            "full_mean": float(f["pnl"].mean()),
            "full_min": float(f["pnl"].min()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "window_p10": float(w["pnl"].quantile(0.10)),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(group["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "mean_final_gross_full": float(f["final_gross_position"].mean()),
        }
        row["robust_score"] = (
            0.25 * row["full_mean"]
            + 0.25 * row["full_min"]
            + 0.25 * row["window_mean"]
            + 1.5 * min(row["window_min"], 0.0)
            + 0.10 * row["simulator_pnl"]
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["product", "robust_score", "simulator_pnl"],
        ascending=[True, False, False],
    )


def combine_top(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for profile, selector in (
        ("robust", lambda g: g.sort_values("robust_score", ascending=False).iloc[0]),
        ("simulator", lambda g: g.sort_values("simulator_pnl", ascending=False).iloc[0]),
        ("positive", lambda g: g[g["positive_windows"] >= 24].sort_values("robust_score", ascending=False).iloc[0]
         if not g[g["positive_windows"] >= 24].empty else g.sort_values("robust_score", ascending=False).iloc[0]),
    ):
        selected = []
        for _product, group in summary.groupby("product", sort=False):
            selected.append(selector(group))
        combo = pd.DataFrame(selected)
        rows.append(
            {
                "profile": profile,
                "products": ",".join(combo["product"]),
                "simulator_pnl_sum": combo["simulator_pnl"].sum(),
                "full_mean_sum": combo["full_mean"].sum(),
                "full_min_naive_sum": combo["full_min"].sum(),
                "window_mean_sum": combo["window_mean"].sum(),
                "window_min_naive_sum": combo["window_min"].sum(),
                "positive_windows_sum": int(combo["positive_windows"].sum()),
                "configs_json": json.dumps(
                    {str(row["product"]): str(row["name"]) for _, row in combo.iterrows()},
                    sort_keys=True,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("simulator_pnl_sum", ascending=False)


def _index_for_timestamp(path: BookPath, timestamp: int) -> int | None:
    if path.n == 0:
        return None
    idx = int(np.searchsorted(path.timestamps, timestamp))
    if idx >= path.n or int(path.timestamps[idx]) != int(timestamp):
        return None
    return idx


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_prices(data_dir)
    trades = load_trades(data_dir)
    paths = make_paths(prices)
    events = infer_events(prices, trades)
    pd.DataFrame([asdict(event) for event in events]).to_csv(
        output_dir / "inferred_events.csv",
        index=False,
    )

    markouts = event_markout_summary(events, paths)
    markouts.to_csv(output_dir / "event_markout_summary.csv", index=False)

    events_by_key: dict[tuple[int, int, str], list[Event]] = {}
    for event in events:
        events_by_key.setdefault((event.day, event.timestamp, event.product), []).append(event)

    results: list[EvalResult] = []
    for product in TRADED_PRODUCTS:
        for config in product_grid(product):
            results.extend(evaluate_config(paths, events_by_key, config))

    result_df = pd.DataFrame([asdict(result) for result in results])
    result_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(results)
    summary.to_csv(output_dir / "summary.csv", index=False)
    combos = combine_top(summary)
    combos.to_csv(output_dir / "combo_summary.csv", index=False)

    per_product = pd.concat(
        [group.head(8) for _, group in summary.groupby("product", sort=False)]
    )
    cols = [
        "product",
        "name",
        "robust_score",
        "simulator_pnl",
        "full_mean",
        "full_min",
        "window_mean",
        "window_min",
        "positive_windows",
        "worst_drawdown",
        "mean_abs_qty_full",
    ]
    lines = [
        "# VELVET Trade Event Research",
        "",
        "## Event Markouts",
        "",
        markdown_table(markouts.head(80)) if not markouts.empty else "_No events._",
        "",
        "## Combined Profiles",
        "",
        markdown_table(combos),
        "",
        "## Per-Product Leaders",
        "",
        markdown_table(per_product[cols]),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(combos.to_string(index=False))
    print(per_product[cols].head(60).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

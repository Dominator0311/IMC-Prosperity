"""Passive maker proxy research for VELVET/options.

The public order-book markouts show strongly positive passive bid/ask markouts
and negative taker markouts. This harness uses historical market trades as a
conservative fill proxy:

* a posted bid fills when a same-timestamp market trade prints at or below it
* a posted ask fills when a same-timestamp market trade prints at or above it

This is not the official matching engine, but it is a useful directional check
before uploading passive diagnostic scripts.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.scripts.round_3.run_velvet_new_family_research import (
    POS_LIMITS,
    TICKS_PER_DAY,
    UNDERLYING,
    WINDOW,
    discover_data_dir,
    load_prices,
    markdown_table,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_passive_maker_research"

CORE_PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)
ALL_PRODUCTS: tuple[str, ...] = (
    "VEV_4000",
    "VEV_4500",
    *CORE_PRODUCTS,
)

ANCHORS: dict[str, float] = {
    UNDERLYING: 5257.0,
    "VEV_4000": 1250.0,
    "VEV_4500": 750.0,
    "VEV_5000": 262.5,
    "VEV_5100": 172.0,
    "VEV_5200": 99.0,
    "VEV_5300": 48.5,
    "VEV_5400": 15.0,
    "VEV_5500": 6.0,
}

DEFAULT_SIZES: dict[str, int] = {
    UNDERLYING: 25,
    "VEV_4000": 8,
    "VEV_4500": 8,
    "VEV_5000": 12,
    "VEV_5100": 16,
    "VEV_5200": 20,
    "VEV_5300": 20,
    "VEV_5400": 22,
    "VEV_5500": 22,
}


@dataclass(frozen=True)
class MakerConfig:
    products: tuple[str, ...]
    mode: str
    edge: float
    inventory_soft: int
    size_mult: int

    @property
    def name(self) -> str:
        products = "all" if set(self.products) == set(ALL_PRODUCTS) else "core"
        return (
            f"{products}_{self.mode}_edge{self.edge:g}"
            f"_soft{self.inventory_soft}_sm{self.size_mult}"
        )


@dataclass(frozen=True)
class PathResult:
    name: str
    day: int
    start: int
    end: int
    pnl: float
    max_drawdown: float
    trade_count: int
    abs_quantity: int
    final_positions_json: str


def load_trades(data_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day in (0, 1, 2):
        path = data_dir / f"trades_round_3_day_{day}.csv"
        frame = pd.read_csv(path, sep=";")
        frame["day"] = day
        frames.append(frame)
    trades = pd.concat(frames, ignore_index=True)
    trades = trades[trades["symbol"].isin(ALL_PRODUCTS)].copy()
    trades["timestamp"] = pd.to_numeric(trades["timestamp"], errors="coerce").astype(int)
    trades["price"] = pd.to_numeric(trades["price"], errors="coerce")
    trades["quantity"] = pd.to_numeric(trades["quantity"], errors="coerce").fillna(0).astype(int)
    return trades.sort_values(["day", "timestamp", "symbol"]).reset_index(drop=True)


def make_trade_lookup(trades: pd.DataFrame) -> dict[tuple[int, int, str], list[tuple[float, int]]]:
    lookup: dict[tuple[int, int, str], list[tuple[float, int]]] = {}
    for row in trades.itertuples(index=False):
        lookup.setdefault((int(row.day), int(row.timestamp), str(row.symbol)), []).append(
            (float(row.price), int(row.quantity))
        )
    return lookup


def quote_prices(row: object, product: str, config: MakerConfig) -> tuple[int | None, int | None]:
    best_bid = int(getattr(row, "bid_price_1"))
    best_ask = int(getattr(row, "ask_price_1"))
    if best_ask <= best_bid + 1:
        return None, None

    bid = best_bid + 1
    ask = best_ask - 1
    if bid >= ask:
        return None, None

    if config.mode == "mid":
        fair = float(getattr(row, "mid_price"))
    else:
        fair = ANCHORS[product]

    bid_ok = fair - bid >= config.edge
    ask_ok = ask - fair >= config.edge
    return (bid if bid_ok else None, ask if ask_ok else None)


def simulate_path(
    prices: pd.DataFrame,
    trade_lookup: dict[tuple[int, int, str], list[tuple[float, int]]],
    config: MakerConfig,
    *,
    day: int,
    start: int,
    end: int,
) -> PathResult:
    path = prices[
        (prices["day"] == day)
        & (prices["timestamp"] >= start)
        & (prices["timestamp"] < end)
    ]
    cash = {product: 0.0 for product in config.products}
    position = {product: 0 for product in config.products}
    latest_mid = {product: ANCHORS[product] for product in config.products}
    peak = -float("inf")
    max_drawdown = 0.0
    trade_count = 0
    abs_quantity = 0

    product_set = set(config.products)
    current_timestamp: int | None = None

    def mark_to_market() -> None:
        nonlocal peak, max_drawdown
        pnl_now = sum(cash[p] + position[p] * latest_mid[p] for p in config.products)
        peak = max(peak, pnl_now)
        max_drawdown = min(max_drawdown, pnl_now - peak)

    for row in path.itertuples(index=False):
        timestamp = int(row.timestamp)
        if current_timestamp is None:
            current_timestamp = timestamp
        elif timestamp != current_timestamp:
            mark_to_market()
            current_timestamp = timestamp

        product = str(row.product)
        if product not in product_set:
            continue
        latest_mid[product] = float(row.mid_price)
        bid, ask = quote_prices(row, product, config)

        size = DEFAULT_SIZES[product] * config.size_mult
        pos = position[product]
        if abs(pos) >= config.inventory_soft:
            if pos > 0:
                bid = None
            else:
                ask = None

        trades_here = trade_lookup.get((day, timestamp, product), [])
        if bid is not None and pos < POS_LIMITS[product]:
            qty_avail = sum(qty for price, qty in trades_here if price <= bid)
            qty = min(size, qty_avail, POS_LIMITS[product] - pos)
            if qty > 0:
                cash[product] -= qty * bid
                position[product] += qty
                trade_count += 1
                abs_quantity += qty

        pos = position[product]
        if ask is not None and pos > -POS_LIMITS[product]:
            qty_avail = sum(qty for price, qty in trades_here if price >= ask)
            qty = min(size, qty_avail, POS_LIMITS[product] + pos)
            if qty > 0:
                cash[product] += qty * ask
                position[product] -= qty
                trade_count += 1
                abs_quantity += qty

    mark_to_market()

    pnl = sum(cash[p] + position[p] * latest_mid[p] for p in config.products)
    return PathResult(
        name=config.name,
        day=day,
        start=start,
        end=end,
        pnl=float(pnl),
        max_drawdown=float(max_drawdown),
        trade_count=trade_count,
        abs_quantity=abs_quantity,
        final_positions_json=json.dumps(position, sort_keys=True),
    )


def build_configs() -> list[MakerConfig]:
    configs: list[MakerConfig] = []
    for products in (CORE_PRODUCTS, ALL_PRODUCTS):
        for mode in ("mid", "anchor"):
            for edge in (1.0, 2.0):
                configs.append(
                    MakerConfig(
                        products=tuple(products),
                        mode=mode,
                        edge=edge,
                        inventory_soft=160,
                        size_mult=1,
                    )
                )
    return configs


def build_expanded_configs() -> list[MakerConfig]:
    configs: list[MakerConfig] = []
    for products in (CORE_PRODUCTS, ALL_PRODUCTS):
        for mode in ("mid", "anchor"):
            for edge in (0.5, 1.0, 2.0, 4.0):
                for soft in (80, 160, 260):
                    for size_mult in (1, 2):
                        configs.append(
                            MakerConfig(
                                products=tuple(products),
                                mode=mode,
                                edge=edge,
                                inventory_soft=soft,
                                size_mult=size_mult,
                            )
                        )
    return configs


def summarize(results: list[PathResult]) -> pd.DataFrame:
    df = pd.DataFrame([asdict(result) for result in results])
    windows = df[df["end"] - df["start"] == WINDOW]
    full = df[df["end"] - df["start"] == TICKS_PER_DAY]
    sim = df[(df["day"] == 2) & (df["start"] == 0) & (df["end"] == WINDOW)]
    rows = []
    for name, _group in df.groupby("name", sort=False):
        w = windows[windows["name"] == name]
        f = full[full["name"] == name]
        s = sim[sim["name"] == name]
        if w.empty or f.empty or s.empty:
            continue
        sim_row = s.iloc[0]
        row = {
            "name": name,
            "simulator_pnl": float(sim_row["pnl"]),
            "simulator_drawdown": float(sim_row["max_drawdown"]),
            "full_mean": float(f["pnl"].mean()),
            "full_min": float(f["pnl"].min()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(df[df["name"] == name]["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "simulator_final_positions_json": str(sim_row["final_positions_json"]),
        }
        row["robust_score"] = (
            0.35 * row["full_mean"]
            + 0.35 * row["full_min"]
            + 0.20 * row["window_mean"]
            + 2.0 * min(row["window_min"], 0.0)
            + 0.10 * row["simulator_pnl"]
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["robust_score", "full_min", "window_min"], ascending=False
    ).reset_index(drop=True)


def run(data_dir: Path, output_dir: Path, *, expanded: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_prices(data_dir)
    trades = load_trades(data_dir)
    trade_lookup = make_trade_lookup(trades)
    configs = build_expanded_configs() if expanded else build_configs()

    results: list[PathResult] = []
    for config in configs:
        for day in (0, 1, 2):
            for start in range(0, TICKS_PER_DAY, WINDOW):
                results.append(
                    simulate_path(prices, trade_lookup, config, day=day, start=start, end=start + WINDOW)
                )
            results.append(
                simulate_path(prices, trade_lookup, config, day=day, start=0, end=TICKS_PER_DAY)
            )

    result_df = pd.DataFrame([asdict(result) for result in results])
    result_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(results)
    summary.to_csv(output_dir / "summary.csv", index=False)
    cols = [
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
        "# Passive Maker Proxy Research",
        "",
        "Fill proxy: historical same-timestamp prints crossing our quoted price.",
        "",
        markdown_table(summary[cols].head(40)),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(summary[cols].head(30).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--expanded", action="store_true")
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir), expanded=bool(args.expanded))


if __name__ == "__main__":
    main()

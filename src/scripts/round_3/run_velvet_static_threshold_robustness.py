"""Robustness sweep for static VELVET/options threshold sleeves.

The high-PnL upload probes showed that simple L1 threshold taking can dominate
the more delicate rolling-IV sleeve. This script stress-tests that family
against the relevant failure mode: overfitting one 100k simulator path.

It evaluates each product independently on:

* all 30 non-overlapping 100k windows from the three public 1M-tick days
* all three full 1M-tick days

Because Prosperity limits are per product and the official results showed
near-exact additivity across VELVET and vouchers, independent product ranking is
the cleanest first pass. Combined candidates are then assembled from selected
per-product configs.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT / "outputs" / "round_3" / "velvet_static_threshold_robustness"
)

UNDERLYING = "VELVETFRUIT_EXTRACT"
PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_4000",
    "VEV_4500",
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_6000",
    "VEV_6500",
)
POS_LIMITS = {UNDERLYING: 200, **{product: 300 for product in PRODUCTS if product != UNDERLYING}}
TICKS_PER_DAY = 1_000_000
WINDOW = 100_000


@dataclass(frozen=True)
class StaticConfig:
    product: str
    buy: int
    sell: int
    max_order: int

    @property
    def name(self) -> str:
        return f"{self.product}_b{self.buy}_s{self.sell}_mo{self.max_order}"


@dataclass(frozen=True)
class PathResult:
    product: str
    config: str
    day: int
    start: int
    end: int
    pnl: float
    max_drawdown: float
    trade_count: int
    abs_quantity: int
    final_position: int


@dataclass(frozen=True)
class PathSlice:
    day: int
    start: int
    end: int
    bid_prices: np.ndarray
    bid_volumes: np.ndarray
    ask_prices: np.ndarray
    ask_volumes: np.ndarray
    mids: np.ndarray


def discover_data_dir(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("ROUND3_DATA_DIR"):
        candidates.append(Path(os.environ["ROUND3_DATA_DIR"]).expanduser())
    candidates += [
        REPO_ROOT / "ROUND_3",
        REPO_ROOT.parent / "IMC" / "ROUND_3",
        Path("/Users/abhinavgupta/Desktop/IMC/ROUND_3"),
    ]
    for candidate in candidates:
        if (candidate / "prices_round_3_day_0.csv").exists():
            return candidate
    raise FileNotFoundError("Could not find Round 3 price CSVs.")


def load_prices(data_dir: Path) -> dict[str, pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    for day in (0, 1, 2):
        frame = pd.read_csv(data_dir / f"prices_round_3_day_{day}.csv", sep=";")
        frame["source_day"] = day
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)
    prices = prices[prices["product"].isin(PRODUCTS)].copy()
    for column in (
        "day",
        "timestamp",
        "bid_price_1",
        "bid_volume_1",
        "ask_price_1",
        "ask_volume_1",
        "mid_price",
    ):
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices = prices.dropna(
        subset=["day", "timestamp", "bid_price_1", "ask_price_1", "mid_price"]
    )
    prices["day"] = prices["day"].astype(int)
    prices["timestamp"] = prices["timestamp"].astype(int)
    prices["bid_volume_1"] = prices["bid_volume_1"].abs().fillna(0).astype(int)
    prices["ask_volume_1"] = prices["ask_volume_1"].abs().fillna(0).astype(int)

    by_product: dict[str, pd.DataFrame] = {}
    for product, group in prices.groupby("product", sort=False):
        by_product[product] = group.sort_values(["day", "timestamp"]).reset_index(drop=True)
    return by_product


def candidate_grid(product: str, data: pd.DataFrame) -> list[StaticConfig]:
    """Build a compact grid from observed L1 prices.

    The grid is deliberately quantile-based instead of hand-centered on the
    successful simulator upload. That keeps the sweep honest when public-day
    distributions drift by product.
    """
    bid_values = sorted(int(x) for x in data["bid_price_1"].dropna().unique())
    ask_values = sorted(int(x) for x in data["ask_price_1"].dropna().unique())
    if not bid_values or not ask_values:
        return []

    if product == UNDERLYING:
        buy_q = np.linspace(0.05, 0.48, 14)
        sell_q = np.linspace(0.52, 0.95, 14)
        max_orders = (40, 80)
    elif product in {"VEV_4000", "VEV_4500"}:
        buy_q = np.linspace(0.03, 0.42, 8)
        sell_q = np.linspace(0.58, 0.97, 8)
        max_orders = (10, 20)
    elif product in {"VEV_5000", "VEV_5100", "VEV_5200"}:
        buy_q = np.linspace(0.05, 0.50, 12)
        sell_q = np.linspace(0.50, 0.95, 12)
        max_orders = (20, 40)
    elif product in {"VEV_5300", "VEV_5400", "VEV_5500"}:
        buy_q = np.linspace(0.05, 0.55, 12)
        sell_q = np.linspace(0.45, 0.95, 12)
        max_orders = (20, 40)
    else:
        buy_q = np.linspace(0.01, 0.35, 6)
        sell_q = np.linspace(0.65, 0.99, 6)
        max_orders = (10, 20)

    buy_prices = sorted(set(int(round(np.quantile(ask_values, q))) for q in buy_q))
    sell_prices = sorted(set(int(round(np.quantile(bid_values, q))) for q in sell_q))

    configs: list[StaticConfig] = []
    for buy in buy_prices:
        for sell in sell_prices:
            if sell <= buy:
                continue
            for max_order in max_orders:
                configs.append(StaticConfig(product, buy, sell, max_order))

    probe_configs = {
        UNDERLYING: ((5245, 5255, 80), (5245, 5269, 80)),
        "VEV_5000": ((255, 270, 40),),
        "VEV_5100": ((165, 179, 40),),
        "VEV_5200": ((93, 105, 40),),
        "VEV_5300": ((45, 52, 20),),
        "VEV_5400": ((13, 17, 40),),
        "VEV_5500": ((5, 7, 40),),
    }
    seen = {(config.buy, config.sell, config.max_order) for config in configs}
    for buy, sell, max_order in probe_configs.get(product, ()):
        if sell > buy and (buy, sell, max_order) not in seen:
            configs.append(StaticConfig(product, buy, sell, max_order))
    return configs


def make_path_slices(data: pd.DataFrame) -> list[PathSlice]:
    paths: list[PathSlice] = []
    for day in (0, 1, 2):
        day_data = data[data["day"] == day]
        for start in range(0, TICKS_PER_DAY, WINDOW):
            paths.append(_make_path_slice(day_data, day=day, start=start, end=start + WINDOW))
        paths.append(_make_path_slice(day_data, day=day, start=0, end=TICKS_PER_DAY))
    return paths


def _make_path_slice(data: pd.DataFrame, *, day: int, start: int, end: int) -> PathSlice:
    path = data[(data["timestamp"] >= start) & (data["timestamp"] < end)]
    return PathSlice(
        day=day,
        start=start,
        end=end,
        bid_prices=path["bid_price_1"].to_numpy(dtype=np.int64),
        bid_volumes=path["bid_volume_1"].to_numpy(dtype=np.int64),
        ask_prices=path["ask_price_1"].to_numpy(dtype=np.int64),
        ask_volumes=path["ask_volume_1"].to_numpy(dtype=np.int64),
        mids=path["mid_price"].to_numpy(dtype=np.float64),
    )


def simulate(path: PathSlice, config: StaticConfig) -> PathResult:
    if len(path.mids) == 0:
        return PathResult(
            config.product,
            config.name,
            path.day,
            path.start,
            path.end,
            0.0,
            0.0,
            0,
            0,
            0,
        )

    cash = 0.0
    position = 0
    trade_count = 0
    abs_quantity = 0
    peak = -float("inf")
    max_drawdown = 0.0
    limit = POS_LIMITS[config.product]

    for bid_price, bid_volume, ask_price, ask_volume, mid in zip(
        path.bid_prices,
        path.bid_volumes,
        path.ask_prices,
        path.ask_volumes,
        path.mids,
        strict=True,
    ):
        ask_price = int(ask_price)
        ask_volume = int(ask_volume)
        bid_price = int(bid_price)
        bid_volume = int(bid_volume)

        if ask_price <= config.buy and position < limit:
            qty = min(config.max_order, ask_volume, limit - position)
            if qty > 0:
                cash -= qty * ask_price
                position += qty
                trade_count += 1
                abs_quantity += qty

        if bid_price >= config.sell and position > -limit:
            qty = min(config.max_order, bid_volume, limit + position)
            if qty > 0:
                cash += qty * bid_price
                position -= qty
                trade_count += 1
                abs_quantity += qty

        pnl = cash + position * float(mid)
        peak = max(peak, pnl)
        max_drawdown = min(max_drawdown, pnl - peak)

    final_mid = float(path.mids[-1])
    pnl = cash + position * final_mid
    return PathResult(
        product=config.product,
        config=config.name,
        day=path.day,
        start=path.start,
        end=path.end,
        pnl=pnl,
        max_drawdown=max_drawdown,
        trade_count=trade_count,
        abs_quantity=abs_quantity,
        final_position=position,
    )


def summarize(results: list[PathResult], configs: dict[str, StaticConfig]) -> pd.DataFrame:
    rows = [asdict(result) for result in results]
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    windows = df[df["end"] - df["start"] == WINDOW]
    full_days = df[df["end"] - df["start"] == TICKS_PER_DAY]

    window_summary = (
        windows.groupby(["product", "config"], as_index=False)
        .agg(
            window_mean=("pnl", "mean"),
            window_median=("pnl", "median"),
            window_min=("pnl", "min"),
            window_p10=("pnl", lambda s: float(np.quantile(s, 0.10))),
            positive_windows=("pnl", lambda s: int((s > 0).sum())),
            window_max_drawdown=("max_drawdown", "min"),
            window_mean_abs_qty=("abs_quantity", "mean"),
            window_mean_abs_final_pos=("final_position", lambda s: float(np.mean(np.abs(s)))),
        )
    )
    full_summary = (
        full_days.groupby(["product", "config"], as_index=False)
        .agg(
            full_mean=("pnl", "mean"),
            full_min=("pnl", "min"),
            full_max=("pnl", "max"),
            full_max_drawdown=("max_drawdown", "min"),
            full_mean_abs_qty=("abs_quantity", "mean"),
            full_mean_abs_final_pos=("final_position", lambda s: float(np.mean(np.abs(s)))),
        )
    )
    summary = window_summary.merge(full_summary, on=["product", "config"], how="inner")
    summary["buy"] = summary["config"].map(lambda name: configs[name].buy)
    summary["sell"] = summary["config"].map(lambda name: configs[name].sell)
    summary["max_order"] = summary["config"].map(lambda name: configs[name].max_order)
    summary["robust_score"] = (
        0.45 * summary["full_mean"]
        + 0.35 * summary["full_min"]
        + 0.20 * summary["window_mean"]
        + 2.0 * summary["window_min"].clip(upper=0)
    )
    return summary.sort_values(
        ["product", "robust_score", "full_min", "window_min"],
        ascending=[True, False, False, False],
    )


def select_configs(summary: pd.DataFrame) -> dict[str, dict[str, str]]:
    selections: dict[str, dict[str, str]] = {}
    for product, group in summary.groupby("product", sort=False):
        g = group.copy()
        positive = g[(g["full_min"] > 0) & (g["positive_windows"] >= 20)]
        if positive.empty:
            positive = g[g["full_min"] > 0]
        if positive.empty:
            positive = g

        robust = positive.sort_values(
            ["robust_score", "window_min", "positive_windows"], ascending=False
        ).iloc[0]
        aggressive = g.sort_values(
            ["full_mean", "full_min", "window_mean"], ascending=False
        ).iloc[0]
        defensive = positive.sort_values(
            ["window_min", "positive_windows", "full_min"], ascending=False
        ).iloc[0]
        selections[product] = {
            "robust": str(robust["config"]),
            "aggressive": str(aggressive["config"]),
            "defensive": str(defensive["config"]),
        }
    return selections


def build_combo_rows(summary: pd.DataFrame, selections: dict[str, dict[str, str]]) -> pd.DataFrame:
    rows = []
    for profile in ("robust", "aggressive", "defensive"):
        selected = []
        for product, product_selections in selections.items():
            config_name = product_selections[profile]
            row = summary[(summary["product"] == product) & (summary["config"] == config_name)].iloc[0]
            if profile != "aggressive" and row["full_min"] <= 0:
                continue
            if profile == "defensive" and row["positive_windows"] < 20:
                continue
            selected.append(row)

        if not selected:
            continue
        combo = pd.DataFrame(selected)
        rows.append(
            {
                "profile": profile,
                "products": ",".join(combo["product"]),
                "product_count": len(combo),
                "sum_window_mean": combo["window_mean"].sum(),
                "sum_window_min_naive": combo["window_min"].sum(),
                "sum_window_p10": combo["window_p10"].sum(),
                "sum_positive_windows": int(combo["positive_windows"].sum()),
                "sum_full_mean": combo["full_mean"].sum(),
                "sum_full_min_naive": combo["full_min"].sum(),
                "sum_robust_score": combo["robust_score"].sum(),
                "configs_json": json.dumps(
                    {
                        str(row["product"]): {
                            "buy": int(row["buy"]),
                            "sell": int(row["sell"]),
                            "max_order": int(row["max_order"]),
                        }
                        for _, row in combo.iterrows()
                    },
                    sort_keys=True,
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("sum_robust_score", ascending=False)


def write_report(
    *,
    output_dir: Path,
    data_dir: Path,
    summary: pd.DataFrame,
    combo_summary: pd.DataFrame,
) -> None:
    top_rows = []
    for product, group in summary.groupby("product", sort=False):
        top_rows.append(group.head(5))
    top = pd.concat(top_rows, ignore_index=True)

    lines = [
        "# VELVET Static Threshold Robustness",
        "",
        f"Data dir: `{data_dir}`",
        "",
        "Each candidate is evaluated on 30 public 100k windows and 3 full 1M days.",
        "The `robust_score` intentionally penalizes negative 100k windows while still",
        "giving most weight to full-day performance, since the final run is 1M ticks.",
        "",
        "## Combined Profiles",
        "",
        markdown_table(combo_summary),
        "",
        "## Per-Product Top 5",
        "",
        markdown_table(
            top[
                [
                    "product",
                    "buy",
                    "sell",
                    "max_order",
                    "robust_score",
                    "full_mean",
                    "full_min",
                    "window_mean",
                    "window_min",
                    "positive_windows",
                    "full_mean_abs_final_pos",
                ]
            ]
        ),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    display = df.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.3f}")
    headers = [str(column) for column in display.columns]
    rows = [[str(value) for value in row] for row in display.to_numpy()]
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    def format_line(values: Iterable[str]) -> str:
        cells = list(values)
        return "| " + " | ".join(
            cells[index].ljust(widths[index]) for index in range(len(widths))
        ) + " |"

    separator = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([format_line(headers), separator, *(format_line(row) for row in rows)])


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices_by_product = load_prices(data_dir)

    all_results: list[PathResult] = []
    config_by_name: dict[str, StaticConfig] = {}
    for product in PRODUCTS:
        data = prices_by_product.get(product)
        if data is None or data.empty:
            continue
        configs = candidate_grid(product, data)
        paths = make_path_slices(data)
        for config in configs:
            config_by_name[config.name] = config
            for path in paths:
                all_results.append(simulate(path, config))

    pd.DataFrame([asdict(result) for result in all_results]).to_csv(
        output_dir / "path_results.csv", index=False
    )
    summary = summarize(all_results, config_by_name)
    summary.to_csv(output_dir / "product_summary.csv", index=False)
    selections = select_configs(summary)
    (output_dir / "selections.json").write_text(json.dumps(selections, indent=2, sort_keys=True) + "\n")
    combo_summary = build_combo_rows(summary, selections)
    combo_summary.to_csv(output_dir / "combo_summary.csv", index=False)
    write_report(
        output_dir=output_dir,
        data_dir=data_dir,
        summary=summary,
        combo_summary=combo_summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

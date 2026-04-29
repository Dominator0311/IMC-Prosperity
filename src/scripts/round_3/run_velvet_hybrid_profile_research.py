"""Evaluate static/hybrid VELVET option profiles for simulator versus final.

The official 100k upload results calibrate very closely to the local day-2
first-100k replay, while the actual competition run is expected to be much
longer. This harness separates those objectives:

* 100k simulator score proxy: day 2, timestamps [0, 100k)
* 1M final proxy: all three public full days
* cross-window sanity: all thirty public 100k windows

It compares the high-scoring old static core, robust core/all profiles, and
simple timestamp hybrids that begin with old static then switch into robust.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_hybrid_profile_research"

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
)
POS_LIMITS = {UNDERLYING: 200, **{product: 300 for product in PRODUCTS if product != UNDERLYING}}
TICKS_PER_DAY = 1_000_000
WINDOW = 100_000


@dataclass(frozen=True)
class StaticRule:
    buy: int
    sell: int
    max_order: int


@dataclass(frozen=True)
class Profile:
    name: str
    early: dict[str, StaticRule]
    late: dict[str, StaticRule] | None = None
    switch_timestamp: int | None = None
    flatten_start: int | None = None
    window_reset_clock: bool = False


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
    final_gross_position: int
    final_positions_json: str


OLD_CORE = {
    UNDERLYING: StaticRule(5245, 5269, 80),
    "VEV_5000": StaticRule(255, 270, 40),
    "VEV_5100": StaticRule(165, 179, 40),
    "VEV_5200": StaticRule(93, 105, 40),
    "VEV_5300": StaticRule(45, 52, 20),
    "VEV_5400": StaticRule(13, 17, 40),
    "VEV_5500": StaticRule(5, 7, 40),
}

ROBUST_CORE = {
    UNDERLYING: StaticRule(5246, 5272, 80),
    "VEV_5000": StaticRule(241, 273, 20),
    "VEV_5100": StaticRule(154, 183, 40),
    "VEV_5200": StaticRule(92, 106, 40),
    "VEV_5300": StaticRule(44, 52, 40),
    "VEV_5400": StaticRule(15, 17, 40),
    "VEV_5500": StaticRule(4, 11, 20),
}

ROBUST_ALL = {
    **ROBUST_CORE,
    "VEV_4000": StaticRule(1233, 1263, 20),
    "VEV_4500": StaticRule(732, 766, 20),
}

AGGRESSIVE_ALL = {
    UNDERLYING: StaticRule(5246, 5272, 40),
    "VEV_4000": StaticRule(1233, 1263, 10),
    "VEV_4500": StaticRule(732, 766, 20),
    "VEV_5000": StaticRule(241, 273, 20),
    "VEV_5100": StaticRule(164, 183, 40),
    "VEV_5200": StaticRule(93, 105, 40),
    "VEV_5300": StaticRule(45, 52, 40),
    "VEV_5400": StaticRule(15, 18, 40),
    "VEV_5500": StaticRule(7, 8, 40),
}


def discover_data_dir(explicit: str | None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("ROUND3_DATA_DIR"):
        candidates.append(Path(os.environ["ROUND3_DATA_DIR"]).expanduser())
    candidates += [
        REPO_ROOT / "data/raw/round_3",
        REPO_ROOT.parent / "IMC" / "data/raw/round_3",
        Path("/Users/abhinavgupta/Desktop/IMC/data/raw/round_3"),
    ]
    for candidate in candidates:
        if (candidate / "prices_round_3_day_0.csv").exists():
            return candidate
    raise FileNotFoundError("Could not find Round 3 price CSVs.")


def load_prices(data_dir: Path) -> pd.DataFrame:
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
    return prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)


def make_profiles() -> list[Profile]:
    profiles = [
        Profile("old_core", OLD_CORE),
        Profile("robust_core_flat980", ROBUST_CORE, flatten_start=980_000),
        Profile("robust_all_flat980", ROBUST_ALL, flatten_start=980_000),
        Profile("aggressive_all_flat980", AGGRESSIVE_ALL, flatten_start=980_000),
    ]
    for switch in (50_000, 100_000, 200_000, 400_000):
        profiles.append(
            Profile(
                f"old_to_robust_core_s{switch}_flat980",
                OLD_CORE,
                ROBUST_CORE,
                switch_timestamp=switch,
                flatten_start=980_000,
            )
        )
        profiles.append(
            Profile(
                f"old_to_robust_all_s{switch}_flat980",
                OLD_CORE,
                ROBUST_ALL,
                switch_timestamp=switch,
                flatten_start=980_000,
            )
        )
        profiles.append(
            Profile(
                f"old_to_aggressive_all_s{switch}_flat980",
                OLD_CORE,
                AGGRESSIVE_ALL,
                switch_timestamp=switch,
                flatten_start=980_000,
            )
        )
    return profiles


def iter_paths(prices: pd.DataFrame) -> Iterable[tuple[int, int, int, pd.DataFrame]]:
    for day in (0, 1, 2):
        day_data = prices[prices["day"] == day]
        for start in range(0, TICKS_PER_DAY, WINDOW):
            yield day, start, start + WINDOW, day_data[
                (day_data["timestamp"] >= start) & (day_data["timestamp"] < start + WINDOW)
            ]
        yield day, 0, TICKS_PER_DAY, day_data


def simulate_path(profile: Profile, day: int, start: int, end: int, data: pd.DataFrame) -> PathResult:
    timestamps = np.array(sorted(data["timestamp"].unique()), dtype=np.int64)
    n = int(len(timestamps))
    by_product: dict[str, dict[str, np.ndarray]] = {}
    for product, group in data.groupby("product", sort=False):
        group = group.sort_values("timestamp")
        if len(group) != n:
            continue
        by_product[product] = {
            "bid": group["bid_price_1"].to_numpy(dtype=np.int64),
            "bid_volume": group["bid_volume_1"].to_numpy(dtype=np.int64),
            "ask": group["ask_price_1"].to_numpy(dtype=np.int64),
            "ask_volume": group["ask_volume_1"].to_numpy(dtype=np.int64),
            "mid": group["mid_price"].to_numpy(dtype=np.float64),
        }
    cash = {product: 0.0 for product in PRODUCTS}
    pos = {product: 0 for product in PRODUCTS}
    trade_count = 0
    abs_quantity = 0
    peak = -float("inf")
    max_drawdown = 0.0

    for index, timestamp_raw in enumerate(timestamps):
        timestamp = int(timestamp_raw)
        clock = timestamp - start if profile.window_reset_clock else timestamp
        active = profile.early
        if profile.late is not None and profile.switch_timestamp is not None:
            if clock >= profile.switch_timestamp:
                active = profile.late

        for product, rule in active.items():
            arrays = by_product.get(product)
            if arrays is None:
                continue
            bid_price = int(arrays["bid"][index])
            bid_volume = int(arrays["bid_volume"][index])
            ask_price = int(arrays["ask"][index])
            ask_volume = int(arrays["ask_volume"][index])
            limit = POS_LIMITS[product]

            if profile.flatten_start is not None and clock >= profile.flatten_start:
                if pos[product] > 0:
                    qty = min(rule.max_order, bid_volume, pos[product])
                    if qty > 0:
                        cash[product] += qty * bid_price
                        pos[product] -= qty
                        trade_count += 1
                        abs_quantity += qty
                elif pos[product] < 0:
                    qty = min(rule.max_order, ask_volume, -pos[product])
                    if qty > 0:
                        cash[product] -= qty * ask_price
                        pos[product] += qty
                        trade_count += 1
                        abs_quantity += qty
                continue

            if ask_price <= rule.buy and pos[product] < limit:
                qty = min(rule.max_order, ask_volume, limit - pos[product])
                if qty > 0:
                    cash[product] -= qty * ask_price
                    pos[product] += qty
                    trade_count += 1
                    abs_quantity += qty
            if bid_price >= rule.sell and pos[product] > -limit:
                qty = min(rule.max_order, bid_volume, limit + pos[product])
                if qty > 0:
                    cash[product] += qty * bid_price
                    pos[product] -= qty
                    trade_count += 1
                    abs_quantity += qty

        pnl = _pnl(cash, pos, by_product, index)
        peak = max(peak, pnl)
        max_drawdown = min(max_drawdown, pnl - peak)

    final_index = n - 1 if n else 0
    final_pnl = _pnl(cash, pos, by_product, final_index)
    live_positions = {product: qty for product, qty in pos.items() if qty}
    return PathResult(
        name=profile.name,
        day=day,
        start=start,
        end=end,
        pnl=float(final_pnl),
        max_drawdown=float(max_drawdown),
        trade_count=trade_count,
        abs_quantity=abs_quantity,
        final_gross_position=sum(abs(qty) for qty in pos.values()),
        final_positions_json=json.dumps(live_positions, sort_keys=True),
    )


def _pnl(
    cash: dict[str, float],
    pos: dict[str, int],
    by_product: dict[str, dict[str, np.ndarray]],
    index: int,
) -> float:
    total = 0.0
    for product, product_cash in cash.items():
        arrays = by_product.get(product)
        if arrays is None:
            continue
        total += product_cash + pos[product] * float(arrays["mid"][index])
    return total


def summarize(results: pd.DataFrame) -> pd.DataFrame:
    windows = results[results["end"] - results["start"] == WINDOW]
    full = results[results["end"] - results["start"] == TICKS_PER_DAY]
    sim = results[
        (results["day"] == 2)
        & (results["start"] == 0)
        & (results["end"] == WINDOW)
    ]
    rows = []
    for name, group in results.groupby("name", sort=False):
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
            "full_max": float(f["pnl"].max()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "window_p10": float(w["pnl"].quantile(0.10)),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(group["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "mean_final_gross_full": float(f["final_gross_position"].mean()),
            "simulator_final_positions_json": str(sim_row["final_positions_json"]),
        }
        row["final_score"] = (
            0.40 * row["full_mean"]
            + 0.35 * row["full_min"]
            + 0.15 * row["window_mean"]
            + 1.5 * min(row["window_min"], 0.0)
            + 0.05 * row["simulator_pnl"]
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["final_score", "full_min", "simulator_pnl"],
        ascending=False,
    )


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

    def line(values: Iterable[str]) -> str:
        return "| " + " | ".join(
            str(value).ljust(widths[index]) for index, value in enumerate(values)
        ) + " |"

    return "\n".join(
        [
            line(headers),
            "| " + " | ".join("-" * width for width in widths) + " |",
            *(line(row) for row in rows),
        ]
    )


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_prices(data_dir)
    profiles = make_profiles()
    results: list[PathResult] = []
    for profile in profiles:
        for day, start, end, path_data in iter_paths(prices):
            results.append(simulate_path(profile, day, start, end, path_data))
    result_df = pd.DataFrame([result.__dict__ for result in results])
    result_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(result_df)
    summary.to_csv(output_dir / "summary.csv", index=False)
    cols = [
        "name",
        "final_score",
        "simulator_pnl",
        "full_mean",
        "full_min",
        "window_mean",
        "window_min",
        "positive_windows",
        "worst_drawdown",
        "mean_abs_qty_full",
        "mean_final_gross_full",
        "simulator_final_positions_json",
    ]
    lines = [
        "# VELVET Hybrid Profile Research",
        "",
        f"Data dir: `{data_dir}`",
        "",
        markdown_table(summary[cols]),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(summary[cols].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

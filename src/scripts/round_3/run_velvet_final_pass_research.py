"""Final targeted robustness pass for the VELVET/options sleeve.

The earlier research found that broad families are mostly settled: simple
static taker thresholds dominate IV residuals, passive posting, and trade-print
logic under the calibrated local replay. This harness focuses the remaining
budget on the highest-value question for the 1M unseen run:

* which per-product static/scheduled rule survives full-day and 100k-window
  cross-slice tests?

The score intentionally underweights the day-2 first-100k simulator proxy. That
path is useful for official calibration, but optimizing to it directly is the
main overfit risk.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_final_pass_research"

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
class Rule:
    buy: int
    sell: int
    max_order: int


@dataclass(frozen=True)
class ProductPolicy:
    product: str
    name: str
    schedule: tuple[tuple[int, Rule], ...]
    flatten_start: int | None = 980_000


@dataclass(frozen=True)
class ProductResult:
    product: str
    policy: str
    day: int
    start: int
    end: int
    pnl: float
    max_drawdown: float
    abs_quantity: int
    final_position: int


@dataclass(frozen=True)
class PortfolioResult:
    name: str
    day: int
    start: int
    end: int
    pnl: float
    max_drawdown: float
    abs_quantity: int
    final_gross_position: int
    final_positions_json: str


OLD = {
    UNDERLYING: Rule(5245, 5269, 80),
    "VEV_5000": Rule(255, 270, 40),
    "VEV_5100": Rule(165, 179, 40),
    "VEV_5200": Rule(93, 105, 40),
    "VEV_5300": Rule(45, 52, 20),
    "VEV_5400": Rule(13, 17, 40),
    "VEV_5500": Rule(5, 7, 40),
}

AGGRESSIVE = {
    UNDERLYING: Rule(5246, 5272, 40),
    "VEV_4000": Rule(1233, 1263, 10),
    "VEV_4500": Rule(732, 766, 20),
    "VEV_5000": Rule(241, 273, 20),
    "VEV_5100": Rule(164, 183, 40),
    "VEV_5200": Rule(93, 105, 40),
    "VEV_5300": Rule(45, 52, 40),
    "VEV_5400": Rule(15, 18, 40),
    "VEV_5500": Rule(7, 8, 40),
}

ROBUST = {
    UNDERLYING: Rule(5246, 5272, 80),
    "VEV_4000": Rule(1233, 1263, 20),
    "VEV_4500": Rule(743, 766, 20),
    "VEV_5000": Rule(241, 273, 20),
    "VEV_5100": Rule(154, 183, 40),
    "VEV_5200": Rule(92, 106, 40),
    "VEV_5300": Rule(44, 52, 40),
    "VEV_5400": Rule(13, 19, 40),
    "VEV_5500": Rule(4, 11, 20),
}

ALT = {
    UNDERLYING: Rule(5229, 5272, 80),
    "VEV_4000": Rule(1239, 1263, 20),
    "VEV_4500": Rule(737, 766, 20),
    "VEV_5000": Rule(241, 270, 20),
    "VEV_5100": Rule(151, 183, 40),
    "VEV_5200": Rule(90, 106, 40),
    "VEV_5300": Rule(45, 53, 40),
    "VEV_5400": Rule(15, 17, 40),
    "VEV_5500": Rule(4, 9, 40),
}


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


def load_prices(data_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day in (0, 1, 2):
        frame = pd.read_csv(data_dir / f"prices_round_3_day_{day}.csv", sep=";")
        frame["day"] = day
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


def make_product_policies() -> list[ProductPolicy]:
    policies: list[ProductPolicy] = []
    for product in PRODUCTS:
        candidates: dict[str, Rule] = {}
        for label, source in (
            ("old", OLD),
            ("aggressive", AGGRESSIVE),
            ("robust", ROBUST),
            ("alt", ALT),
        ):
            if product in source:
                candidates[label] = source[product]
                policies.append(ProductPolicy(product, label, ((0, source[product]),)))

        for early_name, late_name in (("old", "aggressive"), ("old", "robust"), ("robust", "aggressive")):
            if early_name not in candidates or late_name not in candidates:
                continue
            for switch in (50_000, 100_000, 150_000, 200_000, 300_000):
                policies.append(
                    ProductPolicy(
                        product,
                        f"{early_name}_to_{late_name}_{switch // 1000}k",
                        ((0, candidates[early_name]), (switch, candidates[late_name])),
                    )
                )
    return policies


def iter_slices(prices: pd.DataFrame) -> Iterable[tuple[int, int, int, pd.DataFrame]]:
    for day in (0, 1, 2):
        day_data = prices[prices["day"] == day]
        for start in range(0, TICKS_PER_DAY, WINDOW):
            yield day, start, start + WINDOW, day_data[
                (day_data["timestamp"] >= start) & (day_data["timestamp"] < start + WINDOW)
            ]
        yield day, 0, TICKS_PER_DAY, day_data


def simulate_product(policy: ProductPolicy, data: pd.DataFrame, day: int, start: int, end: int) -> ProductResult:
    product_data = data[data["product"] == policy.product].sort_values("timestamp")
    if product_data.empty:
        return ProductResult(policy.product, policy.name, day, start, end, 0.0, 0.0, 0, 0)

    cash = 0.0
    position = 0
    abs_quantity = 0
    peak = -float("inf")
    max_drawdown = 0.0
    limit = POS_LIMITS[policy.product]

    for row in product_data.itertuples(index=False):
        timestamp = int(row.timestamp)
        rule = rule_at(policy.schedule, timestamp)
        bid_price = int(row.bid_price_1)
        ask_price = int(row.ask_price_1)
        bid_volume = int(row.bid_volume_1)
        ask_volume = int(row.ask_volume_1)

        if policy.flatten_start is not None and timestamp >= policy.flatten_start:
            if position > 0:
                qty = min(rule.max_order, bid_volume, position)
                if qty > 0:
                    cash += qty * bid_price
                    position -= qty
                    abs_quantity += qty
            elif position < 0:
                qty = min(rule.max_order, ask_volume, -position)
                if qty > 0:
                    cash -= qty * ask_price
                    position += qty
                    abs_quantity += qty
        else:
            if ask_price <= rule.buy and position < limit:
                qty = min(rule.max_order, ask_volume, limit - position)
                if qty > 0:
                    cash -= qty * ask_price
                    position += qty
                    abs_quantity += qty
            if bid_price >= rule.sell and position > -limit:
                qty = min(rule.max_order, bid_volume, limit + position)
                if qty > 0:
                    cash += qty * bid_price
                    position -= qty
                    abs_quantity += qty

        pnl = cash + position * float(row.mid_price)
        peak = max(peak, pnl)
        max_drawdown = min(max_drawdown, pnl - peak)

    final_mid = float(product_data.iloc[-1]["mid_price"])
    final_pnl = cash + position * final_mid
    return ProductResult(
        policy.product,
        policy.name,
        day,
        start,
        end,
        float(final_pnl),
        float(max_drawdown),
        abs_quantity,
        position,
    )


def rule_at(schedule: tuple[tuple[int, Rule], ...], timestamp: int) -> Rule:
    rule = schedule[0][1]
    for start, candidate in schedule:
        if timestamp >= start:
            rule = candidate
        else:
            break
    return rule


def summarize_product_results(results: pd.DataFrame) -> pd.DataFrame:
    windows = results[results["end"] - results["start"] == WINDOW]
    full = results[results["end"] - results["start"] == TICKS_PER_DAY]
    sim = results[
        (results["day"] == 2)
        & (results["start"] == 0)
        & (results["end"] == WINDOW)
    ]
    rows = []
    for (product, policy), group in results.groupby(["product", "policy"], sort=False):
        w = windows[(windows["product"] == product) & (windows["policy"] == policy)]
        f = full[(full["product"] == product) & (full["policy"] == policy)]
        s = sim[(sim["product"] == product) & (sim["policy"] == policy)]
        if w.empty or f.empty or s.empty:
            continue
        row = {
            "product": product,
            "policy": policy,
            "simulator_pnl": float(s.iloc[0]["pnl"]),
            "full_mean": float(f["pnl"].mean()),
            "full_min": float(f["pnl"].min()),
            "full_max": float(f["pnl"].max()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "window_p10": float(w["pnl"].quantile(0.10)),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(group["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "mean_abs_final_pos_full": float(f["final_position"].abs().mean()),
            "day0_full": float(f[f["day"] == 0].iloc[0]["pnl"]),
            "day1_full": float(f[f["day"] == 1].iloc[0]["pnl"]),
            "day2_full": float(f[f["day"] == 2].iloc[0]["pnl"]),
        }
        row["final_score"] = (
            0.50 * row["full_mean"]
            + 0.35 * row["full_min"]
            + 0.10 * row["window_mean"]
            + 1.0 * min(row["window_p10"], 0.0)
            + 0.02 * row["simulator_pnl"]
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["final_score", "full_min", "window_p10", "simulator_pnl"],
        ascending=False,
    )


def portfolio_candidates(product_summary: pd.DataFrame) -> list[dict[str, str]]:
    by_product = {
        product: group.head(6)["policy"].tolist()
        for product, group in product_summary.groupby("product", sort=False)
    }
    named = [
        {
            product: "aggressive"
            for product in PRODUCTS
            if "aggressive" in set(product_summary[product_summary["product"] == product]["policy"])
        },
        {
            product: "robust"
            for product in PRODUCTS
            if "robust" in set(product_summary[product_summary["product"] == product]["policy"])
        },
        {
            product: "old" if product in OLD else "aggressive"
            for product in PRODUCTS
        },
        {
            UNDERLYING: "aggressive",
            "VEV_4000": "aggressive",
            "VEV_4500": "aggressive",
            "VEV_5000": "old_to_aggressive_100k",
            "VEV_5100": "old_to_aggressive_150k",
            "VEV_5200": "aggressive",
            "VEV_5300": "old_to_aggressive_50k",
            "VEV_5400": "aggressive",
            "VEV_5500": "aggressive",
        },
    ]
    combos: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in named:
        key = json.dumps(candidate, sort_keys=True)
        if key not in seen:
            combos.append(candidate)
            seen.add(key)

    core_products = ["VELVETFRUIT_EXTRACT", "VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"]
    fixed_tail = {"VEV_4000": "aggressive", "VEV_4500": "aggressive", "VEV_5500": "aggressive"}
    for choices in itertools.product(*(by_product[p][:4] for p in core_products)):
        candidate = dict(zip(core_products, choices))
        candidate.update(fixed_tail)
        key = json.dumps(candidate, sort_keys=True)
        if key not in seen:
            combos.append(candidate)
            seen.add(key)
    return combos


def build_portfolios(
    product_results: pd.DataFrame,
    product_summary: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    lookup = {
        (str(row.product), str(row.policy), int(row.day), int(row.start), int(row.end)): (
            float(row.pnl),
            float(row.max_drawdown),
            int(row.abs_quantity),
            int(row.final_position),
        )
        for row in product_results.itertuples(index=False)
    }
    slice_keys = sorted(
        {
            (int(row.day), int(row.start), int(row.end))
            for row in product_results.itertuples(index=False)
        }
    )
    portfolios: list[PortfolioResult] = []
    for number, candidate in enumerate(portfolio_candidates(product_summary)):
        name = "combo_" + str(number).zfill(4)
        if number == 0:
            name = "aggressive_all_flat980"
        elif number == 1:
            name = "robust_all_flat980"
        elif number == 2:
            name = "old_core_plus_deep_aggressive_flat980"
        elif number == 3:
            name = "uploaded_product_switch_flat980"
        valid = True
        for day, start, end in slice_keys:
            pnl = 0.0
            dd = 0.0
            abs_qty = 0
            positions: dict[str, int] = {}
            for product, policy in candidate.items():
                row = lookup.get((product, policy, day, start, end))
                if row is None:
                    valid = False
                    break
                product_pnl, product_dd, product_abs_qty, position = row
                pnl += product_pnl
                dd += product_dd
                abs_qty += product_abs_qty
                if position:
                    positions[product] = position
            if not valid:
                break
            portfolios.append(
                PortfolioResult(
                    name,
                    int(day),
                    int(start),
                    int(end),
                    float(pnl),
                    float(dd),
                    abs_qty,
                    sum(abs(qty) for qty in positions.values()),
                    json.dumps(positions, sort_keys=True),
                )
            )
    portfolio_results = pd.DataFrame([row.__dict__ for row in portfolios])
    return portfolio_results, summarize_portfolios(portfolio_results)


def summarize_portfolios(results: pd.DataFrame) -> pd.DataFrame:
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
        row = {
            "name": name,
            "simulator_pnl": float(s.iloc[0]["pnl"]),
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
            "simulator_final_positions_json": str(s.iloc[0]["final_positions_json"]),
        }
        row["final_score"] = (
            0.50 * row["full_mean"]
            + 0.35 * row["full_min"]
            + 0.10 * row["window_mean"]
            + 1.2 * min(row["window_p10"], 0.0)
            + 0.02 * row["simulator_pnl"]
        )
        rows.append(row)
    return pd.DataFrame(rows).sort_values(
        ["final_score", "full_min", "window_p10", "simulator_pnl"],
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
    policies = make_product_policies()
    results: list[ProductResult] = []
    for policy in policies:
        for day, start, end, data in iter_slices(prices):
            results.append(simulate_product(policy, data, day, start, end))

    product_results = pd.DataFrame([row.__dict__ for row in results])
    product_results.to_csv(output_dir / "product_path_results.csv", index=False)
    product_summary = summarize_product_results(product_results)
    product_summary.to_csv(output_dir / "product_summary.csv", index=False)

    portfolio_results, portfolio_summary = build_portfolios(product_results, product_summary)
    portfolio_results.to_csv(output_dir / "portfolio_path_results.csv", index=False)
    portfolio_summary.to_csv(output_dir / "portfolio_summary.csv", index=False)

    product_cols = [
        "product",
        "policy",
        "final_score",
        "simulator_pnl",
        "full_mean",
        "full_min",
        "window_mean",
        "window_min",
        "window_p10",
        "positive_windows",
        "day0_full",
        "day1_full",
        "day2_full",
    ]
    portfolio_cols = [
        "name",
        "final_score",
        "simulator_pnl",
        "full_mean",
        "full_min",
        "window_mean",
        "window_min",
        "window_p10",
        "positive_windows",
        "mean_final_gross_full",
        "simulator_final_positions_json",
    ]
    lines = [
        "# VELVET Final Pass Research",
        "",
        f"Data dir: `{data_dir}`",
        "",
        "## Product Leaders",
        "",
        markdown_table(product_summary.groupby("product", sort=False).head(6)[product_cols]),
        "",
        "## Portfolio Leaders",
        "",
        markdown_table(portfolio_summary.head(30)[portfolio_cols]),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(portfolio_summary.head(20)[portfolio_cols].to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

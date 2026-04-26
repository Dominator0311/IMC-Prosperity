"""Anchored inventory-curve research for VELVET and core vouchers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.scripts.round_3.run_velvet_new_family_research import (
    POS_LIMITS,
    TICKS_PER_DAY,
    UNDERLYING,
    WINDOW,
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
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_anchor_curve_research"

CORE_PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)

BASE_ANCHORS: dict[str, float] = {
    UNDERLYING: 5257.0,
    "VEV_5000": 262.5,
    "VEV_5100": 172.0,
    "VEV_5200": 99.0,
    "VEV_5300": 48.5,
    "VEV_5400": 15.0,
    "VEV_5500": 6.0,
}


@dataclass(frozen=True)
class CurveConfig:
    product: str
    anchor: float
    half_band: float
    max_position: int
    max_order: int
    dead_zone: float
    levels: int = 1

    @property
    def name(self) -> str:
        anchor = str(self.anchor).replace(".", "p")
        band = str(self.half_band).replace(".", "p")
        dead = str(self.dead_zone).replace(".", "p")
        return (
            f"{self.product}_a{anchor}_b{band}_mp{self.max_position}"
            f"_mo{self.max_order}_dz{dead}_l{self.levels}"
        )


def target_for_price(config: CurveConfig, price: float) -> int:
    diff = price - config.anchor
    if abs(diff) <= config.dead_zone:
        return 0
    scaled = -diff / config.half_band * config.max_position
    return int(max(-config.max_position, min(config.max_position, round(scaled))))


def make_step(config: CurveConfig):
    def step(sim: PortfolioSim, path, index: int) -> None:
        product = config.product
        pos = sim.position.get(product, 0)
        best_ask = int(path.ask_prices[product][index][0])
        best_bid = int(path.bid_prices[product][index][0])

        buy_target = target_for_price(config, best_ask)
        if buy_target > pos:
            take_buys(
                sim,
                path,
                product,
                index,
                best_ask,
                min(config.max_order, buy_target - pos),
                levels=config.levels,
            )
            pos = sim.position.get(product, 0)

        sell_target = target_for_price(config, best_bid)
        if sell_target < pos:
            take_sells(
                sim,
                path,
                product,
                index,
                best_bid,
                min(config.max_order, pos - sell_target),
                levels=config.levels,
            )

    return step


def product_grid(product: str) -> list[CurveConfig]:
    base = BASE_ANCHORS[product]
    if product == UNDERLYING:
        anchor_offsets = (-6, 0, 6, 12)
        bands = (8, 12, 18, 28)
        max_positions = (120, 200)
        max_order = 80
        dead_zones = (0, 2)
    elif product == "VEV_5000":
        anchor_offsets = (-8, -3, 0, 4)
        bands = (4, 7, 11, 18)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 1)
    elif product == "VEV_5100":
        anchor_offsets = (-6, -2, 0, 4)
        bands = (3, 5, 8, 13)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 1)
    elif product == "VEV_5200":
        anchor_offsets = (-4, -1, 0, 3)
        bands = (2, 4, 6, 10)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 0.5)
    elif product == "VEV_5300":
        anchor_offsets = (-3, 0, 2, 4)
        bands = (1.5, 2.5, 4, 7)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 0.5)
    elif product == "VEV_5400":
        anchor_offsets = (-2, 0, 1, 3)
        bands = (0.8, 1.5, 2.5, 4)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 0.5)
    elif product == "VEV_5500":
        anchor_offsets = (-1, 0, 1, 2)
        bands = (0.8, 1.5, 2.5, 4)
        max_positions = (160, 300)
        max_order = 40
        dead_zones = (0, 0.5)
    else:
        raise ValueError(product)

    configs: list[CurveConfig] = []
    for offset in anchor_offsets:
        for band in bands:
            for max_position in max_positions:
                for dead_zone in dead_zones:
                    configs.append(
                        CurveConfig(
                            product=product,
                            anchor=base + offset,
                            half_band=float(band),
                            max_position=min(max_position, POS_LIMITS[product]),
                            max_order=max_order,
                            dead_zone=float(dead_zone),
                        )
                    )
    return configs


def evaluate(paths, config: CurveConfig) -> list[EvalResult]:
    results: list[EvalResult] = []
    step = make_step(config)
    for path in paths:
        sim = PortfolioSim((config.product,))
        for index in range(path.n):
            step(sim, path, index)
            sim.observe(path, index)
        pnl = sim.pnl(path, path.n - 1) if path.n else 0.0
        pos = sim.position.get(config.product, 0)
        results.append(
            EvalResult(
                family="anchor_curve",
                name=config.name,
                day=path.day,
                start=path.start,
                end=path.end,
                pnl=float(pnl),
                max_drawdown=float(sim.max_drawdown),
                trade_count=sim.trade_count,
                abs_quantity=sim.abs_quantity,
                final_gross_position=abs(pos),
                final_positions_json=json.dumps({config.product: pos}, sort_keys=True),
            )
        )
    return results


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
        sim_row = s.iloc[0]
        product = str(name).split("_a", 1)[0]
        row = {
            "product": product,
            "name": name,
            "simulator_pnl": float(sim_row["pnl"]),
            "simulator_drawdown": float(sim_row["max_drawdown"]),
            "full_mean": float(f["pnl"].mean()),
            "full_min": float(f["pnl"].min()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(group["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "mean_final_gross_full": float(f["final_gross_position"].mean()),
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
        ["product", "robust_score", "full_min", "window_min"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def combine_top(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    profiles = {
        "robust": ("robust_score", False),
        "simulator": ("simulator_pnl", False),
        "full_mean": ("full_mean", False),
        "window_min": ("window_min", False),
    }
    for profile, (column, ascending) in profiles.items():
        selected = []
        for _product, group in summary.groupby("product", sort=False):
            selected.append(group.sort_values(column, ascending=ascending).iloc[0])
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


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = make_paths(load_prices(data_dir))
    results: list[EvalResult] = []
    for product in CORE_PRODUCTS:
        for config in product_grid(product):
            results.extend(evaluate(paths, config))

    result_df = pd.DataFrame([asdict(result) for result in results])
    result_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(results)
    summary.to_csv(output_dir / "summary.csv", index=False)
    combos = combine_top(summary)
    combos.to_csv(output_dir / "combo_summary.csv", index=False)
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
        "mean_final_gross_full",
    ]
    top = pd.concat([group.head(8) for _, group in summary.groupby("product", sort=False)])
    lines = [
        "# Anchored Inventory-Curve Research",
        "",
        "## Combined Profiles",
        "",
        markdown_table(combos),
        "",
        "## Per-Product Leaders",
        "",
        markdown_table(top[cols]),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(combos.to_string(index=False))
    print(top[cols].head(50).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

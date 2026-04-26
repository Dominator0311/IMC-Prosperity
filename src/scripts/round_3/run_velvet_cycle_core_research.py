"""Stateful cycle research for VELVET and core vouchers.

Static thresholds captured a large early simulator move but leave a big gap to
the L1 oracle. This harness tests a simple causal cycle per product:

1. sell high into a short
2. cover near a lower band
3. optionally flip to a rebound long
4. exit the rebound when price recovers

Products are evaluated independently first, then combined additively.
"""

from __future__ import annotations

import argparse
import json
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
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_cycle_core_research"

CORE_PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)


@dataclass(frozen=True)
class CycleConfig:
    product: str
    short_entry: int
    cover: int
    rebound_target: int
    long_entry: int
    long_exit: int
    max_order: int
    levels: int = 1

    @property
    def name(self) -> str:
        return (
            f"{self.product}_se{self.short_entry}_cv{self.cover}"
            f"_rt{self.rebound_target}_le{self.long_entry}_lx{self.long_exit}"
            f"_mo{self.max_order}_l{self.levels}"
        )


def make_step(config: CycleConfig):
    def step(sim: PortfolioSim, path: BookPath, index: int) -> None:
        product = config.product
        pos = sim.position.get(product, 0)
        best_ask = int(path.ask_prices[product][index][0])
        best_bid = int(path.bid_prices[product][index][0])

        if pos < 0 and best_ask <= config.cover:
            target = config.rebound_target
            if target > pos:
                take_buys(
                    sim,
                    path,
                    product,
                    index,
                    config.cover,
                    min(config.max_order, target - pos),
                    levels=config.levels,
                )
            return

        if pos > 0 and best_bid >= config.long_exit:
            take_sells(
                sim,
                path,
                product,
                index,
                config.long_exit,
                min(config.max_order, pos),
                levels=config.levels,
            )
            pos = sim.position.get(product, 0)

        if best_bid >= config.short_entry:
            take_sells(
                sim,
                path,
                product,
                index,
                config.short_entry,
                config.max_order,
                levels=config.levels,
            )
        elif best_ask <= config.long_entry and pos < config.rebound_target:
            take_buys(
                sim,
                path,
                product,
                index,
                config.long_entry,
                min(config.max_order, config.rebound_target - pos),
                levels=config.levels,
            )

    return step


def evaluate_config(paths: list[BookPath], config: CycleConfig) -> list[EvalResult]:
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
                family="cycle_core",
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


def product_grid(product: str) -> list[CycleConfig]:
    limit = POS_LIMITS[product]
    if product == UNDERLYING:
        entries = (5265, 5269, 5273, 5277)
        gaps = (8, 14, 22, 34)
        exit_gaps = (12, 22, 36)
        targets = (0, 80, 160, 200)
        max_order = 80
    elif product == "VEV_5000":
        entries = (268, 272, 276, 282)
        gaps = (6, 12, 20, 30)
        exit_gaps = (8, 14, 24)
        targets = (0, 120, 240, 300)
        max_order = 40
    elif product == "VEV_5100":
        entries = (176, 180, 184, 190)
        gaps = (5, 10, 16, 24)
        exit_gaps = (6, 12, 20)
        targets = (0, 120, 240, 300)
        max_order = 40
    elif product == "VEV_5200":
        entries = (102, 106, 110, 114)
        gaps = (4, 8, 12, 18)
        exit_gaps = (5, 9, 15)
        targets = (0, 120, 240, 300)
        max_order = 40
    elif product == "VEV_5300":
        entries = (50, 52, 55, 58)
        gaps = (3, 6, 9, 13)
        exit_gaps = (3, 6, 10)
        targets = (0, 120, 240, 300)
        max_order = 40
    elif product == "VEV_5400":
        entries = (16, 17, 19, 22)
        gaps = (2, 3, 5, 8)
        exit_gaps = (2, 4, 7)
        targets = (0, 120, 240, 300)
        max_order = 40
    elif product == "VEV_5500":
        entries = (7, 8, 10, 12)
        gaps = (1, 2, 3, 5)
        exit_gaps = (1, 2, 4)
        targets = (0, 120, 240, 300)
        max_order = 40
    else:
        raise ValueError(product)

    configs: list[CycleConfig] = []
    for short_entry in entries:
        for gap in gaps:
            cover = short_entry - gap
            for target in targets:
                long_entry = cover - max(1, gap // 3)
                for exit_gap in exit_gaps:
                    long_exit = long_entry + exit_gap
                    configs.append(
                        CycleConfig(
                            product=product,
                            short_entry=short_entry,
                            cover=cover,
                            rebound_target=min(target, limit),
                            long_entry=long_entry,
                            long_exit=long_exit,
                            max_order=max_order,
                        )
                    )
    return configs


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
        product = str(name).split("_se", 1)[0]
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
    for profile, selector in (
        ("robust", lambda g: g.sort_values("robust_score", ascending=False).iloc[0]),
        ("simulator", lambda g: g.sort_values("simulator_pnl", ascending=False).iloc[0]),
        ("full_mean", lambda g: g.sort_values("full_mean", ascending=False).iloc[0]),
        (
            "positive",
            lambda g: g[g["positive_windows"] >= 24].sort_values("robust_score", ascending=False).iloc[0]
            if not g[g["positive_windows"] >= 24].empty
            else g.sort_values("robust_score", ascending=False).iloc[0],
        ),
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


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = make_paths(load_prices(data_dir))
    results: list[EvalResult] = []
    for product in CORE_PRODUCTS:
        for config in product_grid(product):
            results.extend(evaluate_config(paths, config))

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
        "# Stateful Cycle Core Research",
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
    print(top[cols].head(40).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

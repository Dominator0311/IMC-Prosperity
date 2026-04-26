"""Tradable call-spread no-arbitrage research for VELVET vouchers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.scripts.round_3.run_velvet_new_family_research import (
    POS_LIMITS,
    PRODUCTS,
    TICKS_PER_DAY,
    WINDOW,
    BookPath,
    EvalResult,
    PortfolioSim,
    discover_data_dir,
    load_prices,
    make_paths,
    markdown_table,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_call_spread_arb_research"

OPTION_PRODUCTS: tuple[str, ...] = (
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
STRIKES = {product: int(product.split("_")[1]) for product in OPTION_PRODUCTS}


@dataclass(frozen=True)
class SpreadConfig:
    pair_mode: str
    entry_edge: float
    close_edge: float
    max_order: int
    levels: int
    max_pair_inventory: int

    @property
    def name(self) -> str:
        return (
            f"{self.pair_mode}_entry{self.entry_edge:g}_close{self.close_edge:g}"
            f"_mo{self.max_order}_l{self.levels}_pi{self.max_pair_inventory}"
        )


def pairs_for_mode(mode: str) -> tuple[tuple[str, str], ...]:
    if mode == "adjacent":
        return tuple(zip(OPTION_PRODUCTS[:-1], OPTION_PRODUCTS[1:], strict=True))
    if mode == "core_adjacent":
        products = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
        return tuple(zip(products[:-1], products[1:], strict=True))
    if mode == "all":
        pairs: list[tuple[str, str]] = []
        for i, lower in enumerate(OPTION_PRODUCTS):
            for higher in OPTION_PRODUCTS[i + 1 :]:
                pairs.append((lower, higher))
        return tuple(pairs)
    raise ValueError(mode)


def best_bid(path: BookPath, product: str, index: int) -> tuple[int, int]:
    return int(path.bid_prices[product][index][0]), int(path.bid_volumes[product][index][0])


def best_ask(path: BookPath, product: str, index: int) -> tuple[int, int]:
    return int(path.ask_prices[product][index][0]), int(path.ask_volumes[product][index][0])


def simulate(path: BookPath, config: SpreadConfig) -> EvalResult:
    sim = PortfolioSim(OPTION_PRODUCTS)
    pair_inventory = {pair: 0 for pair in pairs_for_mode(config.pair_mode)}

    for index in range(path.n):
        opportunities = []
        for lower, higher in pair_inventory:
            lower_bid, lower_bid_vol = best_bid(path, lower, index)
            higher_ask, higher_ask_vol = best_ask(path, higher, index)
            gap = STRIKES[higher] - STRIKES[lower]
            edge = lower_bid - higher_ask - gap
            if edge >= config.entry_edge:
                opportunities.append((edge, lower, higher, lower_bid, higher_ask, lower_bid_vol, higher_ask_vol))

        for edge, lower, higher, lower_bid, higher_ask, lower_bid_vol, higher_ask_vol in sorted(
            opportunities, reverse=True
        ):
            pair = (lower, higher)
            room_pair = config.max_pair_inventory - pair_inventory[pair]
            qty = min(
                config.max_order,
                lower_bid_vol,
                higher_ask_vol,
                room_pair,
                POS_LIMITS[lower] + sim.position.get(lower, 0),
                POS_LIMITS[higher] - sim.position.get(higher, 0),
            )
            if qty <= 0:
                continue
            sim.sell(lower, lower_bid, qty)
            sim.buy(higher, higher_ask, qty)
            pair_inventory[pair] += qty

        # Opportunistically close when the same spread is cheap enough.
        for lower, higher in pair_inventory:
            inv = pair_inventory[(lower, higher)]
            if inv <= 0:
                continue
            lower_ask, lower_ask_vol = best_ask(path, lower, index)
            higher_bid, higher_bid_vol = best_bid(path, higher, index)
            gap = STRIKES[higher] - STRIKES[lower]
            close_value = lower_ask - higher_bid - gap
            if close_value > -config.close_edge:
                continue
            qty = min(config.max_order, lower_ask_vol, higher_bid_vol, inv)
            qty = min(qty, POS_LIMITS[lower] - sim.position.get(lower, 0))
            qty = min(qty, POS_LIMITS[higher] + sim.position.get(higher, 0))
            if qty <= 0:
                continue
            sim.buy(lower, lower_ask, qty)
            sim.sell(higher, higher_bid, qty)
            pair_inventory[(lower, higher)] -= qty

        sim.observe(path, index)

    pnl = sim.pnl(path, path.n - 1) if path.n else 0.0
    positions = {product: sim.position.get(product, 0) for product in OPTION_PRODUCTS}
    return EvalResult(
        family="call_spread_arb",
        name=config.name,
        day=path.day,
        start=path.start,
        end=path.end,
        pnl=float(pnl),
        max_drawdown=float(sim.max_drawdown),
        trade_count=sim.trade_count,
        abs_quantity=sim.abs_quantity,
        final_gross_position=sum(abs(value) for value in positions.values()),
        final_positions_json=json.dumps(positions, sort_keys=True),
    )


def build_configs() -> list[SpreadConfig]:
    configs: list[SpreadConfig] = []
    for mode in ("core_adjacent", "adjacent", "all"):
        for entry in (0.0, 0.5, 1.0, 2.0):
            for close in (0.5, 1.0, 2.0):
                for max_order in (20, 80):
                    configs.append(
                        SpreadConfig(
                            pair_mode=mode,
                            entry_edge=entry,
                            close_edge=close,
                            max_order=max_order,
                            levels=1,
                            max_pair_inventory=300,
                        )
                    )
    return configs


def summarize(results: list[EvalResult]) -> pd.DataFrame:
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
        ["robust_score", "full_min", "window_min"], ascending=False
    ).reset_index(drop=True)


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = make_paths(load_prices(data_dir))
    configs = build_configs()
    results: list[EvalResult] = []
    for config in configs:
        for path in paths:
            results.append(simulate(path, config))
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
        "mean_final_gross_full",
    ]
    (output_dir / "report.md").write_text(
        "# Call-Spread Arb Research\n\n" + markdown_table(summary[cols].head(40)) + "\n"
    )
    print(f"Wrote {output_dir}")
    print(summary[cols].head(30).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

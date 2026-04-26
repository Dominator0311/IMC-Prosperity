"""Cached IV-smile residual research for R3 VELVET vouchers.

The naive smile pass in ``run_velvet_new_family_research`` recomputes implied
vols for every parameter set. This version computes leave-one-out fair values
once per public path, then sweeps trading thresholds against those cached
fair-price arrays.
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

from src.options.bsm import BSMInputs, call_greeks, call_price, implied_vol
from src.scripts.round_3.run_velvet_new_family_research import (
    DEFAULT_OUTPUT_DIR,
    POS_LIMITS,
    TICKS_PER_DAY,
    UNDERLYING,
    WINDOW,
    BookPath,
    EvalResult,
    PortfolioSim,
    discover_data_dir,
    historical_tte,
    load_prices,
    make_paths,
    markdown_table,
    take_buys,
    take_sells,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_smile_cached_research"

FIT_PRODUCTS: tuple[str, ...] = (
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)
STRIKES: dict[str, int] = {product: int(product.split("_")[1]) for product in FIT_PRODUCTS}


@dataclass(frozen=True)
class SmileCache:
    fair: dict[str, np.ndarray]
    delta: dict[str, np.ndarray]


@dataclass(frozen=True)
class SmileConfig:
    traded: tuple[str, ...]
    max_position: int
    max_order: int
    entry_edge: float
    residual_scale: float
    hedge_delta: bool
    max_abs_delta: float
    levels: int

    @property
    def name(self) -> str:
        traded = "-".join(product.replace("VEV_", "") for product in self.traded)
        hedge = "hedge" if self.hedge_delta else "raw"
        return (
            f"tr{traded}_mp{self.max_position}_mo{self.max_order}"
            f"_e{self.entry_edge:g}_rs{self.residual_scale:g}_{hedge}_l{self.levels}"
        )


def precompute_smile(path: BookPath) -> SmileCache:
    fair = {product: np.full(path.n, np.nan, dtype=np.float64) for product in FIT_PRODUCTS}
    delta = {product: np.full(path.n, np.nan, dtype=np.float64) for product in FIT_PRODUCTS}
    for index in range(path.n):
        spot = float(path.mid[UNDERLYING][index])
        tte = historical_tte(path.day, int(path.timestamps[index]))
        ivs: dict[str, float] = {}
        ms: dict[str, float] = {}
        for product in FIT_PRODUCTS:
            mid = float(path.mid[product][index])
            strike = float(STRIKES[product])
            intrinsic = max(0.0, spot - strike)
            if mid - intrinsic < 0.5:
                continue
            iv = implied_vol(mid, spot=spot, strike=strike, time_to_expiry=tte, lo=0.001, hi=1.0)
            if iv is None or not (0.001 <= iv <= 0.50):
                continue
            ivs[product] = iv
            ms[product] = math.log(strike / spot) / math.sqrt(tte)

        for product in FIT_PRODUCTS:
            fit_products = [other for other in FIT_PRODUCTS if other != product and other in ivs]
            if len(fit_products) < 3:
                continue
            xs = np.array([ms[other] for other in fit_products], dtype=np.float64)
            ys = np.array([ivs[other] for other in fit_products], dtype=np.float64)
            degree = 2 if len(fit_products) >= 4 else 1
            try:
                coeff = np.polyfit(xs, ys, degree)
            except np.linalg.LinAlgError:
                continue
            strike = float(STRIKES[product])
            m = math.log(strike / spot) / math.sqrt(tte)
            fair_iv = float(np.polyval(coeff, m))
            if not (0.001 <= fair_iv <= 0.50):
                continue
            try:
                inputs = BSMInputs(
                    spot=spot,
                    strike=strike,
                    time_to_expiry=tte,
                    volatility=fair_iv,
                )
                fair_price = call_price(inputs)
                option_delta = call_greeks(inputs).delta
            except (ValueError, OverflowError, ZeroDivisionError):
                continue
            if math.isfinite(fair_price) and math.isfinite(option_delta):
                fair[product][index] = fair_price
                delta[product][index] = max(0.0, min(1.0, option_delta))
    return SmileCache(fair=fair, delta=delta)


def simulate_path(path: BookPath, cache: SmileCache, config: SmileConfig) -> EvalResult:
    products = (UNDERLYING, *config.traded) if config.hedge_delta else config.traded
    sim = PortfolioSim(products)
    for index in range(path.n):
        for product in config.traded:
            fair = float(cache.fair[product][index])
            if not math.isfinite(fair):
                continue
            mid = float(path.mid[product][index])
            signal = fair - mid
            if abs(signal) < config.entry_edge:
                continue
            raw_target = int(round(signal / config.residual_scale * config.max_position))
            target = max(-config.max_position, min(config.max_position, raw_target))
            current = sim.position.get(product, 0)
            desired = target - current
            if desired > 0:
                take_buys(
                    sim,
                    path,
                    product,
                    index,
                    fair - config.entry_edge,
                    min(config.max_order, desired),
                    levels=config.levels,
                )
            elif desired < 0:
                take_sells(
                    sim,
                    path,
                    product,
                    index,
                    fair + config.entry_edge,
                    min(config.max_order, -desired),
                    levels=config.levels,
                )
        if config.hedge_delta:
            hedge_delta(sim, path, cache, config, index)
        sim.observe(path, index)

    pnl = sim.pnl(path, path.n - 1) if path.n else 0.0
    positions = {product: sim.position.get(product, 0) for product in products}
    return EvalResult(
        family="smile_cached",
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


def hedge_delta(
    sim: PortfolioSim,
    path: BookPath,
    cache: SmileCache,
    config: SmileConfig,
    index: int,
) -> None:
    net_delta = float(sim.position.get(UNDERLYING, 0))
    for product in config.traded:
        option_delta = float(cache.delta[product][index])
        if math.isfinite(option_delta):
            net_delta += sim.position.get(product, 0) * option_delta
    if abs(net_delta) <= config.max_abs_delta:
        return
    if net_delta > 0:
        qty = int(math.ceil(net_delta - config.max_abs_delta))
        take_sells(sim, path, UNDERLYING, index, -1.0, min(config.max_order, qty), levels=config.levels)
    else:
        qty = int(math.ceil(-net_delta - config.max_abs_delta))
        take_buys(sim, path, UNDERLYING, index, 10**12, min(config.max_order, qty), levels=config.levels)


def summarize(results: list[EvalResult]) -> pd.DataFrame:
    df = pd.DataFrame([asdict(result) for result in results])
    if df.empty:
        return df
    windows = df[df["end"] - df["start"] == WINDOW]
    full = df[df["end"] - df["start"] == TICKS_PER_DAY]
    sim_rows = df[(df["day"] == 2) & (df["start"] == 0) & (df["end"] == WINDOW)]
    rows = []
    for name, _group in df.groupby("name", sort=False):
        w = windows[windows["name"] == name]
        f = full[full["name"] == name]
        s = sim_rows[sim_rows["name"] == name]
        if w.empty or f.empty:
            continue
        sim = s.iloc[0]
        row = {
            "family": "smile_cached",
            "name": name,
            "simulator_pnl": float(sim["pnl"]),
            "simulator_drawdown": float(sim["max_drawdown"]),
            "full_mean": float(f["pnl"].mean()),
            "full_min": float(f["pnl"].min()),
            "full_max": float(f["pnl"].max()),
            "window_mean": float(w["pnl"].mean()),
            "window_min": float(w["pnl"].min()),
            "window_p10": float(np.quantile(w["pnl"], 0.10)),
            "positive_windows": int((w["pnl"] > 0).sum()),
            "worst_drawdown": float(df[df["name"] == name]["max_drawdown"].min()),
            "mean_abs_qty_full": float(f["abs_quantity"].mean()),
            "mean_final_gross_full": float(f["final_gross_position"].mean()),
            "simulator_final_positions_json": str(sim["final_positions_json"]),
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


def build_configs() -> list[SmileConfig]:
    configs: list[SmileConfig] = []
    traded_sets = (("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"), FIT_PRODUCTS)
    for traded in traded_sets:
        for max_pos in (120, 300):
            for edge in (1.0, 2.5):
                for residual_scale in (4.0, 16.0):
                    for hedge in (False,):
                        configs.append(
                            SmileConfig(
                                traded=tuple(traded),
                                max_position=max_pos,
                                max_order=40,
                                entry_edge=edge,
                                residual_scale=residual_scale,
                                hedge_delta=hedge,
                                max_abs_delta=60.0,
                                levels=3,
                            )
                        )
    return configs


def quick_paths(paths: list[BookPath]) -> list[BookPath]:
    """Return simulator-equivalent window plus the three full public days."""
    selected = [
        path
        for path in paths
        if (path.day == 2 and path.start == 0 and path.end == WINDOW)
        or (path.start == 0 and path.end == TICKS_PER_DAY)
    ]
    return selected


def run(data_dir: Path, output_dir: Path, *, all_paths: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = make_paths(load_prices(data_dir))
    if not all_paths:
        paths = quick_paths(paths)
    caches = {index: precompute_smile(path) for index, path in enumerate(paths)}
    configs = build_configs()
    results: list[EvalResult] = []
    for config in configs:
        for index, path in enumerate(paths):
            results.append(simulate_path(path, caches[index], config))

    path_df = pd.DataFrame([asdict(result) for result in results])
    path_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(results)
    summary.to_csv(output_dir / "summary.csv", index=False)
    top_cols = [
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
    lines = [
        "# Cached IV-Smile Research",
        "",
        f"Data dir: `{data_dir}`",
        "",
        markdown_table(summary[top_cols].head(40)),
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(f"Wrote {output_dir}")
    print(summary[top_cols].head(30).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument("--all-paths", action="store_true")
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir), all_paths=bool(args.all_paths))


if __name__ == "__main__":
    main()

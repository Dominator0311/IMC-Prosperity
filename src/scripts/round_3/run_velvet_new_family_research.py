"""Research harness for VELVET/options non-static strategy families.

This script is intentionally independent from the live engines. The goal is
to test broad alpha families under the same simple replay assumptions used for
the calibrated static VELVET/options uploads:

* immediate taker fills against visible book levels
* hard per-product position limits
* final mark-to-mid for open inventory

Families covered:

1. static depth-taking variants (best level versus all visible levels)
2. deep-ITM vouchers as synthetic underlying exposure
3. leave-one-out volatility-smile residual scalping

The output is evidence for what to upload next, not proof of final robustness.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from src.options.bsm import BSMInputs, call_greeks, call_price, implied_vol

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_new_family_research"

UNDERLYING = "VELVETFRUIT_EXTRACT"
CORE_PRODUCTS: tuple[str, ...] = (
    UNDERLYING,
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
)
DEEP_PRODUCTS: tuple[str, ...] = ("VEV_4000", "VEV_4500")
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
PRODUCTS: tuple[str, ...] = (UNDERLYING, *OPTION_PRODUCTS)
STRIKES: dict[str, int] = {product: int(product.split("_")[1]) for product in OPTION_PRODUCTS}
POS_LIMITS: dict[str, int] = {UNDERLYING: 200, **{product: 300 for product in OPTION_PRODUCTS}}

TICKS_PER_DAY = 1_000_000
WINDOW = 100_000

OLD_STATIC: dict[str, dict[str, int]] = {
    UNDERLYING: {"buy": 5245, "sell": 5269, "max_order": 80},
    "VEV_5000": {"buy": 255, "sell": 270, "max_order": 40},
    "VEV_5100": {"buy": 165, "sell": 179, "max_order": 40},
    "VEV_5200": {"buy": 93, "sell": 105, "max_order": 40},
    "VEV_5300": {"buy": 45, "sell": 52, "max_order": 20},
    "VEV_5400": {"buy": 13, "sell": 17, "max_order": 40},
    "VEV_5500": {"buy": 5, "sell": 7, "max_order": 40},
}

ROBUST_CORE: dict[str, dict[str, int]] = {
    UNDERLYING: {"buy": 5246, "sell": 5272, "max_order": 80},
    "VEV_5000": {"buy": 241, "sell": 273, "max_order": 20},
    "VEV_5100": {"buy": 154, "sell": 183, "max_order": 40},
    "VEV_5200": {"buy": 92, "sell": 106, "max_order": 40},
    "VEV_5300": {"buy": 44, "sell": 52, "max_order": 40},
    "VEV_5400": {"buy": 15, "sell": 17, "max_order": 40},
    "VEV_5500": {"buy": 4, "sell": 11, "max_order": 20},
}


@dataclass(frozen=True)
class BookPath:
    day: int
    start: int
    end: int
    timestamps: np.ndarray
    mid: dict[str, np.ndarray]
    bid_prices: dict[str, np.ndarray]
    bid_volumes: dict[str, np.ndarray]
    ask_prices: dict[str, np.ndarray]
    ask_volumes: dict[str, np.ndarray]

    @property
    def n(self) -> int:
        return int(len(self.timestamps))


@dataclass(frozen=True)
class EvalResult:
    family: str
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


@dataclass(frozen=True)
class SummaryRow:
    family: str
    name: str
    window_mean: float
    window_min: float
    window_p10: float
    positive_windows: int
    full_mean: float
    full_min: float
    full_max: float
    worst_drawdown: float
    mean_abs_qty_full: float
    mean_final_gross_full: float
    simulator_pnl: float
    simulator_drawdown: float
    simulator_final_positions_json: str


class PortfolioSim:
    def __init__(self, products: Iterable[str]) -> None:
        self.cash: dict[str, float] = {product: 0.0 for product in products}
        self.position: dict[str, int] = {product: 0 for product in products}
        self.trade_count = 0
        self.abs_quantity = 0
        self.peak = -float("inf")
        self.max_drawdown = 0.0

    def buy(self, product: str, price: int, qty: int) -> int:
        if qty <= 0:
            return 0
        self.cash[product] -= qty * price
        self.position[product] = self.position.get(product, 0) + qty
        self.trade_count += 1
        self.abs_quantity += qty
        return qty

    def sell(self, product: str, price: int, qty: int) -> int:
        if qty <= 0:
            return 0
        self.cash[product] += qty * price
        self.position[product] = self.position.get(product, 0) - qty
        self.trade_count += 1
        self.abs_quantity += qty
        return qty

    def pnl(self, path: BookPath, index: int) -> float:
        total = 0.0
        for product, cash in self.cash.items():
            mids = path.mid.get(product)
            if mids is None:
                continue
            total += cash + self.position.get(product, 0) * float(mids[index])
        return total

    def observe(self, path: BookPath, index: int) -> None:
        pnl = self.pnl(path, index)
        self.peak = max(self.peak, pnl)
        self.max_drawdown = min(self.max_drawdown, pnl - self.peak)


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
        frame["day"] = day
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)
    prices = prices[prices["product"].isin(PRODUCTS)].copy()
    numeric_columns = ["day", "timestamp", "mid_price"]
    for level in (1, 2, 3):
        numeric_columns += [
            f"bid_price_{level}",
            f"bid_volume_{level}",
            f"ask_price_{level}",
            f"ask_volume_{level}",
        ]
    for column in numeric_columns:
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
    prices["timestamp"] = prices["timestamp"].astype(int)
    return prices.sort_values(["day", "timestamp", "product"]).reset_index(drop=True)


def make_paths(prices: pd.DataFrame) -> list[BookPath]:
    paths: list[BookPath] = []
    for day in (0, 1, 2):
        day_data = prices[prices["day"] == day]
        for start in range(0, TICKS_PER_DAY, WINDOW):
            paths.append(_make_path(day_data, day=day, start=start, end=start + WINDOW))
        paths.append(_make_path(day_data, day=day, start=0, end=TICKS_PER_DAY))
    return paths


def _make_path(data: pd.DataFrame, *, day: int, start: int, end: int) -> BookPath:
    path = data[(data["timestamp"] >= start) & (data["timestamp"] < end)]
    timestamps = np.array(sorted(path["timestamp"].unique()), dtype=np.int64)
    mid: dict[str, np.ndarray] = {}
    bid_prices: dict[str, np.ndarray] = {}
    bid_volumes: dict[str, np.ndarray] = {}
    ask_prices: dict[str, np.ndarray] = {}
    ask_volumes: dict[str, np.ndarray] = {}

    for product in PRODUCTS:
        group = path[path["product"] == product].sort_values("timestamp")
        if len(group) != len(timestamps):
            continue
        mid[product] = group["mid_price"].to_numpy(dtype=np.float64)
        bid_prices[product] = np.column_stack(
            [
                group[f"bid_price_{level}"].fillna(-1).to_numpy(dtype=np.int64)
                for level in (1, 2, 3)
            ]
        )
        bid_volumes[product] = np.column_stack(
            [
                group[f"bid_volume_{level}"].abs().fillna(0).to_numpy(dtype=np.int64)
                for level in (1, 2, 3)
            ]
        )
        ask_prices[product] = np.column_stack(
            [
                group[f"ask_price_{level}"].fillna(10**12).to_numpy(dtype=np.int64)
                for level in (1, 2, 3)
            ]
        )
        ask_volumes[product] = np.column_stack(
            [
                group[f"ask_volume_{level}"].abs().fillna(0).to_numpy(dtype=np.int64)
                for level in (1, 2, 3)
            ]
        )

    return BookPath(
        day=day,
        start=start,
        end=end,
        timestamps=timestamps,
        mid=mid,
        bid_prices=bid_prices,
        bid_volumes=bid_volumes,
        ask_prices=ask_prices,
        ask_volumes=ask_volumes,
    )


def historical_tte(day: int, timestamp: int) -> float:
    return max(8.0 - day - timestamp / TICKS_PER_DAY, 1e-6)


def take_buys(
    sim: PortfolioSim,
    path: BookPath,
    product: str,
    index: int,
    threshold: float,
    max_qty: int,
    *,
    price_offset: int = 0,
    levels: int = 3,
) -> int:
    if max_qty <= 0:
        return 0
    limit_left = POS_LIMITS[product] - sim.position.get(product, 0)
    remaining = min(max_qty, limit_left)
    filled = 0
    if remaining <= 0:
        return 0
    prices = path.ask_prices[product][index][:levels]
    volumes = path.ask_volumes[product][index][:levels]
    order = np.argsort(prices)
    for slot in order:
        price = int(prices[slot])
        volume = int(volumes[slot])
        if volume <= 0 or price >= 10**11:
            continue
        if price + price_offset > threshold:
            continue
        qty = min(remaining, volume)
        sim.buy(product, price, qty)
        remaining -= qty
        filled += qty
        if remaining <= 0:
            break
    return filled


def take_sells(
    sim: PortfolioSim,
    path: BookPath,
    product: str,
    index: int,
    threshold: float,
    max_qty: int,
    *,
    price_offset: int = 0,
    levels: int = 3,
) -> int:
    if max_qty <= 0:
        return 0
    limit_left = POS_LIMITS[product] + sim.position.get(product, 0)
    remaining = min(max_qty, limit_left)
    filled = 0
    if remaining <= 0:
        return 0
    prices = path.bid_prices[product][index][:levels]
    volumes = path.bid_volumes[product][index][:levels]
    order = np.argsort(-prices)
    for slot in order:
        price = int(prices[slot])
        volume = int(volumes[slot])
        if volume <= 0 or price < 0:
            continue
        if price + price_offset < threshold:
            continue
        qty = min(remaining, volume)
        sim.sell(product, price, qty)
        remaining -= qty
        filled += qty
        if remaining <= 0:
            break
    return filled


def evaluate(
    *,
    family: str,
    name: str,
    paths: list[BookPath],
    products: Iterable[str],
    step: Callable[[PortfolioSim, BookPath, int], None],
) -> list[EvalResult]:
    results: list[EvalResult] = []
    product_tuple = tuple(products)
    for path in paths:
        sim = PortfolioSim(product_tuple)
        for index in range(path.n):
            step(sim, path, index)
            sim.observe(path, index)
        pnl = sim.pnl(path, path.n - 1) if path.n else 0.0
        positions = {product: sim.position.get(product, 0) for product in product_tuple}
        results.append(
            EvalResult(
                family=family,
                name=name,
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
        )
    return results


def make_static_step(
    configs: dict[str, dict[str, int]],
    *,
    levels: int,
    max_order_mult: int,
) -> Callable[[PortfolioSim, BookPath, int], None]:
    def step(sim: PortfolioSim, path: BookPath, index: int) -> None:
        for product, config in configs.items():
            if product not in path.mid:
                continue
            max_qty = int(config["max_order"]) * max_order_mult
            take_buys(
                sim,
                path,
                product,
                index,
                float(config["buy"]),
                max_qty,
                levels=levels,
            )
            take_sells(
                sim,
                path,
                product,
                index,
                float(config["sell"]),
                max_qty,
                levels=levels,
            )

    return step


@dataclass(frozen=True)
class DeepSynthConfig:
    products: tuple[str, ...]
    short_entry_eq: int
    short_cover_eq: int
    long_entry_eq: int
    long_exit_eq: int
    long_target: int
    max_order: int
    levels: int

    @property
    def name(self) -> str:
        products = "-".join(self.products)
        return (
            f"{products}_se{self.short_entry_eq}_sc{self.short_cover_eq}"
            f"_le{self.long_entry_eq}_lx{self.long_exit_eq}_lt{self.long_target}"
            f"_mo{self.max_order}_l{self.levels}"
        )


def make_deep_synth_step(
    config: DeepSynthConfig,
) -> Callable[[PortfolioSim, BookPath, int], None]:
    def step(sim: PortfolioSim, path: BookPath, index: int) -> None:
        for product in config.products:
            strike = STRIKES[product]
            pos = sim.position.get(product, 0)
            if pos < 0:
                target = config.long_target if _best_synth_ask(path, product, index) <= config.short_cover_eq else pos
                if target > pos:
                    take_buys(
                        sim,
                        path,
                        product,
                        index,
                        config.short_cover_eq - strike,
                        min(config.max_order, target - pos),
                        levels=config.levels,
                    )
                continue

            if pos > 0 and _best_synth_bid(path, product, index) >= config.long_exit_eq:
                take_sells(
                    sim,
                    path,
                    product,
                    index,
                    config.long_exit_eq - strike,
                    min(config.max_order, pos),
                    levels=config.levels,
                )
                pos = sim.position.get(product, 0)

            if _best_synth_bid(path, product, index) >= config.short_entry_eq:
                take_sells(
                    sim,
                    path,
                    product,
                    index,
                    config.short_entry_eq - strike,
                    config.max_order,
                    levels=config.levels,
                )
            elif _best_synth_ask(path, product, index) <= config.long_entry_eq:
                target = config.long_target
                if pos < target:
                    take_buys(
                        sim,
                        path,
                        product,
                        index,
                        config.long_entry_eq - strike,
                        min(config.max_order, target - pos),
                        levels=config.levels,
                    )

    return step


def _best_synth_bid(path: BookPath, product: str, index: int) -> int:
    return int(path.bid_prices[product][index][0]) + STRIKES[product]


def _best_synth_ask(path: BookPath, product: str, index: int) -> int:
    return int(path.ask_prices[product][index][0]) + STRIKES[product]


@dataclass(frozen=True)
class SmileConfig:
    traded: tuple[str, ...]
    fit: tuple[str, ...]
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
        fit = "-".join(product.replace("VEV_", "") for product in self.fit)
        hedge = "hedge" if self.hedge_delta else "raw"
        return (
            f"tr{traded}_fit{fit}_mp{self.max_position}_mo{self.max_order}"
            f"_e{self.entry_edge:g}_rs{self.residual_scale:g}_{hedge}_l{self.levels}"
        )


def make_smile_step(config: SmileConfig) -> Callable[[PortfolioSim, BookPath, int], None]:
    def step(sim: PortfolioSim, path: BookPath, index: int) -> None:
        if UNDERLYING not in path.mid:
            return
        spot = float(path.mid[UNDERLYING][index])
        tte = historical_tte(path.day, int(path.timestamps[index]))
        iv_by_product: dict[str, float] = {}
        m_by_product: dict[str, float] = {}
        for product in config.fit:
            if product not in path.mid:
                continue
            mid = float(path.mid[product][index])
            strike = float(STRIKES[product])
            intrinsic = max(0.0, spot - strike)
            extrinsic = mid - intrinsic
            if extrinsic < 0.5:
                continue
            iv = implied_vol(
                mid,
                spot=spot,
                strike=strike,
                time_to_expiry=tte,
                lo=0.001,
                hi=1.0,
            )
            if iv is None or not (0.001 <= iv <= 0.50):
                continue
            iv_by_product[product] = iv
            m_by_product[product] = math.log(strike / spot) / math.sqrt(tte)

        views: dict[str, tuple[float, float]] = {}
        for product in config.traded:
            if product not in path.mid:
                continue
            fit_products = [p for p in config.fit if p != product and p in iv_by_product]
            if len(fit_products) < 3:
                continue
            degree = 2 if len(fit_products) >= 4 else 1
            xs = np.array([m_by_product[p] for p in fit_products], dtype=np.float64)
            ys = np.array([iv_by_product[p] for p in fit_products], dtype=np.float64)
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
                fair = call_price(inputs)
                delta = call_greeks(inputs).delta
            except (ValueError, OverflowError, ZeroDivisionError):
                continue
            if math.isfinite(fair) and math.isfinite(delta):
                views[product] = (fair, max(0.0, min(1.0, delta)))

        for product in config.traded:
            view = views.get(product)
            if view is None:
                continue
            fair, _delta = view
            mid = float(path.mid[product][index])
            signal = fair - mid
            if abs(signal) < config.entry_edge:
                continue
            raw_target = int(round(signal / config.residual_scale * config.max_position))
            target = max(-config.max_position, min(config.max_position, raw_target))
            current = sim.position.get(product, 0)
            desired = target - current
            if desired > 0:
                ask = int(path.ask_prices[product][index][0])
                if fair - ask >= config.entry_edge:
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
                bid = int(path.bid_prices[product][index][0])
                if bid - fair >= config.entry_edge:
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
            hedge_underlying_delta(sim, path, index, views, config)

    return step


def hedge_underlying_delta(
    sim: PortfolioSim,
    path: BookPath,
    index: int,
    views: dict[str, tuple[float, float]],
    config: SmileConfig,
) -> None:
    net_delta = float(sim.position.get(UNDERLYING, 0))
    for product, (_fair, delta) in views.items():
        net_delta += sim.position.get(product, 0) * delta

    if abs(net_delta) <= config.max_abs_delta:
        return
    if net_delta > 0:
        desired_sell = int(math.ceil(net_delta - config.max_abs_delta))
        take_sells(
            sim,
            path,
            UNDERLYING,
            index,
            -1.0,
            min(config.max_order, desired_sell),
            levels=config.levels,
        )
    else:
        desired_buy = int(math.ceil(-net_delta - config.max_abs_delta))
        take_buys(
            sim,
            path,
            UNDERLYING,
            index,
            10**12,
            min(config.max_order, desired_buy),
            levels=config.levels,
        )


def summarize(results: list[EvalResult]) -> pd.DataFrame:
    if not results:
        return pd.DataFrame()
    rows: list[SummaryRow] = []
    df = pd.DataFrame([asdict(result) for result in results])
    windows = df[df["end"] - df["start"] == WINDOW]
    full = df[df["end"] - df["start"] == TICKS_PER_DAY]
    simulator = df[(df["day"] == 2) & (df["start"] == 0) & (df["end"] == WINDOW)]
    for (family, name), group in df.groupby(["family", "name"], sort=False):
        w = windows[(windows["family"] == family) & (windows["name"] == name)]
        f = full[(full["family"] == family) & (full["name"] == name)]
        s = simulator[(simulator["family"] == family) & (simulator["name"] == name)]
        if w.empty or f.empty:
            continue
        sim_row = s.iloc[0] if not s.empty else None
        rows.append(
            SummaryRow(
                family=str(family),
                name=str(name),
                window_mean=float(w["pnl"].mean()),
                window_min=float(w["pnl"].min()),
                window_p10=float(np.quantile(w["pnl"], 0.10)),
                positive_windows=int((w["pnl"] > 0).sum()),
                full_mean=float(f["pnl"].mean()),
                full_min=float(f["pnl"].min()),
                full_max=float(f["pnl"].max()),
                worst_drawdown=float(group["max_drawdown"].min()),
                mean_abs_qty_full=float(f["abs_quantity"].mean()),
                mean_final_gross_full=float(f["final_gross_position"].mean()),
                simulator_pnl=float(sim_row["pnl"]) if sim_row is not None else float("nan"),
                simulator_drawdown=float(sim_row["max_drawdown"]) if sim_row is not None else float("nan"),
                simulator_final_positions_json=str(sim_row["final_positions_json"])
                if sim_row is not None
                else "{}",
            )
        )
    summary = pd.DataFrame([asdict(row) for row in rows])
    if summary.empty:
        return summary
    summary["robust_score"] = (
        0.35 * summary["full_mean"]
        + 0.35 * summary["full_min"]
        + 0.20 * summary["window_mean"]
        + 2.0 * summary["window_min"].clip(upper=0)
        + 0.10 * summary["simulator_pnl"]
    )
    return summary.sort_values(
        ["robust_score", "full_min", "window_min"], ascending=False
    ).reset_index(drop=True)


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    display = df.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.2f}")
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


def run(data_dir: Path, output_dir: Path, *, include_smile: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_prices(data_dir)
    paths = make_paths(prices)
    all_results: list[EvalResult] = []

    static_jobs: list[tuple[str, dict[str, dict[str, int]], int, int]] = []
    for label, configs in (("old", OLD_STATIC), ("robust_core", ROBUST_CORE)):
        for levels in (1, 3):
            for mult in (1, 2, 4):
                static_jobs.append((label, configs, levels, mult))
    for label, configs, levels, mult in static_jobs:
        products = tuple(configs)
        name = f"{label}_l{levels}_mult{mult}"
        all_results.extend(
            evaluate(
                family="static_depth",
                name=name,
                paths=paths,
                products=products,
                step=make_static_step(configs, levels=levels, max_order_mult=mult),
            )
        )

    deep_configs: list[DeepSynthConfig] = []
    for products in (("VEV_4000",), ("VEV_4500",), DEEP_PRODUCTS):
        for short_entry in (5262, 5266, 5270, 5274):
            for cover_gap in (8, 14, 22):
                cover = short_entry - cover_gap
                for long_target in (0, 120, 300):
                    long_entry = cover - 4
                    for exit_gap in (14, 28, 42):
                        deep_configs.append(
                            DeepSynthConfig(
                                products=tuple(products),
                                short_entry_eq=short_entry,
                                short_cover_eq=cover,
                                long_entry_eq=long_entry,
                                long_exit_eq=long_entry + exit_gap,
                                long_target=long_target,
                                max_order=40,
                                levels=3,
                            )
                        )

    # Keep the first pass intentionally bounded; this is enough to identify
    # whether synthetic deep-ITM logic is directionally better than static.
    for config in deep_configs:
        all_results.extend(
            evaluate(
                family="deep_synth_cycle",
                name=config.name,
                paths=paths,
                products=config.products,
                step=make_deep_synth_step(config),
            )
        )

    if include_smile:
        smile_traded_sets = (
            ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400"),
            ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"),
        )
        smile_fit = ("VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500")
        for traded in smile_traded_sets:
            for max_pos in (60, 120):
                for edge in (0.75, 1.5, 2.5):
                    for residual_scale in (3.0, 8.0):
                        for hedge in (False, True):
                            config = SmileConfig(
                                traded=tuple(traded),
                                fit=smile_fit,
                                max_position=max_pos,
                                max_order=30,
                                entry_edge=edge,
                                residual_scale=residual_scale,
                                hedge_delta=hedge,
                                max_abs_delta=60.0,
                                levels=3,
                            )
                            products = (UNDERLYING, *config.traded) if hedge else config.traded
                            all_results.extend(
                                evaluate(
                                    family="smile_loo",
                                    name=config.name,
                                    paths=paths,
                                    products=products,
                                    step=make_smile_step(config),
                                )
                            )

    results_df = pd.DataFrame([asdict(result) for result in all_results])
    results_df.to_csv(output_dir / "path_results.csv", index=False)
    summary = summarize(all_results)
    summary.to_csv(output_dir / "summary.csv", index=False)

    top_cols = [
        "family",
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
        "# VELVET New Family Research",
        "",
        f"Data dir: `{data_dir}`",
        "",
        "Top candidates by robustness score:",
        "",
        markdown_table(summary[top_cols].head(40)),
        "",
        "Family leaders:",
        "",
    ]
    for family, group in summary.groupby("family", sort=False):
        lines += [
            f"## {family}",
            "",
            markdown_table(group[top_cols].head(12)),
            "",
        ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")

    best_by_family = {
        str(family): group.iloc[0].to_dict()
        for family, group in summary.groupby("family", sort=False)
        if not group.empty
    }
    (output_dir / "best_by_family.json").write_text(
        json.dumps(best_by_family, indent=2, sort_keys=True) + "\n"
    )
    print(f"Wrote {output_dir}")
    if not summary.empty:
        print(summary[top_cols].head(20).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--include-smile", action="store_true")
    args = parser.parse_args()
    run(
        discover_data_dir(args.data_dir),
        Path(args.output_dir),
        include_smile=bool(args.include_smile),
    )


if __name__ == "__main__":
    main()

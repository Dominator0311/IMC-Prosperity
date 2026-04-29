"""Research sweep for the R3 VELVET/options sleeve.

This is deliberately an offline research harness, not live engine code.
It compares broad strategy families on the Round 3 historical tapes:

1. Cross-sectional IV-smile residual trading.
2. Rolling per-strike IV residual trading.
3. Relative-value packages around VEV_5300 / VEV_5400 / VEV_5500.

The fill model is intentionally simple and conservative enough to be useful
for ranking hypotheses: L1 taker fills only, per-product position limits,
optional VELVET delta hedge, and end-of-day marking to the observed mid.
Official fills/hidden fair can differ, so these results are hypothesis
generation rather than proof.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_options_sleeve_sweep"

UNDERLYING = "VELVETFRUIT_EXTRACT"
STRIKES: tuple[int, ...] = (
    4000,
    4500,
    5000,
    5100,
    5200,
    5300,
    5400,
    5500,
    6000,
    6500,
)
VEV_PRODUCTS: tuple[str, ...] = tuple(f"VEV_{k}" for k in STRIKES)
STRIKE_BY_PRODUCT: dict[str, int] = {f"VEV_{k}": k for k in STRIKES}
SMILE_FIT_STRIKES: tuple[int, ...] = (5000, 5100, 5200, 5300, 5400, 5500)
TRADED_PRODUCTS: tuple[str, ...] = (UNDERLYING, *VEV_PRODUCTS)
POS_LIMITS: dict[str, int] = {
    UNDERLYING: 200,
    **{product: 300 for product in VEV_PRODUCTS},
}
TICKS_PER_DAY = 1_000_000


# ---------------------------------------------------------------- math


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def call_price(spot: float, strike: float, t_days: float, vol_daily: float) -> float:
    if spot <= 0 or strike <= 0 or t_days <= 0 or vol_daily <= 0:
        return float("nan")
    sigma_t = vol_daily * math.sqrt(t_days)
    d1 = (math.log(spot / strike) + 0.5 * vol_daily * vol_daily * t_days) / sigma_t
    d2 = d1 - sigma_t
    return spot * norm_cdf(d1) - strike * norm_cdf(d2)


def call_delta(spot: float, strike: float, t_days: float, vol_daily: float) -> float:
    if spot <= 0 or strike <= 0 or t_days <= 0 or vol_daily <= 0:
        return 0.0
    sigma_t = vol_daily * math.sqrt(t_days)
    d1 = (math.log(spot / strike) + 0.5 * vol_daily * vol_daily * t_days) / sigma_t
    return norm_cdf(d1)


def implied_vol(
    price: float,
    *,
    spot: float,
    strike: float,
    t_days: float,
    lo: float = 1e-5,
    hi: float = 1.0,
) -> float | None:
    if price <= 0 or spot <= 0 or strike <= 0 or t_days <= 0:
        return None
    intrinsic = max(spot - strike, 0.0)
    if price < intrinsic - 1e-7:
        return None

    f_lo = call_price(spot, strike, t_days, lo) - price
    f_hi = call_price(spot, strike, t_days, hi) - price
    if abs(f_lo) < 1e-7:
        return lo
    widen_count = 0
    while f_hi < 0.0 and hi < 10.0 and widen_count < 8:
        hi *= 2.0
        f_hi = call_price(spot, strike, t_days, hi) - price
        widen_count += 1
    if f_lo * f_hi > 0:
        return None

    for _ in range(48):
        mid = 0.5 * (lo + hi)
        f_mid = call_price(spot, strike, t_days, mid) - price
        if abs(f_mid) < 1e-7:
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return 0.5 * (lo + hi)


def scaled_moneyness(strike: int, spot: float, t_days: float) -> float:
    return math.log(strike / spot) / math.sqrt(t_days)


# ---------------------------------------------------------------- data


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    bid_volume: int
    ask_volume: int
    mid: float


@dataclass(frozen=True)
class OptionView:
    fair: float
    iv: float
    fair_iv: float
    delta: float
    residual: float


@dataclass(frozen=True)
class Tick:
    day: int
    timestamp: int
    tte_days: float
    quotes: dict[str, Quote]
    options: dict[str, OptionView]


def discover_data_dir(explicit: str | None = None) -> Path:
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
    raise FileNotFoundError(
        "Could not find Round 3 CSVs. Pass --data-dir or set ROUND3_DATA_DIR."
    )


def load_prices(data_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day in (0, 1, 2):
        path = data_dir / f"prices_round_3_day_{day}.csv"
        frame = pd.read_csv(path, sep=";")
        frame["source_day"] = day
        frames.append(frame)
    prices = pd.concat(frames, ignore_index=True)
    prices = prices[prices["product"].isin(TRADED_PRODUCTS)].copy()
    for col in (
        "day",
        "timestamp",
        "bid_price_1",
        "bid_volume_1",
        "ask_price_1",
        "ask_volume_1",
        "mid_price",
    ):
        prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices["bid_volume_1"] = prices["bid_volume_1"].abs().fillna(0).astype(int)
    prices["ask_volume_1"] = prices["ask_volume_1"].abs().fillna(0).astype(int)
    prices["tte_days"] = (8.0 - prices["day"]) - prices["timestamp"] / TICKS_PER_DAY
    prices["tte_days"] = prices["tte_days"].clip(lower=1e-6)
    return prices


def compute_tick_views(prices: pd.DataFrame) -> dict[int, list[Tick]]:
    ticks_by_day: dict[int, list[Tick]] = defaultdict(list)

    for (day, timestamp), group in prices.groupby(["day", "timestamp"], sort=True):
        quote_by_product: dict[str, Quote] = {}
        for row in group.itertuples():
            if not (
                math.isfinite(float(row.bid_price_1))
                and math.isfinite(float(row.ask_price_1))
                and math.isfinite(float(row.mid_price))
            ):
                continue
            quote_by_product[str(row.product)] = Quote(
                bid=float(row.bid_price_1),
                ask=float(row.ask_price_1),
                bid_volume=int(row.bid_volume_1),
                ask_volume=int(row.ask_volume_1),
                mid=float(row.mid_price),
            )
        spot_quote = quote_by_product.get(UNDERLYING)
        if spot_quote is None:
            continue

        tte_days = float(group["tte_days"].iloc[0])
        iv_by_product: dict[str, float] = {}
        m_by_product: dict[str, float] = {}
        for product in VEV_PRODUCTS:
            quote = quote_by_product.get(product)
            if quote is None:
                continue
            strike = STRIKE_BY_PRODUCT[product]
            iv = implied_vol(
                quote.mid,
                spot=spot_quote.mid,
                strike=float(strike),
                t_days=tte_days,
            )
            if iv is None or not math.isfinite(iv):
                continue
            iv_by_product[product] = iv
            m_by_product[product] = scaled_moneyness(strike, spot_quote.mid, tte_days)

        option_views: dict[str, OptionView] = {}
        base_points = [
            (m_by_product[f"VEV_{strike}"], iv_by_product[f"VEV_{strike}"], strike)
            for strike in SMILE_FIT_STRIKES
            if f"VEV_{strike}" in iv_by_product
            and 0.001 <= iv_by_product[f"VEV_{strike}"] <= 0.20
        ]

        all_coeff: np.ndarray | None = None
        if len(base_points) >= 3:
            all_coeff = np.polyfit(
                [point[0] for point in base_points],
                [point[1] for point in base_points],
                deg=2,
            )

        for product, iv in iv_by_product.items():
            strike = STRIKE_BY_PRODUCT[product]
            points = base_points
            if strike in SMILE_FIT_STRIKES:
                points = [point for point in base_points if point[2] != strike]
            coeff: np.ndarray | None = None
            if len(points) >= 3:
                coeff = np.polyfit(
                    [point[0] for point in points],
                    [point[1] for point in points],
                    deg=2,
                )
            elif all_coeff is not None:
                coeff = all_coeff
            if coeff is None:
                continue
            fair_iv = float(np.polyval(coeff, m_by_product[product]))
            if not math.isfinite(fair_iv) or fair_iv <= 0 or fair_iv > 1.0:
                continue
            fair = call_price(spot_quote.mid, float(strike), tte_days, fair_iv)
            delta = call_delta(spot_quote.mid, float(strike), tte_days, fair_iv)
            quote = quote_by_product[product]
            option_views[product] = OptionView(
                fair=fair,
                iv=iv,
                fair_iv=fair_iv,
                delta=delta,
                residual=quote.mid - fair,
            )

        ticks_by_day[int(day)].append(
            Tick(
                day=int(day),
                timestamp=int(timestamp),
                tte_days=tte_days,
                quotes=quote_by_product,
                options=option_views,
            )
        )

    return dict(ticks_by_day)


# ---------------------------------------------------------------- simulation


@dataclass(frozen=True)
class CandidateConfig:
    name: str
    family: str
    traded_strikes: tuple[int, ...]
    entry_edge: float
    exit_edge: float
    residual_scale: float
    max_position: int
    max_order: int
    hedge_ratio: float = 0.0
    hedge_trigger: float = 40.0
    max_abs_delta: float | None = None
    terminal_flatten_start: int | None = None
    rolling_halflife: float = 80.0
    rolling_warmup: int = 40
    package: tuple[tuple[int, int], ...] = ()
    package_entry_edge: float = 0.0
    package_max_units: int = 80


@dataclass
class FillRecord:
    day: int
    timestamp: int
    candidate: str
    product: str
    side: str
    price: float
    quantity: int
    fair: float | None
    edge: float | None
    position_after: int


@dataclass
class DayResult:
    candidate: str
    family: str
    day: int
    pnl: float
    max_drawdown: float
    trade_count: int
    abs_quantity: int
    final_gross: int
    final_delta: float
    final_positions: dict[str, int]
    hedge_abs_quantity: int
    option_abs_quantity: int


class RollingIvFair:
    def __init__(self, halflife: float, warmup: int) -> None:
        self._alpha = 1.0 - 0.5 ** (1.0 / halflife)
        self._warmup = warmup
        self._ewma: dict[str, float] = {}
        self._count: dict[str, int] = defaultdict(int)

    def fair_before_update(self, product: str) -> float | None:
        if self._count.get(product, 0) < self._warmup:
            return None
        return self._ewma.get(product)

    def observe(self, product: str, iv: float) -> None:
        if not (0.001 <= iv <= 0.20):
            return
        prev = self._ewma.get(product)
        self._ewma[product] = iv if prev is None else self._alpha * iv + (1 - self._alpha) * prev
        self._count[product] += 1


class SleeveSimulator:
    def __init__(self, config: CandidateConfig) -> None:
        self.config = config
        self.cash = 0.0
        self.positions: dict[str, int] = defaultdict(int)
        self.fills: list[FillRecord] = []
        self.pnl_path: list[tuple[int, float]] = []
        self.rolling_iv = RollingIvFair(config.rolling_halflife, config.rolling_warmup)

    def run_day(self, ticks: list[Tick]) -> DayResult:
        for tick in ticks:
            if (
                self.config.terminal_flatten_start is not None
                and tick.timestamp >= self.config.terminal_flatten_start
            ):
                self._step_flatten(tick)
            elif self.config.family == "rolling_iv":
                self._step_rolling_iv(tick)
            elif self.config.family == "cross_smile":
                self._step_cross_smile(tick)
            elif self.config.family == "package":
                self._step_package(tick)
            else:
                raise ValueError(f"unknown family: {self.config.family}")

            if self.config.hedge_ratio > 0:
                self._step_hedge(tick)
            self._mark(tick)

        final_tick = ticks[-1]
        final_pnl = self._pnl(final_tick)
        peak = -float("inf")
        max_drawdown = 0.0
        for _, pnl in self.pnl_path:
            peak = max(peak, pnl)
            max_drawdown = min(max_drawdown, pnl - peak)

        final_delta = self._net_delta(final_tick)
        option_abs_qty = sum(
            fill.quantity
            for fill in self.fills
            if fill.product != UNDERLYING
        )
        hedge_abs_qty = sum(
            fill.quantity
            for fill in self.fills
            if fill.product == UNDERLYING
        )
        return DayResult(
            candidate=self.config.name,
            family=self.config.family,
            day=final_tick.day,
            pnl=final_pnl,
            max_drawdown=max_drawdown,
            trade_count=len(self.fills),
            abs_quantity=option_abs_qty + hedge_abs_qty,
            final_gross=sum(abs(v) for v in self.positions.values()),
            final_delta=final_delta,
            final_positions={k: v for k, v in sorted(self.positions.items()) if v != 0},
            hedge_abs_quantity=hedge_abs_qty,
            option_abs_quantity=option_abs_qty,
        )

    def _step_cross_smile(self, tick: Tick) -> None:
        for strike in self.config.traded_strikes:
            product = f"VEV_{strike}"
            view = tick.options.get(product)
            quote = tick.quotes.get(product)
            if view is None or quote is None:
                continue
            self._trade_to_signal_target(
                tick=tick,
                product=product,
                fair=view.fair,
                signal=view.fair - quote.mid,
                quote=quote,
            )

    def _step_rolling_iv(self, tick: Tick) -> None:
        spot = tick.quotes[UNDERLYING].mid
        for strike in self.config.traded_strikes:
            product = f"VEV_{strike}"
            view = tick.options.get(product)
            quote = tick.quotes.get(product)
            if view is None or quote is None:
                continue
            rolling_iv = self.rolling_iv.fair_before_update(product)
            if rolling_iv is not None:
                fair = call_price(spot, float(strike), tick.tte_days, rolling_iv)
                self._trade_to_signal_target(
                    tick=tick,
                    product=product,
                    fair=fair,
                    signal=fair - quote.mid,
                    quote=quote,
                )
            self.rolling_iv.observe(product, view.iv)

    def _step_package(self, tick: Tick) -> None:
        if not self.config.package:
            return
        unit_edges: list[float] = []
        executable: list[tuple[str, int, Quote, OptionView, float]] = []
        for strike, ratio in self.config.package:
            product = f"VEV_{strike}"
            quote = tick.quotes.get(product)
            view = tick.options.get(product)
            if quote is None or view is None:
                return
            if ratio > 0:
                edge = view.fair - quote.ask
            else:
                edge = quote.bid - view.fair
            unit_edges.append(abs(ratio) * edge)
            executable.append((product, ratio, quote, view, edge))

        package_edge = sum(unit_edges)
        if package_edge < self.config.package_entry_edge:
            return

        current_units = self._package_units()
        units_to_add = min(
            self.config.max_order,
            max(0, self.config.package_max_units - current_units),
            max(1, int(package_edge / max(self.config.residual_scale, 1e-9))),
        )
        if units_to_add <= 0:
            return

        for product, ratio, quote, view, edge in executable:
            desired = abs(ratio) * units_to_add
            if ratio > 0:
                self._buy(tick, product, quote, desired, view.fair, edge)
            else:
                self._sell(tick, product, quote, desired, view.fair, edge)

    def _package_units(self) -> int:
        units = []
        for strike, ratio in self.config.package:
            product = f"VEV_{strike}"
            if ratio == 0:
                continue
            pos = self.positions.get(product, 0)
            if ratio > 0:
                units.append(max(0, pos // ratio))
            else:
                units.append(max(0, -pos // abs(ratio)))
        return min(units) if units else 0

    def _trade_to_signal_target(
        self,
        *,
        tick: Tick,
        product: str,
        fair: float,
        signal: float,
        quote: Quote,
    ) -> None:
        if abs(signal) <= self.config.exit_edge:
            target = 0
        else:
            raw_target = int(round(signal / self.config.residual_scale * self.config.max_position))
            target = max(-self.config.max_position, min(self.config.max_position, raw_target))

        current = self.positions.get(product, 0)
        delta = target - current
        if delta > 0:
            edge = fair - quote.ask
            if edge >= self.config.entry_edge:
                qty = min(delta, self.config.max_order)
                self._buy(tick, product, quote, qty, fair, edge)
        elif delta < 0:
            edge = quote.bid - fair
            if edge >= self.config.entry_edge:
                qty = min(-delta, self.config.max_order)
                self._sell(tick, product, quote, qty, fair, edge)

    def _step_hedge(self, tick: Tick) -> None:
        quote = tick.quotes.get(UNDERLYING)
        if quote is None:
            return
        option_delta = self._option_delta(tick)
        target = int(round(-self.config.hedge_ratio * option_delta))
        target = max(-POS_LIMITS[UNDERLYING], min(POS_LIMITS[UNDERLYING], target))
        current = self.positions.get(UNDERLYING, 0)
        delta = target - current
        if abs(delta) < self.config.hedge_trigger:
            return
        qty = min(abs(delta), self.config.max_order)
        if delta > 0:
            self._buy(tick, UNDERLYING, quote, qty, quote.mid, None)
        else:
            self._sell(tick, UNDERLYING, quote, qty, quote.mid, None)

    def _step_flatten(self, tick: Tick) -> None:
        for product in TRADED_PRODUCTS:
            pos = self.positions.get(product, 0)
            if pos == 0:
                continue
            quote = tick.quotes.get(product)
            if quote is None:
                continue
            qty = min(abs(pos), self.config.max_order)
            if pos > 0:
                self._sell(tick, product, quote, qty, quote.mid, None)
            else:
                self._buy(tick, product, quote, qty, quote.mid, None)

    def _buy(
        self,
        tick: Tick,
        product: str,
        quote: Quote,
        qty: int,
        fair: float | None,
        edge: float | None,
    ) -> int:
        limit = POS_LIMITS[product]
        room = max(0, limit - self.positions.get(product, 0))
        fill_qty = min(qty, room, quote.ask_volume)
        fill_qty = self._clip_for_delta_cap(tick, product, fill_qty, side=1)
        if fill_qty <= 0:
            return 0
        self.positions[product] += fill_qty
        self.cash -= fill_qty * quote.ask
        self.fills.append(
            FillRecord(
                day=tick.day,
                timestamp=tick.timestamp,
                candidate=self.config.name,
                product=product,
                side="BUY",
                price=quote.ask,
                quantity=fill_qty,
                fair=fair,
                edge=edge,
                position_after=self.positions[product],
            )
        )
        return fill_qty

    def _sell(
        self,
        tick: Tick,
        product: str,
        quote: Quote,
        qty: int,
        fair: float | None,
        edge: float | None,
    ) -> int:
        limit = POS_LIMITS[product]
        room = max(0, limit + self.positions.get(product, 0))
        fill_qty = min(qty, room, quote.bid_volume)
        fill_qty = self._clip_for_delta_cap(tick, product, fill_qty, side=-1)
        if fill_qty <= 0:
            return 0
        self.positions[product] -= fill_qty
        self.cash += fill_qty * quote.bid
        self.fills.append(
            FillRecord(
                day=tick.day,
                timestamp=tick.timestamp,
                candidate=self.config.name,
                product=product,
                side="SELL",
                price=quote.bid,
                quantity=fill_qty,
                fair=fair,
                edge=edge,
                position_after=self.positions[product],
            )
        )
        return fill_qty

    def _clip_for_delta_cap(
        self,
        tick: Tick,
        product: str,
        qty: int,
        *,
        side: int,
    ) -> int:
        cap = self.config.max_abs_delta
        if cap is None or qty <= 0:
            return qty

        current_delta = self._net_delta(tick)
        if product == UNDERLYING:
            delta_per_unit = 1.0
        else:
            view = tick.options.get(product)
            if view is None:
                return 0
            delta_per_unit = view.delta

        # If the trade reduces absolute delta, allow it even if the book is
        # already beyond cap. Otherwise clip to the largest cap-respecting size.
        for clipped in range(qty, 0, -1):
            projected = current_delta + side * clipped * delta_per_unit
            if abs(projected) <= cap or abs(projected) < abs(current_delta):
                return clipped
        return 0

    def _mark(self, tick: Tick) -> None:
        self.pnl_path.append((tick.timestamp, self._pnl(tick)))

    def _pnl(self, tick: Tick) -> float:
        pnl = self.cash
        for product, pos in self.positions.items():
            quote = tick.quotes.get(product)
            if quote is not None:
                pnl += pos * quote.mid
        return pnl

    def _option_delta(self, tick: Tick) -> float:
        total = 0.0
        for product in VEV_PRODUCTS:
            pos = self.positions.get(product, 0)
            if pos == 0:
                continue
            view = tick.options.get(product)
            if view is not None:
                total += pos * view.delta
        return total

    def _net_delta(self, tick: Tick) -> float:
        return self.positions.get(UNDERLYING, 0) + self._option_delta(tick)


# ---------------------------------------------------------------- configs


def candidate_grid() -> list[CandidateConfig]:
    configs: list[CandidateConfig] = []
    core_strikes = (5000, 5100, 5200, 5300, 5400, 5500)
    rv_strikes = (5200, 5300, 5400, 5500)

    for hedge_ratio in (0.0, 0.5):
        for entry_edge in (0.5, 1.0, 1.5, 2.0):
            for scale in (2.0, 4.0, 8.0):
                configs.append(
                    CandidateConfig(
                        name=(
                            f"cross_core_e{entry_edge:g}_s{scale:g}_h{hedge_ratio:g}"
                        ),
                        family="cross_smile",
                        traded_strikes=core_strikes,
                        entry_edge=entry_edge,
                        exit_edge=0.25,
                        residual_scale=scale,
                        max_position=220,
                        max_order=25,
                        hedge_ratio=hedge_ratio,
                    )
                )
                configs.append(
                    CandidateConfig(
                        name=(
                            f"cross_rv_e{entry_edge:g}_s{scale:g}_h{hedge_ratio:g}"
                        ),
                        family="cross_smile",
                        traded_strikes=rv_strikes,
                        entry_edge=entry_edge,
                        exit_edge=0.25,
                        residual_scale=scale,
                        max_position=240,
                        max_order=25,
                        hedge_ratio=hedge_ratio,
                    )
                )

    for hedge_ratio in (0.0, 0.5):
        for entry_edge in (0.5, 1.0, 1.5):
            for halflife in (40.0, 80.0, 160.0):
                configs.append(
                    CandidateConfig(
                        name=(
                            f"rolling_core_e{entry_edge:g}_hl{halflife:g}_h{hedge_ratio:g}"
                        ),
                        family="rolling_iv",
                        traded_strikes=core_strikes,
                        entry_edge=entry_edge,
                        exit_edge=0.10,
                        residual_scale=1.5,
                        max_position=180,
                        max_order=20,
                        hedge_ratio=hedge_ratio,
                        rolling_halflife=halflife,
                    )
                )

    packages: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
        ("p_2x5400_short5300", ((5400, 2), (5300, -1))),
        ("p_5400_short5500", ((5400, 1), (5500, -1))),
        ("p_2x5400_short5300_5500", ((5400, 2), (5300, -1), (5500, -1))),
    )
    for package_name, package in packages:
        for edge in (3.0, 5.0, 7.0, 9.0):
            for hedge_ratio in (0.0, 0.5):
                configs.append(
                    CandidateConfig(
                        name=f"{package_name}_edge{edge:g}_h{hedge_ratio:g}",
                        family="package",
                        traded_strikes=(),
                        entry_edge=0.0,
                        exit_edge=0.0,
                        residual_scale=3.0,
                        max_position=240,
                        max_order=10,
                        hedge_ratio=hedge_ratio,
                        package=package,
                        package_entry_edge=edge,
                        package_max_units=100,
                    )
                )

    return configs


def risk_candidate_grid() -> list[CandidateConfig]:
    configs: list[CandidateConfig] = []
    core_strikes = (5000, 5100, 5200, 5300, 5400, 5500)
    rv_strikes = (5200, 5300, 5400, 5500)

    for traded_name, strikes in (("core", core_strikes), ("rv", rv_strikes)):
        for entry_edge in (0.5, 0.75, 1.0):
            for halflife in (40.0, 80.0, 160.0):
                for max_position in (40, 80, 120):
                    for scale in (2.0, 4.0):
                        for max_abs_delta in (80.0, 140.0, 220.0):
                            for flatten_start in (None, 950_000):
                                suffix = (
                                    f"{traded_name}_e{entry_edge:g}"
                                    f"_hl{halflife:g}_mp{max_position}"
                                    f"_s{scale:g}_dc{max_abs_delta:g}"
                                    f"_flat{flatten_start or 0}"
                                )
                                configs.append(
                                    CandidateConfig(
                                        name=f"risk_roll_{suffix}",
                                        family="rolling_iv",
                                        traded_strikes=strikes,
                                        entry_edge=entry_edge,
                                        exit_edge=0.10,
                                        residual_scale=scale,
                                        max_position=max_position,
                                        max_order=18,
                                        hedge_ratio=0.0,
                                        max_abs_delta=max_abs_delta,
                                        terminal_flatten_start=flatten_start,
                                        rolling_halflife=halflife,
                                    )
                                )

    for entry_edge in (1.0, 1.5):
        for scale in (4.0, 8.0):
            for max_position in (60, 100):
                for hedge_ratio in (0.0, 1.0):
                    for max_abs_delta in (80.0, 140.0):
                        for flatten_start in (None, 950_000):
                            suffix = (
                                f"e{entry_edge:g}_s{scale:g}_mp{max_position}"
                                f"_h{hedge_ratio:g}_dc{max_abs_delta:g}"
                                f"_flat{flatten_start or 0}"
                            )
                            configs.append(
                                CandidateConfig(
                                    name=f"risk_cross_rv_{suffix}",
                                    family="cross_smile",
                                    traded_strikes=rv_strikes,
                                    entry_edge=entry_edge,
                                    exit_edge=0.25,
                                    residual_scale=scale,
                                    max_position=max_position,
                                    max_order=18,
                                    hedge_ratio=hedge_ratio,
                                    max_abs_delta=max_abs_delta,
                                    terminal_flatten_start=flatten_start,
                                )
                            )

    return configs


# ---------------------------------------------------------------- outputs


def write_outputs(
    *,
    output_dir: Path,
    data_dir: Path,
    results: list[DayResult],
    configs: list[CandidateConfig],
    fill_records: list[FillRecord],
    pnl_paths: dict[tuple[str, int], list[tuple[int, float]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for result in results:
        row = asdict(result)
        row["final_positions_json"] = json.dumps(row.pop("final_positions"), sort_keys=True)
        rows.append(row)
    all_results = pd.DataFrame(rows)
    all_results.to_csv(output_dir / "all_results.csv", index=False)

    summary = (
        all_results.groupby(["candidate", "family"], as_index=False)
        .agg(
            mean_pnl=("pnl", "mean"),
            min_pnl=("pnl", "min"),
            max_pnl=("pnl", "max"),
            mean_drawdown=("max_drawdown", "mean"),
            max_drawdown=("max_drawdown", "min"),
            mean_trade_count=("trade_count", "mean"),
            mean_abs_quantity=("abs_quantity", "mean"),
            mean_final_gross=("final_gross", "mean"),
            mean_abs_final_delta=("final_delta", lambda s: float(np.mean(np.abs(s)))),
            mean_hedge_abs_quantity=("hedge_abs_quantity", "mean"),
        )
        .sort_values(["min_pnl", "mean_pnl"], ascending=[False, False])
    )
    summary.to_csv(output_dir / "ranked_summary.csv", index=False)

    pd.DataFrame([asdict(config) for config in configs]).to_csv(
        output_dir / "candidate_configs.csv", index=False
    )
    pd.DataFrame([asdict(fill) for fill in fill_records]).to_csv(
        output_dir / "fills.csv", index=False
    )

    top_names = tuple(summary.head(8)["candidate"])
    path_rows = []
    for (candidate, day), path in pnl_paths.items():
        if candidate not in top_names:
            continue
        for timestamp, pnl in path:
            path_rows.append(
                {
                    "candidate": candidate,
                    "day": day,
                    "timestamp": timestamp,
                    "pnl": pnl,
                }
            )
    pd.DataFrame(path_rows).to_csv(output_dir / "top_pnl_paths.csv", index=False)

    if path_rows:
        path_df = pd.DataFrame(path_rows)
        fig, axes = plt.subplots(3, 1, figsize=(14, 11), sharex=True)
        for day, ax in zip((0, 1, 2), axes):
            dg = path_df[path_df["day"] == day]
            for candidate, cg in dg.groupby("candidate"):
                ax.plot(cg["timestamp"], cg["pnl"], label=candidate, linewidth=1.2)
            ax.set_title(f"Day {day} PnL paths for top candidates")
            ax.set_ylabel("PnL")
        axes[-1].set_xlabel("timestamp")
        handles, labels = axes[0].get_legend_handles_labels()
        fig.legend(handles, labels, loc="center right", fontsize=7)
        fig.tight_layout(rect=[0, 0, 0.82, 1])
        fig.savefig(output_dir / "top_pnl_paths.png", dpi=160)
        plt.close(fig)

    family_summary = (
        summary.groupby("family", as_index=False)
        .agg(
            best_mean_pnl=("mean_pnl", "max"),
            best_min_pnl=("min_pnl", "max"),
            candidates=("candidate", "count"),
        )
        .sort_values("best_min_pnl", ascending=False)
    )
    family_summary.to_csv(output_dir / "family_summary.csv", index=False)

    top = summary.head(20)
    md_lines = [
        "# VELVET/options sleeve sweep",
        "",
        f"Data dir: `{data_dir}`",
        "",
        "Local model: L1 taker fills only, per-product limits, optional VELVET hedge, "
        "end-of-day mid marking. Treat as strategy-family ranking, not official proof.",
        "",
        "## Family summary",
        "",
        _markdown_table(family_summary),
        "",
        "## Top candidates",
        "",
        _markdown_table(top),
        "",
        "## Files",
        "",
        "- `all_results.csv`",
        "- `ranked_summary.csv`",
        "- `candidate_configs.csv`",
        "- `fills.csv`",
        "- `top_pnl_paths.csv`",
        "- `top_pnl_paths.png`",
    ]
    (output_dir / "report.md").write_text("\n".join(md_lines) + "\n")


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_empty_"
    display = df.copy()
    for column in display.columns:
        if pd.api.types.is_float_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:.3f}")
    headers = list(display.columns)
    rows = [[str(value) for value in row] for row in display.to_numpy()]
    widths = [len(header) for header in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def line(values: Iterable[str]) -> str:
        vals = list(values)
        return "| " + " | ".join(vals[i].ljust(widths[i]) for i in range(len(widths))) + " |"

    sep = "| " + " | ".join("-" * width for width in widths) + " |"
    return "\n".join([line(headers), sep, *(line(row) for row in rows)])


# ---------------------------------------------------------------- main


def run(data_dir: Path, output_dir: Path, *, mode: str) -> None:
    prices = load_prices(data_dir)
    ticks_by_day = compute_tick_views(prices)
    configs = risk_candidate_grid() if mode == "risk" else candidate_grid()

    results: list[DayResult] = []
    all_fills: list[FillRecord] = []
    pnl_paths: dict[tuple[str, int], list[tuple[int, float]]] = {}

    for config in configs:
        for day in (0, 1, 2):
            ticks = ticks_by_day[day]
            simulator = SleeveSimulator(config)
            result = simulator.run_day(ticks)
            results.append(result)
            all_fills.extend(simulator.fills)
            pnl_paths[(config.name, day)] = list(simulator.pnl_path)

    write_outputs(
        output_dir=output_dir,
        data_dir=data_dir,
        results=results,
        configs=configs,
        fill_records=all_fills,
        pnl_paths=pnl_paths,
    )
    ranked = pd.read_csv(output_dir / "ranked_summary.csv")
    print(f"Wrote VELVET/options sweep to {output_dir}")
    print(ranked.head(15).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=None, help="Round 3 CSV directory")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    parser.add_argument(
        "--mode",
        choices=("broad", "risk"),
        default="broad",
        help="Candidate grid to run",
    )
    args = parser.parse_args()

    data_dir = discover_data_dir(args.data_dir)
    output_dir = Path(args.output_dir)
    run(data_dir, output_dir, mode=args.mode)


if __name__ == "__main__":
    main()

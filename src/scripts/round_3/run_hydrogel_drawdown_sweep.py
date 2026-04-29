"""HYDROGEL drawdown-mitigation research sweep.

Goal: isolate HYDROGEL and compare strategy variants on both final PnL and
path quality. This script is intentionally offline/research-only.

It evaluates:
  - the current wide static-MR shape
  - smaller position caps
  - high-zone profit reduction
  - trailing mid stop while holding inventory
  - falling-knife pause that suppresses adding in the direction of momentum

Datasets:
  - historical R3 days 0/1/2
  - official path from outputs/round_3/Results/extracted_new/413315.log
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.backtest.fill_model import FillModel, FillModelConfig
from src.backtest.replay_engine import ReplayEngine, ReplayStep
from src.backtest.simulator import BacktestSimulator
from src.core.config_core import EngineConfig, ProductConfig
from src.core.market_data import MarketDataAdapter
from src.core.primitives.sst import SSTParams, take_clear_make
from src.core.primitives.terminal_ramp import scaled_cap
from src.core.types import NormalizedSnapshot
from src.datamodel import Order, Trade, TradingState


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data/raw/round_3"
RESULTS_DIR = REPO_ROOT / "outputs" / "round_3" / "Results"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_drawdown_sweep"

PRODUCT = "HYDROGEL_PACK"
HARD_LIMIT = 200


@dataclass(frozen=True)
class Candidate:
    name: str
    mu: float = 9980.0
    take_width: float = 30.0
    clear_threshold: float = 0.9
    max_pos: int = 200
    high_reduce_gap: float | None = None
    high_reduce_fraction: float = 1.0
    trail_stop: float | None = None
    trail_fraction: float = 1.0
    cooldown_ticks: int = 0
    momentum_lookback: int | None = None
    momentum_threshold: float = 0.0
    adaptive_gap: bool = False
    vol_window: int = 50
    vol_mult: float = 0.0
    spread_mult: float = 0.0
    inv_mult: float = 0.0


@dataclass(frozen=True)
class Row:
    dataset: str
    candidate: str
    final_pnl: float
    peak_pnl: float
    min_pnl: float
    max_drawdown: float
    final_over_peak: float
    final_pos: int
    trades: int
    taker_qty: int
    maker_qty: int
    near_limit_steps: int
    avg_markout_20: float | None


class HydrogelDDTrader:
    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate
        self.config = EngineConfig(
            products={
                PRODUCT: ProductConfig(
                    position_limit=HARD_LIMIT,
                    strategy_name="market_making",
                    fair_value_method="anchor",
                    anchor_price=candidate.mu,
                )
            }
        )
        self.market_data = MarketDataAdapter()
        self.logger = _NoopLogger()
        self._mids: list[float] = []
        self._long_high: float | None = None
        self._short_low: float | None = None
        self._cooldown_left = 0

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snap = self.market_data.normalize_state(state).get(PRODUCT)
        if snap is None or snap.mid is None:
            return {PRODUCT: []}, 0, state.traderData

        mid = float(snap.mid)
        self._mids.append(mid)
        orders = self._orders(snap, mid)
        return {PRODUCT: orders}, 0, state.traderData

    def _orders(self, snap: NormalizedSnapshot, mid: float) -> list[Order]:
        c = self.candidate
        pos = int(snap.position)

        if self._cooldown_left > 0:
            self._cooldown_left -= 1

        risk_order = self._risk_reduction_order(snap, mid, pos)
        if risk_order is not None:
            if c.cooldown_ticks > 0:
                self._cooldown_left = c.cooldown_ticks
            return [risk_order]

        cap = min(c.max_pos, scaled_cap(HARD_LIMIT, snap.timestamp))
        fair = c.mu - (pos / max(cap, 1)) * 2.0
        decision = take_clear_make(
            product=PRODUCT,
            fair_value=fair,
            snapshot=snap,
            position=pos,
            position_limit=cap,
            params=SSTParams(
                take_width=c.take_width,
                clear_threshold=c.clear_threshold,
                clear_width=2.0,
                default_edge=3.0,
                disregard_edge=1.0,
                join_edge=3.0,
                default_quote_size=20,
                max_taker_size=200,
                prevent_adverse=False,
                quote_inside_wall=False,
                wall_min_volume=10,
            ),
        )
        orders = list(decision.orders)
        orders = self._apply_momentum_pause(orders)
        if self._cooldown_left > 0:
            orders = self._apply_cooldown_filter(orders, pos)
        return orders

    def _risk_reduction_order(
        self,
        snap: NormalizedSnapshot,
        mid: float,
        pos: int,
    ) -> Order | None:
        c = self.candidate
        if pos > 0:
            self._long_high = mid if self._long_high is None else max(self._long_high, mid)
            self._short_low = None
        elif pos < 0:
            self._short_low = mid if self._short_low is None else min(self._short_low, mid)
            self._long_high = None
        else:
            self._long_high = None
            self._short_low = None

        # Profit-zone reduction: do not carry old long inventory after the
        # cycle reaches the upper side of the mean-reversion band.
        reset_gap = self._reset_gap(snap, pos)
        if reset_gap is not None:
            if pos > 0 and mid >= c.mu + reset_gap and snap.best_bid is not None:
                qty = _fractional_qty(pos, c.high_reduce_fraction)
                return Order(PRODUCT, snap.best_bid.price, -qty)
            if pos < 0 and mid <= c.mu - reset_gap and snap.best_ask is not None:
                qty = _fractional_qty(-pos, c.high_reduce_fraction)
                return Order(PRODUCT, snap.best_ask.price, qty)

        # Trailing stop from the best mid seen while holding this inventory.
        if c.trail_stop is not None:
            if (
                pos > 0
                and self._long_high is not None
                and self._long_high - mid >= c.trail_stop
                and snap.best_bid is not None
            ):
                qty = _fractional_qty(pos, c.trail_fraction)
                return Order(PRODUCT, snap.best_bid.price, -qty)
            if (
                pos < 0
                and self._short_low is not None
                and mid - self._short_low >= c.trail_stop
                and snap.best_ask is not None
            ):
                qty = _fractional_qty(-pos, c.trail_fraction)
                return Order(PRODUCT, snap.best_ask.price, qty)
        return None

    def _reset_gap(self, snap: NormalizedSnapshot, pos: int) -> float | None:
        c = self.candidate
        if c.high_reduce_gap is None:
            return None
        if not c.adaptive_gap:
            return c.high_reduce_gap

        recent = self._mids[-c.vol_window:]
        if len(recent) >= 5:
            avg = sum(recent) / len(recent)
            variance = sum((x - avg) ** 2 for x in recent) / len(recent)
            realized_vol = variance ** 0.5
        else:
            realized_vol = 0.0
        spread = float(snap.spread or 0.0)
        inv_pressure = abs(pos) / HARD_LIMIT
        gap = (
            c.high_reduce_gap
            + c.vol_mult * realized_vol
            + c.spread_mult * max(0.0, spread - 10.0)
            - c.inv_mult * inv_pressure
        )
        return max(4.0, min(30.0, gap))

    def _apply_momentum_pause(self, orders: list[Order]) -> list[Order]:
        c = self.candidate
        if c.momentum_lookback is None or len(self._mids) <= c.momentum_lookback:
            return orders
        momentum = self._mids[-1] - self._mids[-1 - c.momentum_lookback]
        if momentum <= -c.momentum_threshold:
            return [o for o in orders if o.quantity <= 0]
        if momentum >= c.momentum_threshold:
            return [o for o in orders if o.quantity >= 0]
        return orders

    def _apply_cooldown_filter(self, orders: list[Order], pos: int) -> list[Order]:
        # After reducing a long, do not immediately rebuild it; after reducing
        # a short, do not immediately rebuild the short.
        if pos >= 0:
            return [o for o in orders if o.quantity <= 0]
        return [o for o in orders if o.quantity >= 0]


class _NoopLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


def _fractional_qty(abs_position: int, fraction: float) -> int:
    return max(1, min(abs_position, int(math.ceil(abs_position * fraction))))


def _historical_replay(day: int) -> tuple[str, ReplayEngine]:
    replay = ReplayEngine.from_files(
        price_paths=[DATA_DIR / f"prices_round_3_day_{day}.csv"],
        trade_paths=[DATA_DIR / f"trades_round_3_day_{day}.csv"],
    )
    return f"hist_day_{day}", _filter_hydrogel(replay)


def _official_new_replay() -> tuple[str, ReplayEngine]:
    payload = json.loads((RESULTS_DIR / "extracted_new" / "413315.log").read_text())
    activities = pd.read_csv(io.StringIO(payload["activitiesLog"]), sep=";")
    h = activities[activities["product"] == PRODUCT].sort_values("timestamp")

    trades = pd.DataFrame(payload.get("tradeHistory", []))
    by_ts: dict[int, list[Trade]] = {}
    if not trades.empty:
        bot = trades[
            (trades["symbol"] == PRODUCT)
            & (trades["buyer"] != "SUBMISSION")
            & (trades["seller"] != "SUBMISSION")
        ]
        for _, row in bot.iterrows():
            trade = Trade(
                symbol=PRODUCT,
                price=int(row["price"]),
                quantity=int(row["quantity"]),
                buyer=row.get("buyer") or None,
                seller=row.get("seller") or None,
                timestamp=int(row["timestamp"]),
            )
            by_ts.setdefault(trade.timestamp, []).append(trade)

    steps: list[ReplayStep] = []
    for _, row in h.iterrows():
        raw = {k: ("" if pd.isna(v) else str(v)) for k, v in row.to_dict().items()}
        ts = int(row["timestamp"])
        steps.append(
            ReplayStep(
                day=int(row["day"]),
                timestamp=ts,
                rows_by_product={PRODUCT: raw},
                market_trades={PRODUCT: by_ts.get(ts, [])},
            )
        )
    return "official_new_path", ReplayEngine(steps)


def _filter_hydrogel(replay: ReplayEngine) -> ReplayEngine:
    steps: list[ReplayStep] = []
    for step in replay.iter_steps():
        if PRODUCT not in step.rows_by_product:
            continue
        steps.append(
            ReplayStep(
                day=step.day,
                timestamp=step.timestamp,
                rows_by_product={PRODUCT: step.rows_by_product[PRODUCT]},
                market_trades={PRODUCT: step.market_trades.get(PRODUCT, [])},
            )
        )
    return ReplayEngine(steps)


def _candidates() -> list[Candidate]:
    out = [
        Candidate("current_mu9980_tw30"),
    ]
    for max_pos in (80, 120, 160):
        out.append(Candidate(f"cap{max_pos}", max_pos=max_pos))
    for gap in (12, 15, 18, 22):
        for fraction in (0.5, 1.0):
            out.append(
                Candidate(
                    f"reduce_gap{gap}_frac{fraction}",
                    high_reduce_gap=gap,
                    high_reduce_fraction=fraction,
                    cooldown_ticks=20,
                )
            )
    for trail in (8, 12, 16, 20):
        for fraction in (0.5, 1.0):
            out.append(
                Candidate(
                    f"trail{trail}_frac{fraction}",
                    trail_stop=trail,
                    trail_fraction=fraction,
                    cooldown_ticks=20,
                )
            )
    for lookback in (10, 20, 50):
        for threshold in (8, 12, 16):
            out.append(
                Candidate(
                    f"pause_lb{lookback}_th{threshold}",
                    momentum_lookback=lookback,
                    momentum_threshold=threshold,
                )
            )
    for base_gap in (8, 10, 12):
        for vol_mult in (0.25, 0.5, 0.75):
            for inv_mult in (0.0, 2.0, 4.0):
                out.append(
                    Candidate(
                        f"adaptive_gap{base_gap}_vol{vol_mult}_inv{inv_mult}",
                        high_reduce_gap=base_gap,
                        high_reduce_fraction=1.0,
                        adaptive_gap=True,
                        vol_window=50,
                        vol_mult=vol_mult,
                        spread_mult=0.15,
                        inv_mult=inv_mult,
                    )
                )
    for mu, tw in ((9970, 40), (9970, 45), (9960, 45), (9980, 35)):
        out.append(Candidate(f"param_mu{mu}_tw{tw}", mu=mu, take_width=tw, clear_threshold=1.0))
    return out


def _max_drawdown(values: list[float]) -> float:
    peak = -1e18
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def run() -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    datasets = [_historical_replay(d) for d in (0, 1, 2)]
    datasets.append(_official_new_replay())
    fill = FillModel(FillModelConfig(passive_allocation=0.0, passive_fills_enabled=False))
    rows: list[Row] = []

    for dataset_name, replay in datasets:
        for candidate in _candidates():
            result = BacktestSimulator(HydrogelDDTrader(candidate), fill).run(replay)
            product = result.per_product[PRODUCT]
            pnl_path = [value for _, value in result.pnl_series[PRODUCT]]
            peak = max(pnl_path)
            final = pnl_path[-1]
            rows.append(
                Row(
                    dataset=dataset_name,
                    candidate=candidate.name,
                    final_pnl=float(final),
                    peak_pnl=float(peak),
                    min_pnl=float(min(pnl_path)),
                    max_drawdown=float(_max_drawdown(pnl_path)),
                    final_over_peak=float(final / peak) if peak > 0 else 0.0,
                    final_pos=product.final_position,
                    trades=product.trade_count,
                    taker_qty=product.taker_trade_quantity,
                    maker_qty=product.maker_trade_quantity,
                    near_limit_steps=product.steps_near_limit,
                    avg_markout_20=product.avg_markout_20,
                )
            )
    df = pd.DataFrame([asdict(row) for row in rows])
    df.to_csv(OUT_DIR / "all_results.csv", index=False)
    _summarize(df)
    return df


def _summarize(df: pd.DataFrame) -> None:
    pivot = df.pivot_table(index="candidate", columns="dataset", values="final_pnl")
    dd = df.pivot_table(index="candidate", columns="dataset", values="max_drawdown")
    out = pd.DataFrame(index=pivot.index)
    hist_cols = [c for c in pivot.columns if str(c).startswith("hist_day_")]
    out["hist_mean_pnl"] = pivot[hist_cols].mean(axis=1)
    out["hist_min_pnl"] = pivot[hist_cols].min(axis=1)
    out["official_pnl"] = pivot.get("official_new_path", 0.0)
    out["hist_mean_dd"] = dd[hist_cols].mean(axis=1)
    out["official_dd"] = dd.get("official_new_path", 0.0)
    out["score"] = (
        out["official_pnl"]
        + out["hist_mean_pnl"]
        + 0.4 * out["hist_min_pnl"]
        + 0.25 * out["official_dd"]
        + 0.15 * out["hist_mean_dd"]
    )
    out = out.sort_values("score", ascending=False)
    out.to_csv(OUT_DIR / "ranked_summary.csv")

    lines = [
        "# HYDROGEL Drawdown Sweep",
        "",
        "| candidate | official_pnl | official_dd | hist_mean_pnl | hist_min_pnl | hist_mean_dd | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate, row in out.head(30).iterrows():
        lines.append(
            f"| {candidate} | {row.official_pnl:.1f} | {row.official_dd:.1f} "
            f"| {row.hist_mean_pnl:.1f} | {row.hist_min_pnl:.1f} "
            f"| {row.hist_mean_dd:.1f} | {row.score:.1f} |"
        )
    (OUT_DIR / "report.md").write_text("\n".join(lines))


def main() -> None:
    df = run()
    ranked = pd.read_csv(OUT_DIR / "ranked_summary.csv")
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
    print(ranked.head(25).to_string(index=False))


if __name__ == "__main__":
    main()

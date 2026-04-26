"""HYDROGEL full-round robustness sweep.

The public upload simulator is 100k timestamps, but the final round can be
1M timestamps. This runner evaluates HYDROGEL candidates on the full
historical 0..999900 tapes with a matching 850k->950k terminal ramp.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.backtest.fill_model import FillModel, FillModelConfig
from src.backtest.replay_engine import ReplayEngine, ReplayStep
from src.backtest.simulator import BacktestSimulator
from src.core.config_core import EngineConfig, ProductConfig
from src.core.market_data import MarketDataAdapter
from src.core.primitives.sst import SSTParams, take_clear_make
from src.datamodel import Order, TradingState


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "ROUND_3"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_full_round_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200
RAMP_START = 850_000
RAMP_END = 950_000


@dataclass(frozen=True)
class Candidate:
    name: str
    mode: str = "static"  # static, ewma
    mu: float = 9955.0
    take_width: float = 25.0
    reset_gap: float = 14.0
    rebound_exit_gap: float = 35.0
    rebound_cooldown: int = 10
    early_cap: int = LIMIT
    early_until: int = 0
    ewma_alpha: float = 0.0
    ewma_offset: float = 0.0
    min_fair: float = 9900.0
    max_fair: float = 10050.0


@dataclass(frozen=True)
class Row:
    dataset: str
    candidate: str
    final_pnl: float
    peak_pnl: float
    max_drawdown: float
    final_pos: int
    trades: int
    abs_qty: int
    near_limit_steps: int


class HydrogelFullTrader:
    def __init__(self, candidate: Candidate) -> None:
        self.candidate = candidate
        self.config = EngineConfig(
            products={
                PRODUCT: ProductConfig(
                    position_limit=LIMIT,
                    strategy_name="market_making",
                    fair_value_method="anchor",
                    anchor_price=candidate.mu,
                )
            }
        )
        self.market_data = MarketDataAdapter()
        self.logger = _NoopLogger()
        self.long_mode = False
        self.cooldown_left = 0
        self.ewma: float | None = None

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snap = self.market_data.normalize_state(state).get(PRODUCT)
        if snap is None or snap.mid is None:
            return {PRODUCT: []}, 0, state.traderData

        c = self.candidate
        pos = int(snap.position)
        mid = float(snap.mid)
        ts = int(snap.timestamp)

        if self.ewma is None:
            self.ewma = mid
        else:
            self.ewma = c.ewma_alpha * mid + (1.0 - c.ewma_alpha) * self.ewma

        if self.cooldown_left > 0:
            self.cooldown_left -= 1

        if self.long_mode and pos > 0 and mid >= c.mu + c.rebound_exit_gap and snap.best_bid is not None:
            self.long_mode = False
            self.cooldown_left = c.rebound_cooldown
            return {PRODUCT: [Order(PRODUCT, snap.best_bid.price, -pos)]}, 0, state.traderData

        if pos < 0 and mid <= c.mu - c.reset_gap and snap.best_ask is not None:
            self.long_mode = True
            return {PRODUCT: [Order(PRODUCT, snap.best_ask.price, -pos)]}, 0, state.traderData

        if self.long_mode and pos == 0 and snap.best_ask is not None:
            return {PRODUCT: [Order(PRODUCT, snap.best_ask.price, 40)]}, 0, state.traderData

        cap = min(c.early_cap if ts < c.early_until else LIMIT, LIMIT)
        cap = min(cap, _scaled_cap(LIMIT, ts))
        fair = self._fair(pos, cap)
        orders = list(
            take_clear_make(
                product=PRODUCT,
                fair_value=fair,
                snapshot=snap,
                position=pos,
                position_limit=cap,
                params=SSTParams(
                    take_width=c.take_width,
                    clear_threshold=1.0,
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
            ).orders
        )
        if self.long_mode or self.cooldown_left > 0:
            orders = [order for order in orders if order.quantity >= 0]
        return {PRODUCT: orders}, 0, state.traderData

    def _fair(self, pos: int, cap: int) -> float:
        c = self.candidate
        if c.mode == "ewma" and self.ewma is not None:
            base = max(c.min_fair, min(c.max_fair, self.ewma + c.ewma_offset))
        else:
            base = c.mu
        return base - (pos / max(cap, 1)) * 2.0


class _NoopLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


def _scaled_cap(base_cap: int, ts: int) -> int:
    if ts < RAMP_START:
        return base_cap
    if ts >= RAMP_END:
        return 1
    return max(1, int(base_cap * (RAMP_END - ts) / (RAMP_END - RAMP_START)))


def _historical_replay(day: int) -> tuple[str, ReplayEngine]:
    replay = ReplayEngine.from_files(
        price_paths=[DATA_DIR / f"prices_round_3_day_{day}.csv"],
        trade_paths=[DATA_DIR / f"trades_round_3_day_{day}.csv"],
    )
    steps = []
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
    return f"hist_day_{day}", ReplayEngine(steps)


def _max_drawdown(values: list[float]) -> float:
    peak = -1e18
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def _candidates() -> list[Candidate]:
    out: list[Candidate] = []
    for mu in (9945, 9950, 9955, 9960, 9965, 9970, 9980, 9990):
        for take in (18, 22, 25, 30, 35):
            for gap in (10, 14, 18, 22):
                out.append(Candidate(f"static_mu{mu}_tw{take}_gap{gap}", mu=mu, take_width=take, reset_gap=gap))
    for cap in (80, 120, 160):
        for until in (10_000, 15_000, 25_000, 50_000):
            out.append(Candidate(f"static_mu9955_tw25_gap14_cap{cap}_u{until}", early_cap=cap, early_until=until))
    for alpha in (0.0005, 0.001, 0.002, 0.005):
        for offset in (-30, -20, -10, 0, 10):
            for take in (18, 25, 35):
                out.append(
                    Candidate(
                        f"ewma_a{alpha}_off{offset}_tw{take}",
                        mode="ewma",
                        ewma_alpha=alpha,
                        ewma_offset=offset,
                        take_width=take,
                        reset_gap=14,
                    )
                )
    return out


def run() -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fill = FillModel(FillModelConfig(passive_allocation=0.0, passive_fills_enabled=False))
    rows = []
    for dataset, replay in [_historical_replay(day) for day in (0, 1, 2)]:
        for candidate in _candidates():
            result = BacktestSimulator(HydrogelFullTrader(candidate), fill).run(replay)
            product = result.per_product[PRODUCT]
            pnl_path = [value for _, value in result.pnl_series[PRODUCT]]
            rows.append(
                Row(
                    dataset=dataset,
                    candidate=candidate.name,
                    final_pnl=float(pnl_path[-1]),
                    peak_pnl=float(max(pnl_path)),
                    max_drawdown=float(_max_drawdown(pnl_path)),
                    final_pos=product.final_position,
                    trades=product.trade_count,
                    abs_qty=product.buy_trade_quantity + product.sell_trade_quantity,
                    near_limit_steps=product.steps_near_limit,
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
    out["mean_pnl"] = pivot.mean(axis=1)
    out["min_pnl"] = pivot.min(axis=1)
    out["max_pnl"] = pivot.max(axis=1)
    out["mean_dd"] = dd.mean(axis=1)
    out["worst_dd"] = dd.min(axis=1)
    out["score"] = out["mean_pnl"] + 0.7 * out["min_pnl"] + 0.15 * out["worst_dd"]
    out = out.sort_values("score", ascending=False)
    out.to_csv(OUT_DIR / "ranked_summary.csv")


def main() -> None:
    df = run()
    ranked = pd.read_csv(OUT_DIR / "ranked_summary.csv")
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
    print(ranked.head(40).to_string(index=False))


if __name__ == "__main__":
    main()

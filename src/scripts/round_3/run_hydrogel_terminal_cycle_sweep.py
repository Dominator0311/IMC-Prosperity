"""HYDROGEL terminal-cycle optimization sweep.

Follow-up after the official rebound run. The rebound state improved PnL and
ended with +72 HYDROGEL, which was profitable on the official path. This sweep
tests whether that terminal long exposure should be deliberate:

- keep the short-cover/rebound state from the live strategy
- optionally target a larger terminal long after the late short cover
- optionally reduce early full-short exposure
"""

from __future__ import annotations

import io
import json
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
from src.datamodel import Order, Trade, TradingState


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "ROUND_3"
RESULTS_DIR = REPO_ROOT / "outputs" / "round_3" / "Results"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_terminal_cycle_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200


@dataclass(frozen=True)
class Candidate:
    name: str
    mu: float = 9955.0
    take_width: float = 25.0
    reset_gap: float = 14.0
    rebound_exit_gap: float = 35.0
    rebound_cooldown: int = 10
    early_cap: int = LIMIT
    early_until: int = 0
    terminal_start: int = 85_000
    terminal_long_target: int = 0
    terminal_entry_mid: float = 9935.0
    terminal_exit_mid: float | None = None
    terminal_cross_size: int = 40


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


class HydrogelTerminalTrader:
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

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snap = self.market_data.normalize_state(state).get(PRODUCT)
        if snap is None or snap.mid is None:
            return {PRODUCT: []}, 0, state.traderData

        c = self.candidate
        pos = int(snap.position)
        mid = float(snap.mid)
        ts = int(snap.timestamp)
        if self.cooldown_left > 0:
            self.cooldown_left -= 1

        terminal = self._terminal_order(snap, pos, mid, ts)
        if terminal is not None:
            return {PRODUCT: [terminal]}, 0, state.traderData

        if (
            pos > 0
            and self.long_mode
            and mid >= c.mu + c.rebound_exit_gap
            and snap.best_bid is not None
        ):
            self.long_mode = False
            self.cooldown_left = c.rebound_cooldown
            return {PRODUCT: [Order(PRODUCT, snap.best_bid.price, -pos)]}, 0, state.traderData

        if (
            pos < 0
            and mid <= c.mu - c.reset_gap
            and snap.best_ask is not None
        ):
            self.long_mode = True
            return {PRODUCT: [Order(PRODUCT, snap.best_ask.price, -pos)]}, 0, state.traderData

        if self.long_mode and pos == 0 and snap.best_ask is not None:
            return {PRODUCT: [Order(PRODUCT, snap.best_ask.price, 40)]}, 0, state.traderData

        cap = min(c.early_cap if ts < c.early_until else LIMIT, LIMIT)
        cap = min(cap, scaled_cap(LIMIT, ts))
        fair = c.mu - (pos / max(cap, 1)) * 2.0
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

    def _terminal_order(self, snap, pos: int, mid: float, ts: int) -> Order | None:
        c = self.candidate
        if c.terminal_long_target <= 0 or ts < c.terminal_start:
            return None
        if c.terminal_exit_mid is not None and mid >= c.terminal_exit_mid and pos > 0:
            if snap.best_bid is not None:
                return Order(PRODUCT, snap.best_bid.price, -pos)
            return None
        if mid <= c.terminal_entry_mid and pos < c.terminal_long_target:
            if snap.best_ask is None:
                return None
            qty = min(c.terminal_cross_size, c.terminal_long_target - pos)
            return Order(PRODUCT, snap.best_ask.price, qty)
        return None


class _NoopLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


def _historical_replay(day: int) -> tuple[str, ReplayEngine]:
    replay = ReplayEngine.from_files(
        price_paths=[DATA_DIR / f"prices_round_3_day_{day}.csv"],
        trade_paths=[DATA_DIR / f"trades_round_3_day_{day}.csv"],
    )
    return f"hist_day_{day}", _filter_hydrogel(replay)


def _official_replay() -> tuple[str, ReplayEngine]:
    log_path = RESULTS_DIR / "extracted_rebound" / "420533.log"
    if not log_path.exists():
        log_path = RESULTS_DIR / "extracted_aggressive_new" / "418798.log"
    payload = json.loads(log_path.read_text())
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
    steps = []
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
    return "official_path", ReplayEngine(steps)


def _filter_hydrogel(replay: ReplayEngine) -> ReplayEngine:
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
    return ReplayEngine(steps)


def _candidates() -> list[Candidate]:
    out = [Candidate("rebound_baseline")]
    for cap in (80, 120, 160):
        for until in (5_000, 10_000, 15_000):
            out.append(Candidate(f"early_cap{cap}_until{until}", early_cap=cap, early_until=until))
    for start in (82_000, 85_000, 88_000, 90_000):
        for entry_mid in (9928, 9932, 9936, 9940, 9945):
            for target in (80, 120, 160, 200):
                out.append(
                    Candidate(
                        f"terminal_s{start}_m{entry_mid}_t{target}",
                        terminal_start=start,
                        terminal_entry_mid=float(entry_mid),
                        terminal_long_target=target,
                    )
                )
    for cap in (80, 120):
        for start in (85_000, 88_000):
            for entry_mid in (9932, 9936, 9940):
                for target in (120, 160, 200):
                    out.append(
                        Candidate(
                            f"combo_cap{cap}_s{start}_m{entry_mid}_t{target}",
                            early_cap=cap,
                            early_until=15_000,
                            terminal_start=start,
                            terminal_entry_mid=float(entry_mid),
                            terminal_long_target=target,
                        )
                    )
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
    datasets.append(_official_replay())
    fill = FillModel(FillModelConfig(passive_allocation=0.0, passive_fills_enabled=False))
    rows = []
    for dataset_name, replay in datasets:
        for candidate in _candidates():
            result = BacktestSimulator(HydrogelTerminalTrader(candidate), fill).run(replay)
            product = result.per_product[PRODUCT]
            pnl_path = [value for _, value in result.pnl_series[PRODUCT]]
            rows.append(
                Row(
                    dataset=dataset_name,
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
    pos = df.pivot_table(index="candidate", columns="dataset", values="final_pos")
    hist_cols = [c for c in pivot.columns if str(c).startswith("hist_day_")]
    out = pd.DataFrame(index=pivot.index)
    out["hist_mean_pnl"] = pivot[hist_cols].mean(axis=1)
    out["hist_min_pnl"] = pivot[hist_cols].min(axis=1)
    out["official_pnl"] = pivot["official_path"]
    out["hist_mean_dd"] = dd[hist_cols].mean(axis=1)
    out["official_dd"] = dd["official_path"]
    out["official_final_pos"] = pos["official_path"]
    out["score"] = (
        out["official_pnl"]
        + out["hist_mean_pnl"]
        + 0.4 * out["hist_min_pnl"]
        + 0.25 * out["official_dd"]
        + 0.15 * out["hist_mean_dd"]
        - 0.5 * (out["official_final_pos"].abs() - 72).clip(lower=0)
    )
    out = out.sort_values("score", ascending=False)
    out.to_csv(OUT_DIR / "ranked_summary.csv")


def main() -> None:
    df = run()
    ranked = pd.read_csv(OUT_DIR / "ranked_summary.csv")
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
    print(ranked.head(35).to_string(index=False))


if __name__ == "__main__":
    main()

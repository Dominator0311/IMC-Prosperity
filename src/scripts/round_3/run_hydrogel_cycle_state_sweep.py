"""HYDROGEL stateful cycle-leg sweep.

This tests the next hypothesis after `mu=9955/take_width=25/reset_gap=14`:
the remaining alpha gap is not just a static anchor tweak. The current bot
covers its short around the lower band, then misses the rebound leg before
shorting the upper band again. This sweep adds an explicit post-cover long
cycle:

1. Short high deviations with the existing static MR rule.
2. Cover short at the lower reset band.
3. Optionally buy a rebound long after the cover.
4. Exit that long at an upper band.
5. Resume the normal short cycle.
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
DATA_DIR = REPO_ROOT / "ROUND_3"
RESULTS_DIR = REPO_ROOT / "outputs" / "round_3" / "Results"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_cycle_state_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200


@dataclass(frozen=True)
class Candidate:
    name: str
    mu: float = 9955.0
    take_width: float = 25.0
    reset_gap: float = 14.0
    long_entry: str = "none"  # none, immediate, rebound
    rebound_trigger: float = 6.0
    long_size: int = 100
    long_exit_gap: float = 18.0
    long_stop_gap: float | None = None
    long_timeout: int | None = None
    cooldown_after_long: int = 0
    initial_scale_start: int = 0
    initial_cap: int = LIMIT


@dataclass(frozen=True)
class Row:
    dataset: str
    candidate: str
    final_pnl: float
    peak_pnl: float
    max_drawdown: float
    final_pos: int
    trades: int
    taker_qty: int
    maker_qty: int
    near_limit_steps: int
    avg_markout_20: float | None


class HydrogelCycleTrader:
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
        self._last_short_reset_mid: float | None = None
        self._long_mode: bool = False
        self._long_entry_ts: int | None = None
        self._cooldown_left: int = 0

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snap = self.market_data.normalize_state(state).get(PRODUCT)
        if snap is None or snap.mid is None:
            return {PRODUCT: []}, 0, state.traderData
        return {PRODUCT: self._orders(snap)}, 0, state.traderData

    def _orders(self, snap: NormalizedSnapshot) -> list[Order]:
        c = self.candidate
        pos = int(snap.position)
        mid = float(snap.mid)
        ts = int(snap.timestamp)

        if self._cooldown_left > 0:
            self._cooldown_left -= 1

        order = self._long_exit_order(snap, pos, mid, ts)
        if order is not None:
            return [order]

        order = self._cycle_reset_order(snap, pos, mid)
        if order is not None:
            return [order]

        order = self._long_entry_order(snap, pos, mid, ts)
        if order is not None:
            return [order]

        cap = min(c.initial_cap if ts < c.initial_scale_start else LIMIT, LIMIT)
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
        if self._long_mode or self._cooldown_left > 0:
            # While harvesting/just after harvesting the rebound long, avoid
            # immediately rebuilding the short that caused the old flat zone.
            orders = [o for o in orders if o.quantity >= 0]
        return orders

    def _cycle_reset_order(
        self,
        snap: NormalizedSnapshot,
        pos: int,
        mid: float,
    ) -> Order | None:
        c = self.candidate
        if pos > 0:
            return None
        if pos < 0 and mid <= c.mu - c.reset_gap and snap.best_ask is not None:
            self._last_short_reset_mid = mid
            if c.long_entry == "immediate":
                self._long_mode = True
            return Order(PRODUCT, snap.best_ask.price, -pos)
        return None

    def _long_entry_order(
        self,
        snap: NormalizedSnapshot,
        pos: int,
        mid: float,
        ts: int,
    ) -> Order | None:
        c = self.candidate
        if c.long_entry == "none" or c.long_size <= 0 or pos != 0:
            return None
        if self._last_short_reset_mid is None or snap.best_ask is None:
            return None
        if c.long_entry == "immediate":
            self._long_mode = True
        elif mid >= self._last_short_reset_mid + c.rebound_trigger:
            self._long_mode = True
        if not self._long_mode:
            return None
        self._long_entry_ts = ts
        qty = min(c.long_size, LIMIT)
        return Order(PRODUCT, snap.best_ask.price, qty)

    def _long_exit_order(
        self,
        snap: NormalizedSnapshot,
        pos: int,
        mid: float,
        ts: int,
    ) -> Order | None:
        c = self.candidate
        if pos <= 0 or not self._long_mode:
            return None
        should_exit = mid >= c.mu + c.long_exit_gap
        if (
            not should_exit
            and c.long_stop_gap is not None
            and self._last_short_reset_mid is not None
        ):
            should_exit = mid <= self._last_short_reset_mid - c.long_stop_gap
        if (
            not should_exit
            and c.long_timeout is not None
            and self._long_entry_ts is not None
        ):
            should_exit = ts - self._long_entry_ts >= c.long_timeout
        if should_exit and snap.best_bid is not None:
            self._long_mode = False
            self._last_short_reset_mid = None
            self._long_entry_ts = None
            self._cooldown_left = c.cooldown_after_long
            return Order(PRODUCT, snap.best_bid.price, -pos)
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
    log_path = RESULTS_DIR / "extracted_aggressive_new" / "418798.log"
    if not log_path.exists():
        log_path = RESULTS_DIR / "extracted_aggressive" / "417423.log"
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
    return "official_path", ReplayEngine(steps)


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
    out = [Candidate("baseline_9955_25_14")]

    for entry in ("immediate", "rebound"):
        triggers = (0,) if entry == "immediate" else (2, 4, 6, 8, 10, 12)
        for trigger in triggers:
            for size in (40, 80, 120, 160, 200):
                for exit_gap in (14, 18, 22, 26, 30, 35):
                    out.append(
                        Candidate(
                            f"{entry}_tr{trigger}_sz{size}_exit{exit_gap}",
                            long_entry=entry,
                            rebound_trigger=float(trigger),
                            long_size=size,
                            long_exit_gap=float(exit_gap),
                        )
                    )
                    out.append(
                        Candidate(
                            f"{entry}_tr{trigger}_sz{size}_exit{exit_gap}_cd10",
                            long_entry=entry,
                            rebound_trigger=float(trigger),
                            long_size=size,
                            long_exit_gap=float(exit_gap),
                            cooldown_after_long=10,
                        )
                    )

    for cap in (80, 120, 160):
        for until in (5_000, 10_000, 15_000):
            out.append(
                Candidate(
                    f"baseline_initial_cap{cap}_until{until}",
                    initial_cap=cap,
                    initial_scale_start=until,
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

    rows: list[Row] = []
    for dataset_name, replay in datasets:
        for candidate in _candidates():
            result = BacktestSimulator(HydrogelCycleTrader(candidate), fill).run(replay)
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
    hist_cols = [c for c in pivot.columns if str(c).startswith("hist_day_")]

    summary = pd.DataFrame(index=pivot.index)
    summary["hist_mean_pnl"] = pivot[hist_cols].mean(axis=1)
    summary["hist_min_pnl"] = pivot[hist_cols].min(axis=1)
    summary["official_pnl"] = pivot["official_path"]
    summary["hist_mean_dd"] = dd[hist_cols].mean(axis=1)
    summary["official_dd"] = dd["official_path"]
    summary["score"] = (
        summary["official_pnl"]
        + summary["hist_mean_pnl"]
        + 0.4 * summary["hist_min_pnl"]
        + 0.25 * summary["official_dd"]
        + 0.15 * summary["hist_mean_dd"]
    )
    summary = summary.sort_values("score", ascending=False)
    summary.to_csv(OUT_DIR / "ranked_summary.csv")

    lines = [
        "# HYDROGEL Cycle-State Sweep",
        "",
        "| candidate | official_pnl | official_dd | hist_mean_pnl | hist_min_pnl | hist_mean_dd | score |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate, row in summary.head(40).iterrows():
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
    print(ranked.head(30).to_string(index=False))


if __name__ == "__main__":
    main()

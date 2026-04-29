"""HYDROGEL runner/reset variant sweep.

Focused follow-up after the aggressive HYDROGEL-only official result.

The aggressive submission (`mu=9960, take_width=25, reset_gap=18`) improved
official PnL, but went flat from roughly 55K-69K ticks because the lower-band
short reset covered the whole position. This script tests nearby variants that
keep a residual "runner" after a profitable short reset.
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
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_runner_variant_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200


@dataclass(frozen=True)
class Candidate:
    name: str
    mu: float
    take_width: float
    reset_gap: float
    long_reset_fraction: float = 1.0
    short_reset_fraction: float = 1.0
    clear_threshold: float = 1.0
    cooldown_ticks: int = 0
    rebound_reentry: bool = False
    rebound_trigger: float = 0.0
    rebound_size: int = 0
    max_pos: int = LIMIT


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


class HydrogelRunnerTrader:
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
        self._cooldown_left = 0
        self._last_short_reset_mid: float | None = None

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snap = self.market_data.normalize_state(state).get(PRODUCT)
        if snap is None or snap.mid is None:
            return {PRODUCT: []}, 0, state.traderData

        orders = self._orders(snap)
        return {PRODUCT: orders}, 0, state.traderData

    def _orders(self, snap: NormalizedSnapshot) -> list[Order]:
        c = self.candidate
        pos = int(snap.position)
        mid = float(snap.mid)

        if self._cooldown_left > 0:
            self._cooldown_left -= 1

        reset = self._reset_order(snap, pos, mid)
        if reset is not None:
            if c.cooldown_ticks > 0:
                self._cooldown_left = c.cooldown_ticks
            return [reset]

        rebound = self._rebound_order(snap, pos, mid)
        if rebound is not None:
            return [rebound]

        cap = min(c.max_pos, scaled_cap(LIMIT, snap.timestamp))
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
        if self._cooldown_left > 0:
            if pos >= 0:
                orders = [o for o in orders if o.quantity <= 0]
            else:
                orders = [o for o in orders if o.quantity >= 0]
        return orders

    def _reset_order(
        self,
        snap: NormalizedSnapshot,
        pos: int,
        mid: float,
    ) -> Order | None:
        c = self.candidate
        if pos > 0 and mid >= c.mu + c.reset_gap and snap.best_bid is not None:
            qty = _fractional_qty(pos, c.long_reset_fraction)
            return Order(PRODUCT, snap.best_bid.price, -qty)
        if pos < 0 and mid <= c.mu - c.reset_gap and snap.best_ask is not None:
            qty = _fractional_qty(-pos, c.short_reset_fraction)
            self._last_short_reset_mid = mid
            return Order(PRODUCT, snap.best_ask.price, qty)
        return None

    def _rebound_order(
        self,
        snap: NormalizedSnapshot,
        pos: int,
        mid: float,
    ) -> Order | None:
        c = self.candidate
        if not c.rebound_reentry or c.rebound_size <= 0:
            return None
        if self._last_short_reset_mid is None or snap.best_bid is None:
            return None
        if pos != 0:
            return None
        if mid >= self._last_short_reset_mid + c.rebound_trigger:
            self._last_short_reset_mid = None
            return Order(PRODUCT, snap.best_bid.price, -c.rebound_size)
        return None


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


def _official_replay() -> tuple[str, ReplayEngine]:
    log_path = RESULTS_DIR / "extracted_aggressive" / "417423.log"
    if not log_path.exists():
        log_path = RESULTS_DIR / "extracted_new" / "413315.log"
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
    out = [
        Candidate("aggressive_full_reset", mu=9960, take_width=25, reset_gap=18),
    ]

    for frac in (0.1, 0.2, 0.25, 0.35, 0.5, 0.65, 0.8):
        out.append(
            Candidate(
                f"aggressive_short_runner_{frac}",
                mu=9960,
                take_width=25,
                reset_gap=18,
                long_reset_fraction=1.0,
                short_reset_fraction=frac,
            )
        )

    for mu in (9950, 9955, 9960, 9965, 9970):
        for tw in (20, 25, 30):
            for gap in (14, 16, 18, 20):
                for frac in (0.2, 0.25, 0.35, 0.5, 1.0):
                    out.append(
                        Candidate(
                            f"grid_mu{mu}_tw{tw}_gap{gap}_sf{frac}",
                            mu=mu,
                            take_width=tw,
                            reset_gap=gap,
                            long_reset_fraction=1.0,
                            short_reset_fraction=frac,
                        )
                    )

    for trigger in (6, 10, 14):
        for size in (20, 40, 60):
            out.append(
                Candidate(
                    f"rebound_mu9960_tw25_gap18_tr{trigger}_sz{size}",
                    mu=9960,
                    take_width=25,
                    reset_gap=18,
                    short_reset_fraction=1.0,
                    rebound_reentry=True,
                    rebound_trigger=float(trigger),
                    rebound_size=size,
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
            result = BacktestSimulator(HydrogelRunnerTrader(candidate), fill).run(replay)
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
        "# HYDROGEL Runner Variant Sweep",
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

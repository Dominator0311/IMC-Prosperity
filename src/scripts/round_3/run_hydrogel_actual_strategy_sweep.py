"""HYDROGEL actual-strategy confirmation sweep.

This is the stricter follow-up to ``run_hydrogel_family_sweep``. The family
sweep answers "what shape of alpha looks promising?" This script answers
"does that shape still work when routed through the repo's real
BacktestSimulator and SST execution primitive?"

It deliberately tests only HYDROGEL_PACK so VELVET/options do not obscure the
asset-level result.
"""

from __future__ import annotations

import csv
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
from src.datamodel import Order, TradingState


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "ROUND_3"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_actual_strategy_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200


@dataclass(frozen=True)
class HydrogelCandidate:
    name: str
    mu: float
    take_width: float
    clear_threshold: float
    clear_width: float
    default_edge: float
    join_edge: float
    quote_size: int
    max_taker_size: int
    skew_strength: float
    profit_band: float | None = None
    profit_min_pos: int = 30


@dataclass(frozen=True)
class SweepRow:
    candidate: str
    fill_allocation: float
    pnl: float
    final_pos: int
    trade_count: int
    taker_qty: int
    maker_qty: int
    buy_qty: int
    sell_qty: int
    near_limit_steps: int
    avg_markout_1: float | None
    avg_markout_5: float | None
    avg_markout_20: float | None


class HydrogelOnlyTrader:
    """Tiny trader wrapper so BacktestSimulator can run HYDROGEL in isolation."""

    def __init__(self, candidate: HydrogelCandidate) -> None:
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

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        snapshot = self.market_data.normalize_state(state).get(PRODUCT)
        if snapshot is None:
            return {PRODUCT: []}, 0, state.traderData
        orders = _candidate_orders(snapshot, self.candidate)
        return {PRODUCT: orders}, 0, state.traderData


class _NoopLogger:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, event: dict) -> None:
        self.events.append(event)


def _candidate_orders(
    snapshot: NormalizedSnapshot,
    candidate: HydrogelCandidate,
) -> list[Order]:
    if snapshot.mid is None:
        return []

    if (
        candidate.profit_band is not None
        and abs(float(snapshot.mid) - candidate.mu) < candidate.profit_band
        and abs(snapshot.position) >= candidate.profit_min_pos
    ):
        if snapshot.position > 0 and snapshot.best_bid is not None:
            return [Order(PRODUCT, snapshot.best_bid.price, -snapshot.position)]
        if snapshot.position < 0 and snapshot.best_ask is not None:
            return [Order(PRODUCT, snapshot.best_ask.price, -snapshot.position)]
        return []

    cap = scaled_cap(LIMIT, snapshot.timestamp)
    fair = _fair(candidate, snapshot.position, cap)
    params = SSTParams(
        take_width=candidate.take_width,
        clear_threshold=candidate.clear_threshold,
        clear_width=candidate.clear_width,
        default_edge=candidate.default_edge,
        disregard_edge=1.0,
        join_edge=candidate.join_edge,
        default_quote_size=candidate.quote_size,
        max_taker_size=candidate.max_taker_size,
        prevent_adverse=False,
        quote_inside_wall=False,
        wall_min_volume=10,
    )
    return take_clear_make(
        product=PRODUCT,
        fair_value=fair,
        snapshot=snapshot,
        position=snapshot.position,
        position_limit=cap,
        params=params,
    ).orders


def _fair(candidate: HydrogelCandidate, position: int, cap: int) -> float:
    if cap <= 0:
        return candidate.mu
    return candidate.mu - (position / cap) * candidate.skew_strength


def _hydrogel_replay(day: int | None = None) -> ReplayEngine:
    days = (0, 1, 2) if day is None else (day,)
    steps: list[ReplayStep] = []
    for d in days:
        price_path = DATA_DIR / f"prices_round_3_day_{d}.csv"
        trade_path = DATA_DIR / f"trades_round_3_day_{d}.csv"
        day_replay = ReplayEngine.from_files(
            price_paths=[price_path],
            trade_paths=[trade_path],
        )
        for step in day_replay.iter_steps():
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


def _candidates() -> list[HydrogelCandidate]:
    candidates: list[HydrogelCandidate] = [
        HydrogelCandidate(
            name="current_v7_like",
            mu=9990,
            take_width=25,
            clear_threshold=0.9,
            clear_width=2,
            default_edge=3,
            join_edge=3,
            quote_size=20,
            max_taker_size=200,
            skew_strength=2,
            profit_band=10,
            profit_min_pos=30,
        )
    ]
    for mu in (9960, 9980, 9990, 10000):
        for take_width in (25, 30, 45):
            for clear_threshold in (0.9, 1.0):
                candidates.append(
                    HydrogelCandidate(
                        name=f"wide_static_mu{mu}_tw{take_width}_ct{clear_threshold}",
                        mu=mu,
                        take_width=take_width,
                        clear_threshold=clear_threshold,
                        clear_width=2,
                        default_edge=3,
                        join_edge=3,
                        quote_size=20,
                        max_taker_size=200,
                        skew_strength=2,
                    )
                )
    return candidates


def run() -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    replay = _hydrogel_replay()
    rows: list[SweepRow] = []
    for fill_allocation in (0.0, 0.15, 0.3):
        fill_model = FillModel(
            FillModelConfig(
                passive_allocation=fill_allocation,
                passive_fills_enabled=fill_allocation > 0,
            )
        )
        for candidate in _candidates():
            result = BacktestSimulator(
                HydrogelOnlyTrader(candidate),
                fill_model,
            ).run(replay)
            product = result.per_product[PRODUCT]
            rows.append(
                SweepRow(
                    candidate=candidate.name,
                    fill_allocation=fill_allocation,
                    pnl=product.pnl,
                    final_pos=product.final_position,
                    trade_count=product.trade_count,
                    taker_qty=product.taker_trade_quantity,
                    maker_qty=product.maker_trade_quantity,
                    buy_qty=product.buy_trade_quantity,
                    sell_qty=product.sell_trade_quantity,
                    near_limit_steps=product.steps_near_limit,
                    avg_markout_1=product.avg_markout_1,
                    avg_markout_5=product.avg_markout_5,
                    avg_markout_20=product.avg_markout_20,
                )
            )
    df = pd.DataFrame([asdict(row) for row in rows])
    df.to_csv(OUT_DIR / "all_results.csv", index=False)
    ranked = df.sort_values(["fill_allocation", "pnl"], ascending=[True, False])
    ranked.to_csv(OUT_DIR / "ranked_results.csv", index=False)
    _write_report(df)
    return df


def _write_report(df: pd.DataFrame) -> None:
    lines = [
        "# HYDROGEL Actual Strategy Sweep",
        "",
        "Runs HYDROGEL-only candidates through BacktestSimulator using the real SST primitive.",
        "",
    ]
    for allocation in sorted(df["fill_allocation"].unique()):
        subset = df[df["fill_allocation"] == allocation].sort_values("pnl", ascending=False)
        lines += [
            f"## Passive allocation {allocation}",
            "",
            "| candidate | pnl | pos | trades | taker_qty | maker_qty | mk20 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for _, row in subset.head(12).iterrows():
            mk20 = row["avg_markout_20"]
            mk20_str = "" if pd.isna(mk20) else f"{mk20:.2f}"
            lines.append(
                f"| {row['candidate']} | {row['pnl']:.1f} | {int(row['final_pos'])} "
                f"| {int(row['trade_count'])} | {int(row['taker_qty'])} "
                f"| {int(row['maker_qty'])} | {mk20_str} |"
            )
        lines.append("")
    (OUT_DIR / "report.md").write_text("\n".join(lines))


def main() -> None:
    df = run()
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
    print(
        df.sort_values("pnl", ascending=False)
        .head(20)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()

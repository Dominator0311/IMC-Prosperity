"""Smoke evaluation of the 5 new PEPPER candidates against real tapes.

Routes each candidate through the existing ReplayEngine + BacktestSimulator
against all 3 real training days. Reports PEPPER PnL per day + cross-day
stats. This is NOT a full official-calibrated score — local sim is still
the broken sim — but it confirms each strategy runs end-to-end without
crashing, respects position limits, and doesn't blow up.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.eval_pepper_candidates

Exit code is 0 iff every candidate completes without exception.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from statistics import mean, pstdev

from src.backtest.metrics import SimulationResult
from src.backtest.replay_engine import ReplayEngine
from src.backtest.simulator import BacktestSimulator
from src.core.config import EngineConfig, round1_h1_engine_config
from src.core.state_store import InMemoryStateStore
from src.strategies.base import BaseStrategy, StrategyContext
from src.strategies.round_1_pepper_candidates import (
    CANDIDATE_FACTORIES,
    PEPPER,
    pepper_product_config,
)
from src.trader import Trader

ASH = "ASH_COATED_OSMIUM"
DATA = Path("data/raw/round_1")
FOLDS = (-2, -1, 0)


class _PerProductStrategy(BaseStrategy):
    """Routes intents by product so ASH and PEPPER can use different strategies."""

    def __init__(self, by_product: dict[str, BaseStrategy]) -> None:
        self.by_product = by_product

    def generate_intent(self, ctx: StrategyContext):  # type: ignore[override]
        return self.by_product[ctx.product].generate_intent(ctx)


def _base_engine() -> EngineConfig:
    """H1 base (live market_making) + PEPPER ProductConfig upgraded to our candidate cfg."""
    base = round1_h1_engine_config()
    products = dict(base.products)
    products[PEPPER] = pepper_product_config()
    return EngineConfig(
        state_version=base.state_version,
        max_trader_data_chars=base.max_trader_data_chars,
        diagnostics_verbosity=base.diagnostics_verbosity,
        products=products,
        scanner_config=replace(base.scanner_config, enabled=False),
        residual_config=base.residual_config,
    )


def _load_day_replay(day: int) -> ReplayEngine:
    return ReplayEngine.from_files(
        price_paths=[DATA / f"prices_round_1_day_{day}.csv"],
        trade_paths=[DATA / f"trades_round_1_day_{day}.csv"],
    )


def _run_one(name: str, replay: ReplayEngine) -> SimulationResult:
    engine = _base_engine()
    trader = Trader(
        config=engine,
        state_store=InMemoryStateStore(
            version=engine.state_version,
            max_chars=engine.max_trader_data_chars,
        ),
    )
    # Replace the market_making entry with a per-product router that
    # sends ASH to the original market_making strategy and PEPPER to
    # the candidate under test.
    original_mm = trader.strategies["market_making"]
    fve, sig = trader.fair_value_engine, trader.signal_engine
    candidate = CANDIDATE_FACTORIES[name](fve, sig)
    trader.strategies["market_making"] = _PerProductStrategy(
        {ASH: original_mm, PEPPER: candidate}
    )
    return BacktestSimulator(trader=trader).run(replay)


def main() -> int:
    replays = {d: _load_day_replay(d) for d in FOLDS}
    rows: list[dict] = []
    failures: list[str] = []
    for name in CANDIDATE_FACTORIES:
        per_day: dict[int, dict[str, float]] = {}
        try:
            for day, replay in replays.items():
                result = _run_one(name, replay)
                pep_pnl = result.per_product[PEPPER].pnl
                ash_pnl = result.per_product[ASH].pnl
                per_day[day] = {
                    "pep": pep_pnl,
                    "ash": ash_pnl,
                    "total": result.total_pnl,
                }
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            print(f"!! {name}: FAILED — {exc}")
            continue
        pep_series = [per_day[d]["pep"] for d in FOLDS]
        rows.append(
            {
                "name": name,
                "mean_pep": mean(pep_series),
                "min_pep": min(pep_series),
                "max_pep": max(pep_series),
                "std_pep": pstdev(pep_series),
                "day_-2": per_day[-2]["pep"],
                "day_-1": per_day[-1]["pep"],
                "day_0": per_day[0]["pep"],
            }
        )

    print("\n" + "=" * 78)
    print(f"{'candidate':<30s}{'mean':>10s}{'min':>10s}{'max':>10s}{'d-2':>10s}{'d-1':>10s}{'d0':>10s}")
    print("-" * 78)
    for r in sorted(rows, key=lambda r: -r["mean_pep"]):
        print(
            f"{r['name']:<30s}{r['mean_pep']:>+10.0f}{r['min_pep']:>+10.0f}"
            f"{r['max_pep']:>+10.0f}{r['day_-2']:>+10.0f}"
            f"{r['day_-1']:>+10.0f}{r['day_0']:>+10.0f}"
        )
    print("=" * 78)
    if failures:
        print(f"\n{len(failures)} failures:")
        for f in failures:
            print(f"  {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

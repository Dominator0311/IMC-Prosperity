"""Phase 6.5: Test combined EMERALDS + TOMATOES finalist pairings.

Since EMERALDS produced zero fills under the current local replay / fill
model, all pairings use baseline EMERALDS.  The 3 TOMATOES candidates
drive the ranking.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.backtest.replay_engine import ReplayEngine
from src.backtest.simulator import BacktestSimulator
from src.core.config import EngineConfig, default_engine_config
from src.trader import Trader

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")

# Phase 6 shortlisted TOMATOES candidates (estimator, param overrides)
CANDIDATES: list[tuple[str, dict]] = [
    ("C1: wall_mid taker=0.5", {"fair_value_method": "wall_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 0.5, "maker_edge": 1.0}),
    ("C2: wall_mid taker=1.0", {"fair_value_method": "wall_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 1.0, "maker_edge": 1.0}),
    ("C3: rolling_mid h=32", {"fair_value_method": "rolling_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 1.5, "maker_edge": 2.0, "history_length": 32}),
]


def main() -> None:
    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    engine = default_engine_config()
    base_tomatoes = engine.product_config("TOMATOES")

    # Baseline run
    baseline_result = BacktestSimulator(trader=Trader(config=engine)).run(replay)
    bl = baseline_result
    print("Baseline:")
    print(bl.summary_table())
    print()

    results = []
    for label, overrides in CANDIDATES:
        mod_tomatoes = replace(base_tomatoes, **overrides)
        mod_engine = replace(engine, products={**engine.products, "TOMATOES": mod_tomatoes})
        result = BacktestSimulator(trader=Trader(config=mod_engine)).run(replay)
        results.append((label, mod_engine, result))

    # Ranking table
    print("=" * 70)
    print("Combined finalist ranking")
    print("=" * 70)
    header = f"{'label':<26} {'total':>8} {'EM_pnl':>8} {'TOM_pnl':>8} {'trades':>7} {'edge':>8} {'mk1':>8} {'near':>5} {'pos':>4}"
    print(header)
    print("-" * len(header))

    def fmt(v):
        return f"{v:+.3f}" if v is not None else "    n/a"

    ranked = sorted(results, key=lambda x: x[2].total_pnl, reverse=True)
    for label, _, r in ranked:
        em = r.per_product.get("EMERALDS")
        tom = r.per_product.get("TOMATOES")
        em_pnl = em.pnl if em else 0.0
        tom_pnl = tom.pnl if tom else 0.0
        trades = (tom.trade_count if tom else 0) + (em.trade_count if em else 0)
        edge = fmt(tom.avg_entry_edge) if tom else "    n/a"
        mk1 = fmt(tom.avg_markout_1) if tom else "    n/a"
        near = (tom.steps_near_limit if tom else 0) + (em.steps_near_limit if em else 0)
        pos_t = tom.final_position if tom else 0
        print(f"{label:<26} {r.total_pnl:>8.2f} {em_pnl:>8.2f} {tom_pnl:>8.2f} {trades:>7d} {edge:>8} {mk1:>8} {near:>5d} {pos_t:>4d}")

    bl_total = baseline_result.total_pnl
    print(f"\nBaseline total PnL: {bl_total:.2f}")
    for label, _, r in ranked:
        delta = r.total_pnl - bl_total
        print(f"  {label}: delta={delta:+.2f}")


if __name__ == "__main__":
    main()

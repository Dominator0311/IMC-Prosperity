"""Phase 7: Generate review packs for combined finalist configs."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from src.backtest.replay_engine import ReplayEngine
from src.backtest.reporting import write_review_pack
from src.backtest.simulator import BacktestSimulator
from src.core.config import default_engine_config
from src.trader import Trader

_TUTORIAL_DIR = Path("data/raw/tutorial_round_1")

CANDIDATES = {
    "c1_wall_mid_t05": {"fair_value_method": "wall_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 0.5, "maker_edge": 1.0},
    "c2_wall_mid_t10": {"fair_value_method": "wall_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 1.0, "maker_edge": 1.0},
    "c3_rolling_mid_h32": {"fair_value_method": "rolling_mid", "fair_value_fallbacks": ("mid", "microprice"), "taker_edge": 1.5, "maker_edge": 2.0, "history_length": 32},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", choices=list(CANDIDATES) + ["all"], default="all")
    parser.add_argument("--no-charts", action="store_true")
    args = parser.parse_args()

    price_files = sorted(_TUTORIAL_DIR.glob("prices_*.csv"))
    trade_files = sorted(_TUTORIAL_DIR.glob("trades_*.csv"))
    if not price_files:
        raise SystemExit(f"No tutorial price files in {_TUTORIAL_DIR}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    engine = default_engine_config()
    base_tomatoes = engine.product_config("TOMATOES")
    data_files = [str(p) for p in (*price_files, *trade_files)]

    targets = CANDIDATES if args.candidate == "all" else {args.candidate: CANDIDATES[args.candidate]}

    for label, overrides in targets.items():
        mod_tomatoes = replace(base_tomatoes, **overrides)
        mod_engine = replace(engine, products={**engine.products, "TOMATOES": mod_tomatoes})
        trader = Trader(config=mod_engine)
        result = BacktestSimulator(trader=trader).run(replay)

        pack_dir = write_review_pack(
            result,
            run_label=f"optim_finalist_{label}",
            render_charts=not args.no_charts,
            engine_config=mod_engine,
            data_files=data_files,
        )
        print(f"[{label}] Review pack: {pack_dir}")
        print(result.summary_table())
        print()


if __name__ == "__main__":
    main()

"""Phase 5 review-pack generator for the Round-1 shortlist.

Emits one review pack per Phase-4 candidate under
``outputs/round_1/review_packs/<stamp>_<candidate>/``. Each pack is the
standard ``write_review_pack`` output (``summary.{json,txt}``,
``series.json``, ``trades.json``, ``manifest.json``, plus ``charts/``
when matplotlib is available).

This script does **not** run any sweeps; it only replays each
shortlisted config once with full instrumentation.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_review_packs
    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_review_packs --candidate ash_c1
    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_review_packs --no-charts
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from src.backtest.replay_engine import ReplayEngine
from src.backtest.reporting import write_review_pack
from src.backtest.simulator import BacktestSimulator
from src.core.config import (
    ROUND1_PRODUCTS,
    EngineConfig,
    ProductConfig,
    round1_engine_config,
)
from src.trader import Trader

_ROUND1_DATA_DIR = Path("data/raw/round_1")
_ROUND1_REVIEW_DIR = Path("outputs/round_1/review_packs")

# Each candidate is a (product, overrides) pair. Overrides are merged
# on top of the product's round1_engine_config default via
# ``dataclasses.replace``.
_CANDIDATES: dict[str, dict[str, Any]] = {
    # ---- ASH ----
    "ash_c1_wall_mid_t05": {
        "product": "ASH_COATED_OSMIUM",
        "overrides": {
            "fair_value_method": "wall_mid",
            "fair_value_fallbacks": ("mid", "microprice"),
            "maker_edge": 1.5,
            "taker_edge": 0.5,
            "inventory_skew": 4.0,
            "flatten_threshold": 0.7,
            "history_length": 48,
        },
    },
    "ash_c2_ewma_mid_t025": {
        "product": "ASH_COATED_OSMIUM",
        "overrides": {
            "fair_value_method": "ewma_mid",
            "fair_value_fallbacks": ("mid", "microprice"),
            "maker_edge": 1.0,
            "taker_edge": 0.25,
            "inventory_skew": 4.0,
            "flatten_threshold": 0.7,
            "history_length": 48,
        },
    },
    # ---- PEPPER ----
    "pepper_c1_linear_drift_h32_t20_f08": {
        "product": "INTARIAN_PEPPER_ROOT",
        "overrides": {
            "fair_value_method": "linear_drift",
            "fair_value_fallbacks": ("depth_mid", "hybrid_wall_micro", "mid"),
            "maker_edge": 1.0,
            "taker_edge": 2.0,
            "inventory_skew": 2.0,
            "flatten_threshold": 0.8,
            "history_length": 32,
        },
    },
    "pepper_c1b_linear_drift_h32_t20_f07": {
        "product": "INTARIAN_PEPPER_ROOT",
        "overrides": {
            "fair_value_method": "linear_drift",
            "fair_value_fallbacks": ("depth_mid", "hybrid_wall_micro", "mid"),
            "maker_edge": 1.0,
            "taker_edge": 2.0,
            "inventory_skew": 2.0,
            "flatten_threshold": 0.7,
            "history_length": 32,
        },
    },
    "pepper_c2_linear_drift_h32_skew1_f09": {
        "product": "INTARIAN_PEPPER_ROOT",
        "overrides": {
            "fair_value_method": "linear_drift",
            "fair_value_fallbacks": ("depth_mid", "hybrid_wall_micro", "mid"),
            "maker_edge": 1.0,
            "taker_edge": 2.0,
            "inventory_skew": 1.0,
            "flatten_threshold": 0.9,
            "history_length": 32,
        },
    },
    "pepper_c3_linear_drift_h32_skew4_f08": {
        "product": "INTARIAN_PEPPER_ROOT",
        "overrides": {
            "fair_value_method": "linear_drift",
            "fair_value_fallbacks": ("depth_mid", "hybrid_wall_micro", "mid"),
            "maker_edge": 1.0,
            "taker_edge": 2.0,
            "inventory_skew": 4.0,
            "flatten_threshold": 0.8,
            "history_length": 32,
        },
    },
}


def _build_engine_for(candidate: dict[str, Any]) -> EngineConfig:
    base = round1_engine_config()
    target_product: str = candidate["product"]
    pc = base.product_config(target_product)
    assert pc is not None, f"{target_product} missing in round1_engine_config"
    modified = replace(pc, **candidate["overrides"])
    # Single-product engine: other round-1 products keep their defaults
    # so the replay still executes them, but the sweep is anchored on
    # the candidate's product. This matches the Phase-4 sweep behaviour.
    products = dict(base.products)
    products[target_product] = modified
    return EngineConfig(
        state_version=base.state_version,
        max_trader_data_chars=base.max_trader_data_chars,
        diagnostics_verbosity=base.diagnostics_verbosity,
        products=products,
        scanner_config=base.scanner_config,
        residual_config=base.residual_config,
    )


def _run_one(
    label: str,
    candidate: dict[str, Any],
    replay: ReplayEngine,
    price_files: list[Path],
    trade_files: list[Path],
    *,
    render_charts: bool,
) -> Path:
    engine = _build_engine_for(candidate)
    trader = Trader(config=engine)
    result = BacktestSimulator(trader=trader).run(replay)

    data_files = [str(p) for p in (*price_files, *trade_files)]
    pack_dir = write_review_pack(
        result,
        run_label=f"round1_{label}",
        base_dir=_ROUND1_REVIEW_DIR,
        render_charts=render_charts,
        engine_config=engine,
        data_files=data_files,
    )

    # Compact per-product headline right to stdout so `--candidate all`
    # runs are easy to skim.
    headline_parts: list[str] = [f"[{label}] pack: {pack_dir.name}"]
    target_product = candidate["product"]
    pr = result.per_product.get(target_product)
    if pr is not None:
        headline_parts.append(
            f"  {target_product}: pnl={pr.pnl:+.0f} trades={pr.trade_count} "
            f"pos={pr.final_position} near={pr.steps_near_limit} "
            f"edge={pr.avg_entry_edge:+.3f} "
            f"mk1={_fmt(pr.avg_markout_1)} mk5={_fmt(pr.avg_markout_5)} "
            f"mk20={_fmt(pr.avg_markout_20)}"
        )
    print("\n".join(headline_parts))
    return pack_dir


def _fmt(value: float | None) -> str:
    return f"{value:+.2f}" if value is not None else "n/a"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--candidate",
        choices=list(_CANDIDATES) + ["all"],
        default="all",
        help="Review pack(s) to generate. Defaults to all shortlisted candidates.",
    )
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=_ROUND1_DATA_DIR)
    args = parser.parse_args()

    price_files = sorted(args.data_dir.glob("prices_round_1_day_*.csv"))
    trade_files = sorted(args.data_dir.glob("trades_round_1_day_*.csv"))
    if not price_files:
        raise SystemExit(f"No price files in {args.data_dir}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)
    targets = (
        _CANDIDATES
        if args.candidate == "all"
        else {args.candidate: _CANDIDATES[args.candidate]}
    )

    render = not args.no_charts
    for label, candidate in targets.items():
        _run_one(
            label,
            candidate,
            replay,
            price_files=price_files,
            trade_files=trade_files,
            render_charts=render,
        )
        # Also dump the full ProductConfig used so reviewers can
        # reproduce the candidate from the pack alone.
        engine = _build_engine_for(candidate)
        for product in ROUND1_PRODUCTS:
            pc = engine.product_config(product)
            if pc is None:
                continue
            marker = "*" if product == candidate["product"] else " "
            print(f"    {marker} {product} config: {asdict(pc)}")


if __name__ == "__main__":
    main()


# Exported for tests / tooling that wants to iterate the shortlist.
CANDIDATES = _CANDIDATES

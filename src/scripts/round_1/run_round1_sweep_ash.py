"""Round 1 Stage-A sweep for ASH_COATED_OSMIUM.

For each candidate fair-value method (wall_mid, depth_mid, ewma_mid),
sweep quote competitiveness (``maker_edge``, ``taker_edge``) with
inventory_skew and flatten_threshold held at the Phase-3 defaults.

Outputs a per-estimator sweep report to
``outputs/round_1/sweeps/<stamp>_<label>_<estimator>/``.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_sweep_ash \
        --label round1_ash_stage_a
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from src.backtest.parameter_sweep import (
    build_parameter_sweep_report,
    write_parameter_sweep_report,
)
from src.backtest.replay_engine import ReplayEngine
from src.core.config import EngineConfig, round1_engine_config

_ROUND1_DATA_DIR = Path("data/raw/round_1")
_ROUND1_SWEEP_DIR = Path("outputs/round_1/sweeps")
_PRODUCT = "ASH_COATED_OSMIUM"

# Stage A: quote competitiveness. Skew / flatten held fixed.
_STAGE_A_GRID = {
    "maker_edge": [0.5, 1.0, 1.5, 2.0],
    "taker_edge": [0.5, 1.0, 1.5, 2.0],
}

# Fair-value families to test (dossier shortlist).
_FV_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("wall_mid", ("mid", "microprice")),
    ("depth_mid", ("mid", "microprice")),
    ("ewma_mid", ("mid", "microprice")),
)


def _engine_for_estimator(estimator: str, fallbacks: tuple[str, ...]) -> EngineConfig:
    """Build an EngineConfig whose ASH uses the requested estimator."""
    base = round1_engine_config()
    ash = base.product_config(_PRODUCT)
    assert ash is not None
    ash = replace(
        ash,
        fair_value_method=estimator,
        fair_value_fallbacks=fallbacks,
        # Hold inventory parameters fixed at Phase-3 defaults.
        inventory_skew=4.0,
        flatten_threshold=0.7,
        history_length=48,
    )
    return EngineConfig(
        state_version=base.state_version,
        max_trader_data_chars=base.max_trader_data_chars,
        diagnostics_verbosity=base.diagnostics_verbosity,
        products={_PRODUCT: ash},
        scanner_config=base.scanner_config,
        residual_config=base.residual_config,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="round1_ash_stage_a")
    parser.add_argument("--data-dir", type=Path, default=_ROUND1_DATA_DIR)
    args = parser.parse_args()

    price_files = sorted(args.data_dir.glob("prices_round_1_day_*.csv"))
    trade_files = sorted(args.data_dir.glob("trades_round_1_day_*.csv"))
    if not price_files:
        raise SystemExit(f"No price files in {args.data_dir}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)

    for estimator, fallbacks in _FV_CANDIDATES:
        engine = _engine_for_estimator(estimator, fallbacks)
        print(f"\n=== {estimator} (grid size = "
              f"{len(_STAGE_A_GRID['maker_edge']) * len(_STAGE_A_GRID['taker_edge'])}) ===")
        report = build_parameter_sweep_report(
            replay,
            product=_PRODUCT,
            grid=_STAGE_A_GRID,
            config=engine,
            run_label=f"{args.label}_{estimator}",
        )
        directory = write_parameter_sweep_report(report, base_dir=_ROUND1_SWEEP_DIR)
        print(f"  wrote {directory}")
        print(report.summary_text(top_n=8))


if __name__ == "__main__":
    main()

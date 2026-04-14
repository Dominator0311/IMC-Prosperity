"""Round 1 Stage-A and Stage-B sweeps for INTARIAN_PEPPER_ROOT.

- Stage A (``--stage a``): compare fair-value families at a common
  baseline edge/skew. Tests the 4 Phase-1 shortlisted FVs plus a
  coarse history_length sweep for ``linear_drift`` (the only FV with
  a meaningful history-length knob).
- Stage B (``--stage b``): threshold frontier on the best Stage-A FV
  family (``maker_edge`` × ``taker_edge``) with inventory skew held
  at the Phase-3 default.
- Stage C (``--stage c``): inventory refinement on the best Stage-B
  config.

Outputs land in ``outputs/round_1/sweeps/<stamp>_<label>/``.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_sweep_pepper --stage a
    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.run_round1_sweep_pepper --stage b \
        --fv linear_drift --history 32
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
_PRODUCT = "INTARIAN_PEPPER_ROOT"

# Stage A: fair-value family comparison. Each family runs with a
# minimal 2x2 edge grid so we can read PnL, edge, markouts, and
# inventory together.
_STAGE_A_FV_GRID = {
    "maker_edge": [1.0, 1.5],
    "taker_edge": [1.0, 1.5],
}

# Stage A (linear_drift history scan): test several history windows.
_STAGE_A_HISTORY_GRID = {
    "history_length": [16, 32, 48, 64],
    "maker_edge": [1.5],
    "taker_edge": [1.0],
}

# Stage B: threshold frontier on the best FV family.
_STAGE_B_GRID = {
    "maker_edge": [0.5, 1.0, 1.5, 2.0, 2.5],
    "taker_edge": [0.5, 1.0, 1.5, 2.0],
}

# Stage C: inventory refinement.
_STAGE_C_GRID = {
    "inventory_skew": [1.0, 2.0, 4.0, 8.0],
    "flatten_threshold": [0.5, 0.7, 0.8, 0.9],
}

_STAGE_A_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("linear_drift", ("depth_mid", "hybrid_wall_micro", "mid")),
    ("depth_mid", ("hybrid_wall_micro", "mid")),
    ("hybrid_wall_micro", ("depth_mid", "mid")),
    ("ewma_mid", ("depth_mid", "mid")),
)


def _engine_for(
    estimator: str,
    fallbacks: tuple[str, ...],
    *,
    history_length: int = 48,
    inventory_skew: float = 2.0,
    flatten_threshold: float = 0.8,
) -> EngineConfig:
    """Build an EngineConfig where PEPPER uses the requested FV family."""
    base = round1_engine_config()
    pepper = base.product_config(_PRODUCT)
    assert pepper is not None
    pepper = replace(
        pepper,
        fair_value_method=estimator,
        fair_value_fallbacks=fallbacks,
        history_length=history_length,
        inventory_skew=inventory_skew,
        flatten_threshold=flatten_threshold,
    )
    return EngineConfig(
        state_version=base.state_version,
        max_trader_data_chars=base.max_trader_data_chars,
        diagnostics_verbosity=base.diagnostics_verbosity,
        products={_PRODUCT: pepper},
        scanner_config=base.scanner_config,
        residual_config=base.residual_config,
    )


def _run_stage_a(replay: ReplayEngine, label: str) -> None:
    for estimator, fallbacks in _STAGE_A_FAMILIES:
        engine = _engine_for(estimator, fallbacks)
        print(f"\n=== Stage A · {estimator} (grid {len(_STAGE_A_FV_GRID['maker_edge']) * len(_STAGE_A_FV_GRID['taker_edge'])}) ===")
        report = build_parameter_sweep_report(
            replay,
            product=_PRODUCT,
            grid=_STAGE_A_FV_GRID,
            config=engine,
            run_label=f"{label}_{estimator}",
        )
        directory = write_parameter_sweep_report(report, base_dir=_ROUND1_SWEEP_DIR)
        print(f"  wrote {directory}")
        print(report.summary_text(top_n=4))

    # History-length scan for linear_drift only (no other FV cares)
    engine = _engine_for("linear_drift", ("depth_mid", "hybrid_wall_micro", "mid"))
    print("\n=== Stage A · linear_drift history_length sweep ===")
    report = build_parameter_sweep_report(
        replay,
        product=_PRODUCT,
        grid=_STAGE_A_HISTORY_GRID,
        config=engine,
        run_label=f"{label}_linear_drift_history",
    )
    directory = write_parameter_sweep_report(report, base_dir=_ROUND1_SWEEP_DIR)
    print(f"  wrote {directory}")
    print(report.summary_text(top_n=6))


def _run_stage_b(replay: ReplayEngine, label: str, fv: str, history: int) -> None:
    fallbacks = {
        "linear_drift": ("depth_mid", "hybrid_wall_micro", "mid"),
        "depth_mid": ("hybrid_wall_micro", "mid"),
        "hybrid_wall_micro": ("depth_mid", "mid"),
        "ewma_mid": ("depth_mid", "mid"),
    }[fv]
    engine = _engine_for(fv, fallbacks, history_length=history)
    print(f"\n=== Stage B · {fv} (history={history}, grid {len(_STAGE_B_GRID['maker_edge']) * len(_STAGE_B_GRID['taker_edge'])}) ===")
    report = build_parameter_sweep_report(
        replay,
        product=_PRODUCT,
        grid=_STAGE_B_GRID,
        config=engine,
        run_label=f"{label}_{fv}_h{history}",
    )
    directory = write_parameter_sweep_report(report, base_dir=_ROUND1_SWEEP_DIR)
    print(f"  wrote {directory}")
    print(report.summary_text(top_n=10))


def _run_stage_c(
    replay: ReplayEngine,
    label: str,
    fv: str,
    history: int,
    maker_edge: float,
    taker_edge: float,
) -> None:
    fallbacks = {
        "linear_drift": ("depth_mid", "hybrid_wall_micro", "mid"),
        "depth_mid": ("hybrid_wall_micro", "mid"),
        "hybrid_wall_micro": ("depth_mid", "mid"),
        "ewma_mid": ("depth_mid", "mid"),
    }[fv]
    engine = _engine_for(fv, fallbacks, history_length=history)
    # Stage-C grid sweeps skew/flatten while fixing maker/taker from Stage B.
    grid = {
        "maker_edge": [maker_edge],
        "taker_edge": [taker_edge],
        **_STAGE_C_GRID,
    }
    print(f"\n=== Stage C · {fv} (maker={maker_edge}, taker={taker_edge}, grid {len(grid['inventory_skew']) * len(grid['flatten_threshold'])}) ===")
    report = build_parameter_sweep_report(
        replay,
        product=_PRODUCT,
        grid=grid,
        config=engine,
        run_label=f"{label}_{fv}_stageC",
    )
    directory = write_parameter_sweep_report(report, base_dir=_ROUND1_SWEEP_DIR)
    print(f"  wrote {directory}")
    print(report.summary_text(top_n=10))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("a", "b", "c"), required=True)
    parser.add_argument("--label", default=None)
    parser.add_argument("--data-dir", type=Path, default=_ROUND1_DATA_DIR)
    parser.add_argument("--fv", default="linear_drift", help="Stage B/C only")
    parser.add_argument("--history", type=int, default=48, help="Stage B/C only")
    parser.add_argument("--maker-edge", type=float, default=1.5, help="Stage C only")
    parser.add_argument("--taker-edge", type=float, default=1.0, help="Stage C only")
    args = parser.parse_args()
    label = args.label or f"round1_pepper_stage_{args.stage}"

    price_files = sorted(args.data_dir.glob("prices_round_1_day_*.csv"))
    trade_files = sorted(args.data_dir.glob("trades_round_1_day_*.csv"))
    if not price_files:
        raise SystemExit(f"No price files in {args.data_dir}")

    replay = ReplayEngine.from_files(price_paths=price_files, trade_paths=trade_files)

    if args.stage == "a":
        _run_stage_a(replay, label)
    elif args.stage == "b":
        _run_stage_b(replay, label, args.fv, args.history)
    else:
        _run_stage_c(replay, label, args.fv, args.history, args.maker_edge, args.taker_edge)


if __name__ == "__main__":
    main()

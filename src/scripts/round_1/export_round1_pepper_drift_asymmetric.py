"""Export bundle for pepper_drift_asymmetric candidate.

Fodra-Labadie asymmetric maker: edges skew with linear_drift slope
(positive slope → tighter bid, wider ask). Reversal guard flips target
to 0 when slope turns negative.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_pepper_drift_asymmetric
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_pepper_drift_asymmetric_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    export_bundle,
)
from src.strategies.round_1_pepper_candidates import DRIFT_ASYMMETRIC_PARAMS

_ASH_INLINE = PepperInline(
    strategy_module_path="src/strategies/ash_ladder.py",
    strategy_class_name="AshLadderStrategy",
    params_class_name="LadderParams",
    new_strategy_name="ash_ladder",
    params_dict={
        "edges": (2.5, 4.0, 6.0),
        "size_mults": (1.0, 1.5, 2.0),
        "skew_coef": 2.0,
        "flatten_threshold": 0.7,
        "weights": (3, 1, 1),
    },
)

_PEPPER_INLINE = PepperInline(
    strategy_module_path="src/strategies/pepper_drift_asymmetric.py",
    strategy_class_name="PepperDriftAsymmetricStrategy",
    params_class_name="DriftAsymmetricParams",
    new_strategy_name="pepper_drift_asymmetric",
    params_dict=asdict(DRIFT_ASYMMETRIC_PARAMS),
)

_SPEC = PepperBundleSpec(
    variant="pepper_drift_asymmetric",
    factory_name="round1_pepper_drift_asymmetric_engine_config",
    factory=round1_pepper_drift_asymmetric_engine_config,
    label="Round-1 PEPPER Fodra-Labadie asymmetric-maker candidate",
    purpose=(
        "Asymmetric maker around linear_drift forecast; edge "
        "asymmetry scales with observed slope (slope_skew_factor=10, "
        "max_asymmetry=3). Reversal guard flips target to 0 when "
        "slope <= -0.02 with r2 >= 0.30. Local 3-day PEPPER mean "
        "+39,237."
    ),
    ash_inline=_ASH_INLINE,
    pepper_inline=_PEPPER_INLINE,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    path = export_bundle(_SPEC, out_dir=args.out_dir)
    print(f"[{_SPEC.variant}] wrote {path.name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

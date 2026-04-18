"""Export bundle for pepper_passive_maker candidate.

Ships K2's ASH ladder (2.5/4/6 weights 3/1/1) + PepperPassiveMakerStrategy
with the no-overfit shipping params from
``src.strategies.round_1_pepper_candidates.PASSIVE_MAKER_PARAMS``.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_pepper_passive_maker
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_pepper_passive_maker_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    export_bundle,
)
from src.strategies.round_1_pepper_candidates import PASSIVE_MAKER_PARAMS

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
    strategy_module_path="src/strategies/pepper_passive_maker.py",
    strategy_class_name="PepperPassiveMakerStrategy",
    params_class_name="PassiveMakerParams",
    new_strategy_name="pepper_passive_maker",
    params_dict=asdict(PASSIVE_MAKER_PARAMS),
)

_SPEC = PepperBundleSpec(
    variant="pepper_passive_maker",
    factory_name="round1_pepper_passive_maker_engine_config",
    factory=round1_pepper_passive_maker_engine_config,
    label="Round-1 PEPPER passive-maker candidate",
    purpose=(
        "Breaks out of buy_and_hold on PEPPER. Posts inside-spread "
        "passive maker with asymmetric long bias (bid_edge=3, "
        "ask_edge=5) anchored to linear_drift forecast. Core target 40 "
        "leaves 40 units of cycling headroom. Local 3-day PEPPER mean "
        "+45,248."
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

"""Export bundle for pepper_imbalance_timer candidate.

Drift-carry core (target 60) + OFI-gated tactical adds/trims.
Top-of-book imbalance >= 0.30 triggers adds (up to size 4) at or below
the current ask; imbalance <= -0.30 triggers trims. Background maker
quotes (edge 3/5, size 3) run continuously between events. Best
local-mean PEPPER performer of the 5 candidates at +73,461.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_pepper_imbalance_timer
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_pepper_imbalance_timer_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    export_bundle,
)
from src.strategies.round_1_pepper_candidates import IMBALANCE_TIMER_PARAMS

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
    strategy_module_path="src/strategies/pepper_imbalance_timer.py",
    strategy_class_name="PepperImbalanceTimerStrategy",
    params_class_name="ImbalanceTimerParams",
    new_strategy_name="pepper_imbalance_timer",
    params_dict=asdict(IMBALANCE_TIMER_PARAMS),
)

_SPEC = PepperBundleSpec(
    variant="pepper_imbalance_timer",
    factory_name="round1_pepper_imbalance_timer_engine_config",
    factory=round1_pepper_imbalance_timer_engine_config,
    label="Round-1 PEPPER OFI-gated timer candidate",
    purpose=(
        "Drift-carry core (target 60) with OFI-gated adds/trims when "
        "book imbalance exceeds +/-0.30 and price is within +/-2 of "
        "drift_fair. Uses the 0.56-correlation imbalance signal no "
        "prior PEPPER strategy has used. Local 3-day PEPPER mean "
        "+73,461 (best of 5 candidates locally)."
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

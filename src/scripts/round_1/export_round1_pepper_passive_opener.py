"""Export bundle for pepper_passive_opener candidate.

Passive-first opening (bid at best_bid+1 for 3 ticks, taker fallback
at tick 3), then drift-maker carry with asymmetric inventory-skewed
edges (3/5, core 40).

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_pepper_passive_opener
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_pepper_passive_opener_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    export_bundle,
)
from src.strategies.round_1_pepper_candidates import PASSIVE_OPENER_PARAMS

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
    strategy_module_path="src/strategies/pepper_passive_opener.py",
    strategy_class_name="PepperPassiveOpenerStrategy",
    params_class_name="PassiveOpenerParams",
    new_strategy_name="pepper_passive_opener",
    params_dict=asdict(PASSIVE_OPENER_PARAMS),
)

_SPEC = PepperBundleSpec(
    variant="pepper_passive_opener",
    factory_name="round1_pepper_passive_opener_engine_config",
    factory=round1_pepper_passive_opener_engine_config,
    label="Round-1 PEPPER passive-first opening candidate",
    purpose=(
        "Replaces V3's taker-first opening with a 3-tick passive-first "
        "open (bid at best_bid+1) + taker fallback. Designed to save "
        "~200-400 PnL of entry spread cost on the 40-unit seed. "
        "Post-open: drift-maker carry with asymmetric inventory-skewed "
        "edges. Local 3-day PEPPER mean +66,373."
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

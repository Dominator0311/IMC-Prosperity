"""Export K3 — Phase-K J2_4lvl (2.5/5/8/12 with weights 3/1/1/1)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_k3_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_k3",
    factory_name="round1_ash_deep_k3_engine_config",
    factory=round1_ash_deep_k3_engine_config,
    label="Round-1 Phase-K K3 — J2 plus d=12 outer (4-level)",
    purpose=(
        "J2 extension with a 4th outer level at d=12. Weights "
        "3/1/1/1 → inner 50%, outers 16.7% each. Adds coverage "
        "for rare ±12-tick excursions while keeping J2's winning "
        "inner-heavy structure. Local +3 582 (vs J2 +3 653). "
        "Extreme-move fills are low probability but high edge "
        "when they land."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_ladder.py",
        strategy_class_name="AshLadderStrategy",
        params_class_name="LadderParams",
        new_strategy_name="ash_ladder",
        params_dict={
            "edges": (2.5, 5.0, 8.0, 12.0),
            "size_mults": (1.0, 1.5, 2.0, 3.0),
            "skew_coef": 2.0,
            "flatten_threshold": 0.7,
            "weights": (3, 1, 1, 1),
        },
    ),
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

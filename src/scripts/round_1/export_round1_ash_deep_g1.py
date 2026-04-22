"""Export G1 — wall_mid + m=2.5 + linear skew c=2 (F3a tuning, wall_mid FV)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_g1_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_g1",
    factory_name="round1_ash_deep_g1_engine_config",
    factory=round1_ash_deep_g1_engine_config,
    label="Round-1 Phase-G G1 — wall_mid + m=2.5 + linear skew c=2",
    purpose=(
        "Phase-G extension. Applies the F3a winning tuning "
        "(m=2.5/t=0.5 + linear skew c=2) on wall_mid FV instead of "
        "weighted_mid. Tests whether F3a's win comes from the FV "
        "choice or from the edge/skew tuning. Projected official "
        "+1 407 (vs F3a observed +1 395)."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_shape_override.py",
        strategy_class_name="AshShapeOverrideStrategy",
        params_class_name="ShapeParams",
        new_strategy_name="ash_shape_override",
        params_dict={
            "skew_mode": "linear",
            "skew_coef": 2.0,
            "flatten_mode": "hard",
            "flatten_threshold": 0.7,
            "size_mode": "constant",
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

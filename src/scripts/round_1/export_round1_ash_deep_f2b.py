"""Export F2b — D6 m=2.5 + AS-continuous flatten via ash_shape_override."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_f2b_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_f2b",
    factory_name="round1_ash_deep_f2b_engine_config",
    factory=round1_ash_deep_f2b_engine_config,
    label="Round-1 Phase-F F2b — D6 m=2.5 + AS-continuous flatten",
    purpose=(
        "Phase-D D6: wall_mid at m=2.5/t=0.5 with AS-continuous "
        "flatten (skew_mode=as, gamma=5e-7) replacing the hard "
        "threshold. Best D-hybrid on expected-official at +2016; "
        "best wall_mid-family candidate on stress tapes."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_shape_override.py",
        strategy_class_name="AshShapeOverrideStrategy",
        params_class_name="ShapeParams",
        new_strategy_name="ash_shape_override",
        params_dict={
            "skew_mode": "as",
            "as_gamma": 5e-7,
            "as_sigma": 2.0,
            "as_horizon": 100_000,
            "flatten_mode": "as_continuous",
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

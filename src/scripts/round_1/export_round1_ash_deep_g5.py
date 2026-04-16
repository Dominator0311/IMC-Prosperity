"""Export G5 — F3a with softer skew c=1 (highest Phase-G local mean)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_g5_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_g5",
    factory_name="round1_ash_deep_g5_engine_config",
    factory=round1_ash_deep_g5_engine_config,
    label="Round-1 Phase-G G5 — F3a with skew c=1 (softer)",
    purpose=(
        "Phase-G extension. F3a's engine config (weighted_mid + "
        "m=2.5/t=0.5) with linear skew coefficient halved to 1.0 "
        "(F3a uses c=2). Phase-G local sweep showed c=1 as the "
        "local optimum along the skew axis (+3 495 3-day mean, "
        "highest of any ASH variant tested). Projected official "
        "+1 468 (Δ +72 vs F3a)."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_shape_override.py",
        strategy_class_name="AshShapeOverrideStrategy",
        params_class_name="ShapeParams",
        new_strategy_name="ash_shape_override",
        params_dict={
            "skew_mode": "linear",
            "skew_coef": 1.0,
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

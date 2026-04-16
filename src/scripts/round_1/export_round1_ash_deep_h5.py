"""Export H5 — Phase-H slow-FV test (ewma τ=500 + linear skew c=2)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_h5_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_h5",
    factory_name="round1_ash_deep_h5_engine_config",
    factory=round1_ash_deep_h5_engine_config,
    label="Round-1 Phase-H H5 — slow-FV anchor (ewma τ=500)",
    purpose=(
        "Phase-H hidden-pattern test. ASH Roll (1984) decomposition "
        "shows fundamental vol ~0 and OU half-life 2 ticks around a "
        "near-constant FV. F3a uses weighted_mid which tracks the OU "
        "state (noise); H5 replaces FV with ewma τ=500 which tracks "
        "the OU mean. Local 3-day mean +1 908 (below F3a +3 446) but "
        "fill-scale projected official +1 639 (+244 vs F3a observed "
        "+1 395) because maker fills are ~5x denser. Resolves "
        "local-vs-projection ambiguity: if H5 wins the slow-FV "
        "hypothesis is confirmed; if it loses F3a is proven optimal."
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

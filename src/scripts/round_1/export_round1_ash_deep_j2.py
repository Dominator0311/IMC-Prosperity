"""Export J2 — Phase-J 3-level inner-heavy ladder (weights 3/1/1)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_j2_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_j2",
    factory_name="round1_ash_deep_j2_engine_config",
    factory=round1_ash_deep_j2_engine_config,
    label="Round-1 Phase-J J2 — 3-level inner-heavy ladder (3/1/1)",
    purpose=(
        "Phase-J post-I2a test. I2a tied F3a officially (+1 365 "
        "vs +1 395) — edge per share +29% offset by volume −29%. "
        "J2 biases the tick-rotation toward the inner level (60%) "
        "to recover F3a's volume base while keeping outer-level "
        "coverage. Local +3 653 (vs I2a +3 666). Projected official "
        "~+1 461 (Δ +66 vs F3a observed) if the inner-heavy design "
        "gets a better local-to-official transfer ratio than I2a."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_ladder.py",
        strategy_class_name="AshLadderStrategy",
        params_class_name="LadderParams",
        new_strategy_name="ash_ladder",
        params_dict={
            "edges": (2.5, 5.0, 8.0),
            "size_mults": (1.0, 1.5, 2.0),
            "skew_coef": 2.0,
            "flatten_threshold": 0.7,
            "weights": (3, 1, 1),
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

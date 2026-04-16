"""Export I2a — Phase-I 4-level ladder (tick-rotation 2.5/5/8/12)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_i2a_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_i2a",
    factory_name="round1_ash_deep_i2a_engine_config",
    factory=round1_ash_deep_i2a_engine_config,
    label="Round-1 Phase-I I2a — 4-level ladder (2.5/5/8/12)",
    purpose=(
        "Phase-I post-Phase-H exploration. F3a's engine with a "
        "tick-rotation maker ladder: each tick quotes at one of "
        "four edge levels (2.5, 5, 8, 12) with sizes scaled "
        "(1x, 1.5x, 2x, 3x). Local 3-day mean +3 666 (vs F3a "
        "+3 446, Δ +220 — first variant beating F3a on local). "
        "14x maker fill count (72 vs 5) at higher per-fill "
        "markout (+2.11). Hypothesis: multi-level quoting "
        "captures the OU amplitude distribution F3a's "
        "single-edge misses."
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

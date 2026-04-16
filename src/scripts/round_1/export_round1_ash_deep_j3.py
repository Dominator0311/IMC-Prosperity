"""Export J3 — Phase-J 4-level ladder with spread-gated outer levels."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_j3_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_j3",
    factory_name="round1_ash_deep_j3_engine_config",
    factory=round1_ash_deep_j3_engine_config,
    label="Round-1 Phase-J J3 — spread-gated 4-level ladder",
    purpose=(
        "Phase-J post-I2a test. 4-level ladder (2.5/5/8/12) but "
        "outer levels (index>0) only fire when book_spread >= 16. "
        "When spread is tight (<16), forces inner-level quoting. "
        "Theory: outer-level quotes at edge=12 when spread=10 are "
        "meaningless (they sit 7 ticks beyond the book). Gating "
        "prevents wasted outer-level ticks. Local +3 631 (vs I2a "
        "+3 666). Projected official ~+1 452."
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
            "spread_gate_enabled": True,
            "gate_spread": 16,
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

"""Export J7 — Phase-J weighted 3/1/1/1 + spread-gated outer."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_j7_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_j7",
    factory_name="round1_ash_deep_j7_engine_config",
    factory=round1_ash_deep_j7_engine_config,
    label="Round-1 Phase-J J7 — weighted 3/1/1/1 + spread-gated",
    purpose=(
        "Phase-J post-I2a combo. Combines J2's inner-heavy weighting "
        "(3/1/1/1 → inner 50%, outers 17% each) with J3's spread-"
        "gating (outer levels only when spread>=16). Tests whether "
        "the two mechanisms compound. Local +3 581 (below J2 by 72 "
        "but the gating filters low-value outer-level ticks). "
        "Projected official ~+1 468 if transfer ratio benefits "
        "from the cleaner mechanism."
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

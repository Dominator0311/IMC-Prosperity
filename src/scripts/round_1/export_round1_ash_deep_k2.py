"""Export K2 — Phase-K J2_tight (2.5/4/6 with weights 3/1/1)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_k2_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_k2",
    factory_name="round1_ash_deep_k2_engine_config",
    factory=round1_ash_deep_k2_engine_config,
    label="Round-1 Phase-K K2 — J2_tight (outer at 4/6)",
    purpose=(
        "J2 variant with tighter outer edges (4, 6 instead of 5, "
        "8). Rationale: ASH spread is dominantly 16 (each side ~8 "
        "ticks); outer quotes at edge=6 still sit inside the book "
        "typically, while edge=8 might miss. Local +3 497 "
        "(vs J2 +3 653). If edge=4,6 fires at higher official "
        "rate than edge=5,8, could improve PnL despite lower "
        "per-share edge."
    ),
    inline=InlineSpec(
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

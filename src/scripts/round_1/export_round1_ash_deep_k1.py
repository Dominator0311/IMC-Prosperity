"""Export K1 — Phase-K J2_heavier (weights 4/1/1, 67% inner)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_k1_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_k1",
    factory_name="round1_ash_deep_k1_engine_config",
    factory=round1_ash_deep_k1_engine_config,
    label="Round-1 Phase-K K1 — J2_heavier (67% inner)",
    purpose=(
        "J2 (weights 3/1/1, 60% inner) scored +1 647 officially — "
        "first variant to beat F3a (+1 395). J2's transfer ratio "
        "0.451 was highest observed, suggesting inner-heavy "
        "variants UNDER-project locally. K1 pushes inner weight "
        "to 4/1/1 (67% inner, 16.5%/16.5% outer). Local +3 516 "
        "(vs J2 +3 653) but if transfer ratio rises further, "
        "could match or beat J2 officially."
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
            "weights": (4, 1, 1),
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

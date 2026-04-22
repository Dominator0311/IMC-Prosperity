"""Export K5 — Phase-K J2_asym_flip (buy tight, sell wide)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_k5_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_k5",
    factory_name="round1_ash_deep_k5_engine_config",
    factory=round1_ash_deep_k5_engine_config,
    label="Round-1 Phase-K K5 — asymmetric ladder (buy tight, sell wide)",
    purpose=(
        "First asymmetric per-side ladder. Buy side uses tighter "
        "edges (2.5/4/6) to accumulate quickly on dips; sell side "
        "uses wider edges (2.5/5/8) to hold for bigger reversions. "
        "Rationale: if the OU process has asymmetric mean-"
        "reversion (e.g., sharp dips with slower recoveries), "
        "per-side depths better match the process. Local +3 581 "
        "(vs J2 +3 653)."
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
            "buy_edges": (2.5, 4.0, 6.0),
            "buy_size_mults": (1.0, 1.5, 2.0),
            "buy_weights": (3, 1, 1),
            "sell_edges": (2.5, 5.0, 8.0),
            "sell_size_mults": (1.0, 1.5, 2.0),
            "sell_weights": (3, 1, 1),
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

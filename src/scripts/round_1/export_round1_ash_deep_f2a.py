"""Export the Phase-F F2a bundle — C1 AS gamma=2e-6 (Phase-C overall winner).

Inlines the research-only ``AshAvellanedaStoikovStrategy`` and its
``AvellanedaStoikovParams`` via the shared ``_ash_deep_bundle`` helper.

See ``outputs/round_1/ash_deep_dive/phase_c/PHASE_C_MEMO.md`` sec 2 (C1).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_f2a_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_f2a",
    factory_name="round1_ash_deep_f2a_engine_config",
    factory=round1_ash_deep_f2a_engine_config,
    label="Round-1 Phase-F F2a — Avellaneda-Stoikov gamma=2e-6",
    purpose=(
        "Phase-C C1 overall winner across all 85 cells (expected-"
        "official +2244). AS closed-form at gamma=2e-6 delivers "
        "~2.5-tick AS half-spread + gentle inventory-aware reservation-"
        "price shift. Baseline m=2.0/t=0.5 on wall_mid."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_avellaneda_stoikov.py",
        strategy_class_name="AshAvellanedaStoikovStrategy",
        params_class_name="AvellanedaStoikovParams",
        new_strategy_name="ash_avellaneda_stoikov",
        params_dict={
            "gamma": 2e-6, "sigma": 2.0, "k": 0.4, "horizon": 100_000,
            "taker_edge": 0.5, "min_half_spread": 0.5, "flatten_threshold": 0.7,
        },
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    path = export_bundle(_SPEC, out_dir=args.out_dir)
    size_bytes = path.stat().st_size
    print(f"[{_SPEC.variant}] wrote {path.name} ({size_bytes} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

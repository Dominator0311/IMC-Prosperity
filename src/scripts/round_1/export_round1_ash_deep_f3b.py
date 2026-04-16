"""Export F3b — D7 weighted_mid + AS gamma=2e-6."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_f3b_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_f3b",
    factory_name="round1_ash_deep_f3b_engine_config",
    factory=round1_ash_deep_f3b_engine_config,
    label="Round-1 Phase-F F3b — D7 weighted_mid + AS gamma=2e-6",
    purpose=(
        "Phase-D D7: weighted_mid FV (Phase-B winner) + AS quote formula "
        "(Phase-C winner). Tests whether stacking the two winning "
        "components compounds. Stress-tape robust (zero loss on all "
        "six Phase-E tapes)."
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
    print(f"[{_SPEC.variant}] wrote {path.name} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

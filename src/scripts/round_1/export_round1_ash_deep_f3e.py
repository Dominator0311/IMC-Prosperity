"""Export F3e — C3 Cartea beta=0.3 (only C3 cell above baseline)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_f3e_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_f3e",
    factory_name="round1_ash_deep_f3e_engine_config",
    factory=round1_ash_deep_f3e_engine_config,
    label="Round-1 Phase-F F3e — C3 Cartea beta=0.3",
    purpose=(
        "Phase-C C3 smallest-tested beta (0.3) at the Phase-C "
        "baseline m=2.0/t=0.5. Only C3 cell that landed above the "
        "shipped baseline on expected-official (+1107); lowest "
        "confidence of the Phase-F cohort and last priority in the "
        "upload order."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_cartea_skew.py",
        strategy_class_name="AshCarteaSkewStrategy",
        params_class_name="CarteaSkewParams",
        new_strategy_name="ash_cartea_skew",
        params_dict={
            "beta": 0.3,
            "fv_for_alpha": "ewma_mid",
            "sigma_residual_prior": 1.06,
            "alpha_clip": 3.0,
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

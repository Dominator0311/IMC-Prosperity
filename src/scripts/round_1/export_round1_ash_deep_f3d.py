"""Export F3d — C1 AS gamma=5e-7 (safer AS gamma)."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.core.config import round1_ash_deep_f3d_engine_config
from src.scripts.round_1._ash_deep_bundle import (
    DEFAULT_OUT_DIR,
    AshDeepBundleSpec,
    InlineSpec,
    export_bundle,
)

_SPEC = AshDeepBundleSpec(
    variant="ash_deep_f3d",
    factory_name="round1_ash_deep_f3d_engine_config",
    factory=round1_ash_deep_f3d_engine_config,
    label="Round-1 Phase-F F3d — AS gamma=5e-7",
    purpose=(
        "Phase-C C1 safer AS variant at gamma=5e-7 (middle of the "
        "3-point Phase-C grid). Milder inventory-aware reservation-"
        "price shift than F2a (gamma=2e-6) — tests whether the "
        "less-aggressive AS tuning transfers better."
    ),
    inline=InlineSpec(
        strategy_module_path="src/strategies/ash_avellaneda_stoikov.py",
        strategy_class_name="AshAvellanedaStoikovStrategy",
        params_class_name="AvellanedaStoikovParams",
        new_strategy_name="ash_avellaneda_stoikov",
        params_dict={
            "gamma": 5e-7, "sigma": 2.0, "k": 0.4, "horizon": 100_000,
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

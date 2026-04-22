"""Export bundle for pepper_flow_overlay candidate.

First PEPPER strategy to read ``snapshot.trades``: EWMA of aggressor
net-flow biases target position toward the dominant side. flow_decay
0.85 (half-life ≈ 4.3 ticks), flow_scale 0.5, flow_bias_size 20.

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_pepper_flow_overlay
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_pepper_flow_overlay_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    export_bundle,
)
from src.strategies.round_1_pepper_candidates import FLOW_OVERLAY_PARAMS

_ASH_INLINE = PepperInline(
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
)

_PEPPER_INLINE = PepperInline(
    strategy_module_path="src/strategies/pepper_flow_overlay.py",
    strategy_class_name="PepperFlowOverlayStrategy",
    params_class_name="FlowOverlayParams",
    new_strategy_name="pepper_flow_overlay",
    params_dict=asdict(FLOW_OVERLAY_PARAMS),
)

_SPEC = PepperBundleSpec(
    variant="pepper_flow_overlay",
    factory_name="round1_pepper_flow_overlay_engine_config",
    factory=round1_pepper_flow_overlay_engine_config,
    label="Round-1 PEPPER trade-flow EWMA overlay candidate",
    purpose=(
        "Reads snapshot.trades (aggressor flow) — untouched by any "
        "prior PEPPER strategy. EWMA of net aggressor flow biases "
        "target position up to +/-20 units around core_long=50. "
        "Local 3-day PEPPER mean +51,752."
    ),
    ash_inline=_ASH_INLINE,
    pepper_inline=_PEPPER_INLINE,
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

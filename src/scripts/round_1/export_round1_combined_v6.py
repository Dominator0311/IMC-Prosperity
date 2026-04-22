"""Export combined bundle: v6 PEPPER + L1 ASH ladder.

v6 PEPPER combines four mechanisms:
1. Passive-first opening (save spread cost vs taker)
2. Core-long overlay with OLS guard (from v5_micro)
3. Inside-spread maker cycling (from passive_maker)
4. Drift asymmetry (Fodra-Labadie, from drift_asymmetric)

ASH leg is unchanged from the v5micro+L1 bundle (L1 ladder 2.5/3.5/5).

Two param configs:
- v6a: conservative (base_long=80, no cycling, passive opening only)
- v6b: full combo (base_long=65, cycling + asymmetry)

Usage::

    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_combined_v6
    PYTHONPATH=. .venv/bin/python -m src.scripts.round_1.export_round1_combined_v6 --variant v6a
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import asdict
from pathlib import Path

from src.core.config import round1_combined_v6_engine_config
from src.scripts.round_1._pepper_deep_bundle import (
    DEFAULT_OUT_DIR,
    PepperBundleSpec,
    PepperInline,
    build_bundle,
)
from src.strategies.ash_ladder import LadderParams
from src.strategies.pepper_v6_combined import V6CombinedParams

# ---- v6b: full combo (default) ----
_V6B_PARAMS = V6CombinedParams(
    base_long=65,
    floor=0,
    ceiling=80,
    step=8,
    opening_passive_window=3,
    opening_seed_size=50,
    opening_taker_fallback_tick=3,
    opening_no_short=True,
    opening_max_size_per_tick=20,
    passive_bid_improve=1,
    add_thresh=3.0,
    trim_thresh=8.0,
    add_gain=5.0,
    trim_gain=2.0,
    guard_window=32,
    guard_negative_slope=0.01,
    guard_r2_min=0.0,
    guard_target=0,
    micro_residual_threshold=3.0,
    micro_imbalance_threshold=0.30,
    micro_add_size=2,
    micro_trim_size=2,
    maker_base_bid_edge=3.0,
    maker_base_ask_edge=5.0,
    maker_quote_size=5,
    maker_inventory_skew_coef=0.04,
    min_spread_for_maker=4,
    drift_slope_skew_factor=10.0,
    drift_max_asymmetry=3.0,
    drift_slope_r2_min=0.30,
    drift_reversal_slope_threshold=0.02,
    drift_reversal_r2_min=0.30,
    drift_reversal_target=0,
    exec_style="hybrid",
    hybrid_threshold=2.0,
)

# ---- v6a: conservative (passive opening only, same base as v5_micro) ----
_V6A_PARAMS = V6CombinedParams(
    base_long=80,
    floor=0,
    ceiling=80,
    step=8,
    opening_passive_window=3,
    opening_seed_size=65,
    opening_taker_fallback_tick=3,
    opening_no_short=True,
    opening_max_size_per_tick=20,
    passive_bid_improve=1,
    add_thresh=3.0,
    trim_thresh=8.0,
    add_gain=5.0,
    trim_gain=2.0,
    guard_window=32,
    guard_negative_slope=0.01,
    guard_r2_min=0.0,
    guard_target=0,
    micro_residual_threshold=3.0,
    micro_imbalance_threshold=0.30,
    micro_add_size=2,
    micro_trim_size=2,
    maker_base_bid_edge=3.0,
    maker_base_ask_edge=5.0,
    maker_quote_size=0,  # Cycling OFF for v6a
    maker_inventory_skew_coef=0.04,
    min_spread_for_maker=4,
    drift_slope_skew_factor=10.0,
    drift_max_asymmetry=3.0,
    drift_slope_r2_min=0.30,
    drift_reversal_slope_threshold=0.02,
    drift_reversal_r2_min=0.30,
    drift_reversal_target=0,
    exec_style="hybrid",
    hybrid_threshold=2.0,
)

_ASH_INLINE = PepperInline(
    strategy_module_path="src/strategies/ash_ladder.py",
    strategy_class_name="AshLadderStrategy",
    params_class_name="LadderParams",
    new_strategy_name="ash_ladder",
    params_dict={
        "edges": (2.5, 3.5, 5.0),
        "size_mults": (1.0, 1.5, 2.0),
        "skew_coef": 2.0,
        "flatten_threshold": 0.7,
        "weights": (3, 1, 1),
    },
)

_VARIANTS: dict[str, tuple[str, V6CombinedParams, str]] = {
    "v6b": (
        "combined_v6b",
        _V6B_PARAMS,
        "Full combo: passive opening + core-long overlay + maker cycling + "
        "drift asymmetry (base_long=65, maker_quote_size=5).",
    ),
    "v6a": (
        "combined_v6a",
        _V6A_PARAMS,
        "Conservative: passive opening only, same base_long=80 as v5_micro. "
        "No maker cycling (maker_quote_size=0).",
    ),
}


def _ast_compress(source: str) -> str:
    tree = ast.parse(source)

    def _strip_string_exprs(body: list[ast.stmt]) -> list[ast.stmt]:
        out: list[ast.stmt] = []
        for node in body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                node.body = _strip_string_exprs(node.body)
            out.append(node)
        return out

    tree.body = _strip_string_exprs(tree.body)
    return ast.unparse(tree).rstrip() + "\n"


def _build_spec(variant_key: str) -> PepperBundleSpec:
    variant_name, params, purpose = _VARIANTS[variant_key]

    pepper_inline = PepperInline(
        strategy_module_path="src/strategies/pepper_v6_combined.py",
        strategy_class_name="PepperV6CombinedStrategy",
        params_class_name="V6CombinedParams",
        new_strategy_name="pepper_v6_combined",
        params_dict=asdict(params),
    )
    return PepperBundleSpec(
        variant=variant_name,
        factory_name="round1_combined_v6_engine_config",
        factory=round1_combined_v6_engine_config,
        label=f"Round-1 combined v6 ({variant_key}): PEPPER + L1 ASH ladder",
        purpose=purpose,
        ash_inline=_ASH_INLINE,
        pepper_inline=pepper_inline,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--variant",
        choices=list(_VARIANTS.keys()),
        default="v6b",
        help="Which v6 param set to export (default: v6b full combo)",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)

    spec = _build_spec(args.variant)
    source, _ = build_bundle(spec)
    compressed = _ast_compress(source)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / f"trader_round1_{spec.variant}.py"
    output_path.write_text(compressed, encoding="utf-8")
    print(f"[{spec.variant}] wrote {output_path.name} ({output_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

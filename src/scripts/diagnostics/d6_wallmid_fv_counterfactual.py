"""Diagnostic D6 — Wall-mid fair-value counterfactual for ASH (F2 + F4).

Tests the F2/F4 convergent finding that top teams use volume-robust mid
(wall_mid / filtered_wall_mid) as fair value on stable products, not
time-smoothed weighted_mid.

Runs the R2 replay through the shipped v5micro_wide113 stack with three
ASH fair-value primaries:
  1. weighted_mid (current shipped — time-smoothed average of recent mids)
  2. wall_mid (midpoint of LARGEST-volume bid and ask levels)
  3. filtered_wall_mid (same, filtered to volume >= 25% of side max)

If wall_mid or filtered_wall_mid produces materially higher ASH P&L in
our local backtest, that directionally supports the fix. **This is a
direction test, not truth — only IMC simulator upload validates.**

Usage:
    PYTHONPATH=. .venv/bin/python -m src.scripts.diagnostics.d6_wallmid_fv_counterfactual
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.backtest.simulator import BacktestSimulator
from src.scripts.round_2._runtime import (
    L1_ASH_LADDER_PARAMS,
    V5_MICRO_PEPPER_PARAMS,
    baseline_engine,
    load_round_2_replay,
    wrap_trader_with_v5micro_l1,
)
from src.trader import Trader

_OUTPUT = Path("outputs/diagnostics/d6_wallmid_fv.md")


def _run(fv_method: str, fv_fallbacks: tuple[str, ...]) -> dict:
    replay = load_round_2_replay()
    config = baseline_engine(flush_pepper=True)
    products = dict(config.products)
    products["ASH_COATED_OSMIUM"] = replace(
        products["ASH_COATED_OSMIUM"],
        fair_value_method=fv_method,
        fair_value_fallbacks=fv_fallbacks,
    )
    config = replace(config, products=products)
    trader = Trader(config=config)
    wrap_trader_with_v5micro_l1(
        trader,
        pepper_params=V5_MICRO_PEPPER_PARAMS,
        ash_params=L1_ASH_LADDER_PARAMS,
    )
    result = BacktestSimulator(trader=trader).run(replay)
    per_product = {name: r.pnl for name, r in result.per_product.items()}
    return {
        "total_pnl": result.total_pnl,
        "ash_pnl": per_product.get("ASH_COATED_OSMIUM", 0.0),
        "pep_pnl": per_product.get("INTARIAN_PEPPER_ROOT", 0.0),
        "trades": sum(r.trade_count for r in result.per_product.values()),
        "near_limit": sum(r.steps_near_limit for r in result.per_product.values()),
    }


def main() -> None:
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    variants = [
        ("weighted_mid (current)", "weighted_mid", ("wall_mid", "mid")),
        ("wall_mid", "wall_mid", ("weighted_mid", "mid")),
        ("filtered_wall_mid", "filtered_wall_mid", ("wall_mid", "weighted_mid", "mid")),
        ("microprice (sanity)", "microprice", ("wall_mid", "mid")),
        ("hybrid_wall_micro (blend)", "hybrid_wall_micro", ("wall_mid", "mid")),
    ]

    out: list[str] = [
        "# D6 — Wall-Mid Fair-Value Counterfactual for ASH",
        "",
        "Tests F2 + F4 convergent finding: top teams use wall_mid / "
        "max-amount-mid as fair value on stable products, not time-smoothed "
        "weighted_mid. Swap ASH primary FV method and measure ASH P&L on "
        "the R2 3-day local replay.",
        "",
        "**Caveat:** local backtest is not the truth source (F7 calibration "
        "mismatch). A positive direction on local backtest + plausible "
        "mechanism = upload-to-IMC-simulator candidate.",
        "",
        "| Variant | Total P&L | ASH P&L | ΔASH vs current | PEPPER | Trades | Near-limit |",
        "|---|---|---|---|---|---|---|",
    ]

    baseline_ash = None
    for label, fv, fb in variants:
        print(f"running: {label}")
        r = _run(fv, fb)
        if "current" in label:
            baseline_ash = r["ash_pnl"]
        delta = r["ash_pnl"] - (baseline_ash or 0.0)
        out.append(
            f"| {label} | {r['total_pnl']:,.0f} | {r['ash_pnl']:,.0f} | "
            f"{delta:+,.0f} | {r['pep_pnl']:,.0f} | {r['trades']} | "
            f"{r['near_limit']} |"
        )

    out += [
        "",
        "## Interpretation",
        "",
        "- **ΔASH > 500 on wall_mid / filtered_wall_mid:** F2/F4 mechanical "
        "fix is directionally correct. Build the IMC-simulator upload.",
        "- **ΔASH ≈ 0:** wall-mid fair value alone isn't the mechanism; we "
        "also need quote-inside-wall placement (F2 finding #2).",
        "- **ΔASH < 0:** our current weighted_mid is actually calibrated to "
        "our ladder; the fix requires both FV and placement together.",
        "",
        "## Next step if this diagnostic is positive",
        "",
        "1. Create a new engine-config variant `round2_v5micro_wallmid_ash_engine_config`.",
        "2. Use `src/scripts/round_2/export_test_variants.py` pattern to build "
        "an IMC test-upload bundle.",
        "3. Upload to IMC simulator alongside current `Promoted` variant for "
        "direct A/B.",
        "4. IF IMC test shows +500+ shells/sample on ASH, promote to R3 submission.",
    ]

    _OUTPUT.write_text("\n".join(out) + "\n")
    print(f"wrote {_OUTPUT}")


if __name__ == "__main__":
    main()

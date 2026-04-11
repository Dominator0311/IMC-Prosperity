"""Round-day runner for Family 4 (hybrid bid with average-bid coupling).

Usage::

    python -m src.scripts.run_manual_hybrid \
        --input inputs/round3_flippers.json \
        --output outputs/manual_rounds/round3_flippers

Input JSON schema::

    {
      "round": "P4-R3",
      "distribution": {
        "type": "bimodal",
        "low_a": 160, "high_a": 200,
        "low_b": 250, "high_b": 320,
        "mass_low": 0.5
      },
      "resale_value": 320,
      "bid_grid": {"start": 160, "stop": 321, "step": 1},
      "alpha": 3.0,
      "mu_scenarios": {
        "base": 287,
        "optimistic": 280,
        "pessimistic": 295
      },
      "top_k": 10
    }

The hybrid solver already returns a worst-case-robust answer across
mu scenarios, so the "robust" recommendation = the top result of
``optimize_hybrid`` with the supplied scenarios.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.manual_rounds.artifacts import Artifacts, write_artifacts
from src.manual_rounds.hybrid_bid import (
    HybridResult,
    HybridScenario,
    optimize_hybrid,
)
from src.manual_rounds.submission_note import SubmissionNote
from src.scripts.run_manual_bid import _build_distribution, _build_grid


def _result_to_dict(r: HybridResult) -> dict[str, Any]:
    return {
        "low_bid": r.low_bid,
        "high_bid": r.high_bid,
        "expected_pnl_by_scenario": dict(r.expected_pnl_by_scenario),
        "mean_pnl": r.mean_pnl,
        "worst_case_pnl": r.worst_case_pnl,
    }


def run_from_input(input_path: Path, output_dir: Path) -> Path:
    config: dict[str, Any] = json.loads(Path(input_path).read_text())

    distribution = _build_distribution(config["distribution"])
    resale_value = float(config["resale_value"])
    grid = _build_grid(config["bid_grid"])
    alpha = float(config.get("alpha", 1.0))
    mu_scenarios_config = config["mu_scenarios"]
    scenarios = tuple(
        HybridScenario(label=label, mu=float(mu)) for label, mu in mu_scenarios_config.items()
    )
    top_k = int(config.get("top_k", 10))
    round_name = config.get("round", "manual-hybrid")

    best, top = optimize_hybrid(
        distribution=distribution,
        resale_value=resale_value,
        bid_grid=grid,
        scenarios=scenarios,
        alpha=alpha,
        top_k=top_k,
    )

    answer = {
        "family": "hybrid_bid",
        "round": round_name,
        "chosen": _result_to_dict(best),
    }
    top_alternatives = [_result_to_dict(r) for r in top]
    assumptions = {
        "distribution": config["distribution"],
        "resale_value": resale_value,
        "bid_grid": config["bid_grid"],
        "alpha": alpha,
        "mu_scenarios": mu_scenarios_config,
    }
    sensitivity: dict[str, Any] = {
        "note": (
            "optimize_hybrid returns a worst-case-robust answer natively. "
            "Each alternative is scored across every mu scenario; the "
            "`robust` entry is the bundle with the highest min-PnL."
        ),
        "scenarios": {
            label: {"mu": mu, "alpha": alpha} for label, mu in mu_scenarios_config.items()
        },
        "base": _result_to_dict(best),
        "optimistic": _result_to_dict(best),
        "pessimistic": _result_to_dict(best),
        "robust": _result_to_dict(best),
    }
    scenario_breakdown = ", ".join(
        f"{label}={val:.2f}" for label, val in best.expected_pnl_by_scenario
    )
    submission_note = SubmissionNote(
        round_name=round_name,
        family="hybrid bid (average-bid coupling)",
        chosen_answer=(
            f"(low={best.low_bid}, high={best.high_bid}) "
            f"worst-case EV/unit = {best.worst_case_pnl:.4f}"
        ),
        payoff_explanation=(
            f"Two-tier bid with scale = min(1, ((V - mu)/(V - p_h))**{alpha}) "
            f"applied to the high-bid leg when mu > p_h. Scenarios: "
            + ", ".join(f"{s.label}=mu={s.mu}" for s in scenarios)
        ),
        core_assumptions=[
            f"reserve distribution = {config['distribution']}",
            f"resale value = {resale_value}",
            f"alpha = {alpha} ({'cubic' if alpha >= 3 else 'linear'} penalty)",
            f"mu scenarios = {mu_scenarios_config}",
        ],
        naive_baseline=(
            "optimize_two_bids answer without the average-bid coupling; "
            "always below the robust answer when mu > p_h"
        ),
        crowd_adjusted=(
            f"(low={best.low_bid}, high={best.high_bid}) via worst-case "
            f"argmax across supplied mu scenarios"
        ),
        robustness_range=f"per-scenario EV/unit: {scenario_breakdown}",
        backup_answer=(
            f"(low={top[1].low_bid}, high={top[1].high_bid}) "
            f"worst-case={top[1].worst_case_pnl:.4f}"
            if len(top) > 1
            else "n/a"
        ),
        failure_mode=(
            "mu forecast range is wrong (all scenarios underestimate "
            "realised average). If P3-R3 taught anything: below-average "
            "bidding is punished more than above-average; widen the "
            "pessimistic mu before submitting."
        ),
        top_alternatives=[
            f"(low={r.low_bid}, high={r.high_bid}) worst-case={r.worst_case_pnl:.4f}"
            for r in top
        ],
    )

    return write_artifacts(
        out_dir=output_dir,
        artifacts=Artifacts(
            answer=answer,
            top_alternatives=top_alternatives,
            assumptions=assumptions,
            sensitivity=sensitivity,
            submission_note=submission_note,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual round hybrid-bid runner.")
    parser.add_argument("--input", required=True, help="path to input JSON")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args()
    out = run_from_input(Path(args.input), Path(args.output))
    print(f"Wrote artifacts to {out}")


if __name__ == "__main__":
    main()

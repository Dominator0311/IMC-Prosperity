"""Round-day runner for Family 5 (news portfolio, integer QP).

Usage::

    python -m src.scripts.run_manual_news \
        --input inputs/round5_news.json \
        --output outputs/manual_rounds/round5_news

Input JSON schema::

    {
      "round": "P4-R5",
      "capital_per_unit": 10000,
      "fee_coefficient": 120,
      "budget": 100,
      "products": [
        {"name": "Haystacks",   "expected_return": -0.005, "rationale": "neutral news"},
        {"name": "Red Flags",   "expected_return":  0.050, "rationale": "bullish"},
        ...
      ],
      "sensitivity_shift": 0.02,
      "shrink_factor": 0.7
    }

Reports a base solution, an optimistic shift, a pessimistic shift, and
a robust (shrunk-returns) position vector.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.manual_rounds.artifacts import Artifacts, write_artifacts
from src.manual_rounds.news_portfolio import NewsPayoff, Product, solve
from src.manual_rounds.sensitivity import run_news_sensitivity
from src.manual_rounds.submission_note import SubmissionNote


def run_from_input(input_path: Path, output_dir: Path) -> Path:
    config: dict[str, Any] = json.loads(Path(input_path).read_text())

    payoff = NewsPayoff(
        capital_per_unit=float(config["capital_per_unit"]),
        fee_coefficient=float(config["fee_coefficient"]),
        budget=int(config.get("budget", 100)),
    )
    products = tuple(
        Product(
            name=str(p["name"]),
            expected_return=float(p["expected_return"]),
            rationale=str(p.get("rationale", "")),
        )
        for p in config["products"]
    )
    shift = float(config.get("sensitivity_shift", 0.02))
    shrink_factor = float(config.get("shrink_factor", 0.7))
    round_name = config.get("round", "manual-news")

    base_solution = solve(products, payoff)
    sensitivity = run_news_sensitivity(
        products=products,
        payoff=payoff,
        shift=shift,
        shrink_factor=shrink_factor,
    )

    answer = {
        "family": "news_portfolio",
        "round": round_name,
        "chosen": {
            "positions": dict(base_solution.positions),
            "total_pnl": base_solution.total_pnl,
            "budget_used": base_solution.budget_used,
            "binding": base_solution.binding,
        },
        "robust": {
            "positions": dict(sensitivity.robust_positions),
            "total_pnl_at_base": sensitivity.robust_total_pnl,
        },
    }
    # Top alternatives: each product's unconstrained target vs realised
    # position, so the operator can see where the L1 budget bit.
    top_alternatives = [
        {
            "name": name,
            "unconstrained_target": base_solution.unconstrained_positions[name],
            "base_position": base_solution.positions[name],
            "robust_position": sensitivity.robust_positions[name],
        }
        for name in base_solution.positions
    ]
    assumptions = {
        "capital_per_unit": payoff.capital_per_unit,
        "fee_coefficient": payoff.fee_coefficient,
        "budget": payoff.budget,
        "products": [
            {
                "name": p.name,
                "expected_return": p.expected_return,
                "rationale": p.rationale,
            }
            for p in products
        ],
        "sensitivity_shift": shift,
        "shrink_factor": shrink_factor,
    }

    chosen_positions_str = ", ".join(
        f"{name}={pos:+d}" for name, pos in base_solution.positions.items() if pos != 0
    )
    robust_positions_str = ", ".join(
        f"{name}={pos:+d}" for name, pos in sensitivity.robust_positions.items() if pos != 0
    )
    submission_note = SubmissionNote(
        round_name=round_name,
        family="news portfolio (integer QP)",
        chosen_answer=(
            f"base positions: {chosen_positions_str or '(all zero)'}; "
            f"PnL = {base_solution.total_pnl:.0f}"
        ),
        payoff_explanation=(
            f"Integer QP: max sum_i K*r_i*x_i - f*x_i^2 with "
            f"K={payoff.capital_per_unit}, f={payoff.fee_coefficient}, "
            f"subject to sum |x_i| <= {payoff.budget}. Solved by greedy "
            f"shrinkage of the closed-form unconstrained optimum."
        ),
        core_assumptions=[
            f"sentiment shift grid = +/-{shift}",
            f"shrink factor for robust answer = {shrink_factor}",
            "per-product sentiment estimates are from the round news PDF",
        ],
        naive_baseline=(
            "unconstrained optimum = "
            + ", ".join(
                f"{n}={x:+d}"
                for n, x in base_solution.unconstrained_positions.items()
                if x != 0
            )
        ),
        crowd_adjusted=(
            "no opponent effect; 'robust' = solve with returns shrunk by "
            f"{shrink_factor}"
        ),
        robustness_range=(
            f"base PnL = {base_solution.total_pnl:.0f}; "
            + ", ".join(
                f"{label}={result.total_pnl:.0f}"
                for label, result in sensitivity.scenarios.items()
            )
        ),
        backup_answer=f"robust positions: {robust_positions_str or '(all zero)'}",
        failure_mode=(
            "news-round anchoring to prior-year analogues (Red Flags "
            "headline looked bearish in P3; actual return was +50.9%). "
            "Re-read the current PDF end-to-end before trusting the "
            "sentiment estimates you typed in."
        ),
        top_alternatives=[
            f"{alt['name']}: unconstrained={alt['unconstrained_target']:+d}, "
            f"base={alt['base_position']:+d}, robust={alt['robust_position']:+d}"
            for alt in top_alternatives
        ],
    )

    return write_artifacts(
        out_dir=output_dir,
        artifacts=Artifacts(
            answer=answer,
            top_alternatives=top_alternatives,
            assumptions=assumptions,
            sensitivity=sensitivity.to_json(),
            submission_note=submission_note,
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual round news-portfolio runner.")
    parser.add_argument("--input", required=True, help="path to input JSON")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args()
    out = run_from_input(Path(args.input), Path(args.output))
    print(f"Wrote artifacts to {out}")


if __name__ == "__main__":
    main()

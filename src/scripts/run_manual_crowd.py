"""Round-day runner for Family 3 (game-theoretic crowding).

Usage::

    python -m src.scripts.run_manual_crowd \
        --input inputs/round2_containers.json \
        --output outputs/manual_rounds/round2_containers

Input JSON schema::

    {
      "round": "P4-R2",
      "cells": [
        {"name": "C1",  "multiplier": 10, "inhabitants": 1},
        {"name": "C2",  "multiplier": 80, "inhabitants": 6},
        ...
      ],
      "base_treasure": 10000,
      "coupling": 100,
      "pick_fees": [0, 50000],
      "max_picks": 2,
      "optimistic_exponent": 0.5,
      "pessimistic_exponent": 3.0
    }

Sensitivity is first-class here. Every run computes base / optimistic /
pessimistic crowd distributions and reports the bundle whose worst-case
net EV across all three is highest (the "robust" answer).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.manual_rounds.artifacts import Artifacts, write_artifacts
from src.manual_rounds.nash_crowd import Bundle, CrowdCell, CrowdPayoff, solve
from src.manual_rounds.sensitivity import run_crowd_sensitivity
from src.manual_rounds.submission_note import SubmissionNote


def _bundle_to_dict(bundle: Bundle) -> dict[str, Any]:
    return {
        "cells": list(bundle.cells),
        "size": bundle.size,
        "gross_ev": bundle.gross_ev,
        "fee": bundle.fee,
        "net_ev": bundle.net_ev,
    }


def run_from_input(input_path: Path, output_dir: Path) -> Path:
    config: dict[str, Any] = json.loads(Path(input_path).read_text())

    cells = tuple(
        CrowdCell(
            name=str(c["name"]),
            multiplier=float(c["multiplier"]),
            inhabitants=float(c["inhabitants"]),
        )
        for c in config["cells"]
    )
    payoff = CrowdPayoff(
        base_treasure=float(config["base_treasure"]),
        coupling=float(config.get("coupling", 100)),
    )
    pick_fees = tuple(float(f) for f in config["pick_fees"])
    max_picks = int(config["max_picks"])
    round_name = config.get("round", "manual-crowd")

    base_solution = solve(
        cells=cells,
        payoff=payoff,
        pick_fees=pick_fees,
        max_picks=max_picks,
        top_k=max(10, min(50, len(cells) * max_picks)),
    )
    sensitivity = run_crowd_sensitivity(
        cells=cells,
        payoff=payoff,
        pick_fees=pick_fees,
        max_picks=max_picks,
        optimistic_exponent=float(config.get("optimistic_exponent", 0.5)),
        pessimistic_exponent=float(config.get("pessimistic_exponent", 3.0)),
    )

    robust_bundle = sensitivity.robust_bundle
    base_best = base_solution.top_bundles[0]

    # The chosen answer is the robust bundle; we log the base-optimal
    # bundle as a "top alternative" if it differs.
    top_alternatives: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for bundle in (robust_bundle, *base_solution.top_bundles):
        key = tuple(bundle.cells)
        if key in seen:
            continue
        seen.add(key)
        top_alternatives.append(_bundle_to_dict(bundle))
        if len(top_alternatives) >= 10:
            break

    answer = {
        "family": "crowding",
        "round": round_name,
        "chosen": _bundle_to_dict(robust_bundle),
        "base_optimal": _bundle_to_dict(base_best),
        "robust_worst_case_net_ev": sensitivity.robust_worst_case_net_ev,
    }
    assumptions = {
        "cells": [
            {"name": c.name, "multiplier": c.multiplier, "inhabitants": c.inhabitants}
            for c in cells
        ],
        "base_treasure": payoff.base_treasure,
        "coupling": payoff.coupling,
        "pick_fees": list(pick_fees),
        "max_picks": max_picks,
        "optimistic_exponent": float(config.get("optimistic_exponent", 0.5)),
        "pessimistic_exponent": float(config.get("pessimistic_exponent", 3.0)),
    }

    chosen_summary = (
        "+".join(robust_bundle.cells)
        + f"  (net EV base={base_best.net_ev:.0f}, worst-case={sensitivity.robust_worst_case_net_ev:.0f})"
    )
    submission_note = SubmissionNote(
        round_name=round_name,
        family="game-theoretic crowding",
        chosen_answer=chosen_summary,
        payoff_explanation=(
            f"Per-cell EV = {payoff.base_treasure:.0f} * M / "
            f"(I + {payoff.coupling:.0f} * p). Fees: {list(pick_fees)}. "
            f"Scored across base (Nash) / optimistic (diffuse crowd) / "
            f"pessimistic (concentrated crowd)."
        ),
        core_assumptions=[
            "base crowd = logit quantal response at T=10000",
            f"optimistic crowd = mix(proportional_to_ratio^{config.get('optimistic_exponent', 0.5)}, uniform)",
            f"pessimistic crowd = proportional_to_ratio^{config.get('pessimistic_exponent', 3.0)}",
        ],
        naive_baseline=(
            "+".join(base_best.cells)
            + f"  (net EV = {base_best.net_ev:.0f} under Nash)"
        ),
        crowd_adjusted=(
            "+".join(robust_bundle.cells)
            + f"  (net EV worst-case = {sensitivity.robust_worst_case_net_ev:.0f})"
        ),
        robustness_range=(
            "scenarios: "
            + ", ".join(
                f"{label}={sr.best_bundle.net_ev:.0f}"
                for label, sr in sensitivity.scenarios.items()
            )
        ),
        backup_answer=(
            "+".join(base_solution.top_bundles[1].cells)
            if len(base_solution.top_bundles) > 1
            else "n/a"
        ),
        failure_mode=(
            "additional-pick fee is a trap: the base-optimal bundle may "
            "clear the fee under Nash but get crowded under the pessimistic "
            "scenario. Prefer the robust bundle unless the base margin is "
            "very large (> 2x the fee)."
        ),
        top_alternatives=[
            "+".join(alt["cells"]) + f" (net EV={alt['net_ev']:.0f})"
            for alt in top_alternatives[:5]
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
    parser = argparse.ArgumentParser(description="Manual round crowding runner.")
    parser.add_argument("--input", required=True, help="path to input JSON")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args()
    out = run_from_input(Path(args.input), Path(args.output))
    print(f"Wrote artifacts to {out}")


if __name__ == "__main__":
    main()

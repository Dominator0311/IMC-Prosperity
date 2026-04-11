"""Round-day runner for Family 2 (single-agent sealed bid).

Usage::

    python -m src.scripts.run_manual_bid \
        --input inputs/round1_bid.json \
        --output outputs/manual_rounds/round1_bid

Input JSON schema::

    {
      "round": "P4-R1",
      "distribution": {
        "type": "linear_ramp" | "uniform" | "bimodal",
        "low": 900, "high": 1000,         # for linear_ramp / uniform
        "low_a": 160, "high_a": 200,      # for bimodal
        "low_b": 250, "high_b": 320,      # for bimodal
        "mass_low": 0.5                   # for bimodal
      },
      "resale_value": 1000,
      "bid_grid": {"start": 900, "stop": 1001, "step": 1},
      "n_bids": 2,
      "top_k": 10
    }

Sensitivity for Family 2 reduces to the robustness of the EV-optimum
relative to the 2nd-best alternative, because the single-agent bidding
problem has no opponent model.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from src.manual_rounds.artifacts import Artifacts, write_artifacts
from src.manual_rounds.bid_optimizer import (
    BimodalUniformReserve,
    LinearRampReserve,
    OneBidResult,
    ReserveDistribution,
    TwoBidResult,
    UniformReserve,
    optimize_one_bid,
    optimize_two_bids,
)
from src.manual_rounds.submission_note import SubmissionNote


def _build_distribution(spec: dict[str, Any]) -> ReserveDistribution:
    dtype = spec["type"]
    if dtype == "uniform":
        return UniformReserve(low=float(spec["low"]), high=float(spec["high"]))
    if dtype == "linear_ramp":
        return LinearRampReserve(low=float(spec["low"]), high=float(spec["high"]))
    if dtype == "bimodal":
        return BimodalUniformReserve(
            low_a=float(spec["low_a"]),
            high_a=float(spec["high_a"]),
            low_b=float(spec["low_b"]),
            high_b=float(spec["high_b"]),
            mass_low=float(spec.get("mass_low", 0.5)),
        )
    raise ValueError(f"unknown distribution type: {dtype!r}")


def _build_grid(spec: dict[str, Any]) -> list[int]:
    return list(range(int(spec["start"]), int(spec["stop"]), int(spec.get("step", 1))))


def _one_bid_to_dict(r: OneBidResult) -> dict[str, Any]:
    return {"bid": r.bid, "expected_pnl_per_unit": r.expected_pnl_per_unit}


def _two_bid_to_dict(r: TwoBidResult) -> dict[str, Any]:
    return {
        "low_bid": r.low_bid,
        "high_bid": r.high_bid,
        "expected_pnl_per_unit": r.expected_pnl_per_unit,
    }


def run_from_input(input_path: Path, output_dir: Path) -> Path:
    config: dict[str, Any] = json.loads(Path(input_path).read_text())

    distribution = _build_distribution(config["distribution"])
    resale_value = float(config["resale_value"])
    grid = _build_grid(config["bid_grid"])
    n_bids = int(config.get("n_bids", 2))
    top_k = int(config.get("top_k", 10))
    round_name = config.get("round", "manual-bid")

    answer_detail: dict[str, Any]
    top_alternatives: Sequence[dict[str, Any]]

    if n_bids == 1:
        best_one, top_one = optimize_one_bid(
            distribution, resale_value=resale_value, bid_grid=grid, top_k=top_k
        )
        answer_detail = _one_bid_to_dict(best_one)
        top_alternatives = [_one_bid_to_dict(r) for r in top_one]
        chosen_summary = f"bid={best_one.bid} (EV/unit={best_one.expected_pnl_per_unit:.4f})"
        backup = (
            f"bid={top_one[1].bid} (EV/unit={top_one[1].expected_pnl_per_unit:.4f})"
            if len(top_one) > 1
            else "n/a"
        )
        naive_baseline = f"bid={grid[len(grid) // 2]} midpoint fallback"
        top_alts_rendered = [f"bid={r.bid} EV/unit={r.expected_pnl_per_unit:.4f}" for r in top_one]
        robustness = (
            f"top bid leads 2nd by "
            f"{top_one[0].expected_pnl_per_unit - top_one[1].expected_pnl_per_unit:.4f}"
            if len(top_one) > 1
            else "unique"
        )
    elif n_bids == 2:
        best_two, top_two = optimize_two_bids(
            distribution, resale_value=resale_value, bid_grid=grid, top_k=top_k
        )
        answer_detail = _two_bid_to_dict(best_two)
        top_alternatives = [_two_bid_to_dict(r) for r in top_two]
        chosen_summary = (
            f"(low={best_two.low_bid}, high={best_two.high_bid}) "
            f"EV/unit={best_two.expected_pnl_per_unit:.4f}"
        )
        backup = (
            f"(low={top_two[1].low_bid}, high={top_two[1].high_bid}) "
            f"EV/unit={top_two[1].expected_pnl_per_unit:.4f}"
            if len(top_two) > 1
            else "n/a"
        )
        naive_baseline = "single-bid answer (n_bids=1) is the trivial baseline"
        top_alts_rendered = [
            f"(low={r.low_bid}, high={r.high_bid}) EV/unit={r.expected_pnl_per_unit:.4f}"
            for r in top_two
        ]
        robustness = (
            f"top pair leads 2nd by "
            f"{top_two[0].expected_pnl_per_unit - top_two[1].expected_pnl_per_unit:.4f}"
            if len(top_two) > 1
            else "unique"
        )
    else:
        raise ValueError("n_bids must be 1 or 2")

    answer = {"family": "bid", "round": round_name, "chosen": answer_detail}
    assumptions = {
        "distribution": config["distribution"],
        "resale_value": resale_value,
        "bid_grid": config["bid_grid"],
        "n_bids": n_bids,
    }
    sensitivity = {
        "note": (
            "Single-agent sealed-bid problem has no opponent model. "
            "Sensitivity reduces to the margin between the EV-optimum "
            "and its top alternatives. Be aware: for sampled-reserve "
            "rounds (e.g. P2-R1 with 5000 fish) the EV-optimal answer "
            "may only be ex-post optimal on a small fraction of samples."
        ),
        "base": answer_detail,
        "optimistic": answer_detail,
        "pessimistic": answer_detail,
        "robust": answer_detail,
    }
    submission_note = SubmissionNote(
        round_name=round_name,
        family="bid optimization",
        chosen_answer=chosen_summary,
        payoff_explanation=(
            f"Two-bid payoff against reserve distribution {config['distribution']['type']}; "
            f"resale value = {resale_value}."
            if n_bids == 2
            else f"Single-bid payoff against reserve distribution; resale value = {resale_value}."
        ),
        core_assumptions=[
            f"reserve distribution = {config['distribution']}",
            f"resale value = {resale_value}",
            f"bid grid = {config['bid_grid']}",
        ],
        naive_baseline=naive_baseline,
        crowd_adjusted="not applicable (single-agent)",
        robustness_range=robustness,
        backup_answer=backup,
        failure_mode=(
            "reserve distribution misread from puzzle text; EV-optimum may "
            "not be ex-post optimum if round scores on realised sample"
        ),
        top_alternatives=top_alts_rendered,
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
    parser = argparse.ArgumentParser(description="Manual round bid optimizer runner.")
    parser.add_argument("--input", required=True, help="path to input JSON")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args()
    out = run_from_input(Path(args.input), Path(args.output))
    print(f"Wrote artifacts to {out}")


if __name__ == "__main__":
    main()

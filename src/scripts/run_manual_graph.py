"""Round-day runner for Family 1 (graph / path arbitrage).

Usage::

    python -m src.scripts.run_manual_graph \
        --input inputs/round1.json \
        --output outputs/manual_rounds/round1_graph

Input JSON schema::

    {
      "round": "P4-R1",
      "currencies": ["A", "B", "C", "D"],
      "rates": [[1.0, 1.4, 0.5, 0.7], [...], [...], [...]],
      "start": "A",
      "end": "A",
      "max_hops": 5,
      "top_k": 5
    }

Artifacts written to ``<output_dir>``:

- ``answer.json``
- ``top_alternatives.json``
- ``assumptions.json``
- ``sensitivity.json``
- ``submission_note.md``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.manual_rounds.artifacts import Artifacts, write_artifacts
from src.manual_rounds.graph_arbitrage import Path as GraphPath
from src.manual_rounds.graph_arbitrage import RateMatrix, best_path
from src.manual_rounds.submission_note import SubmissionNote


def _path_to_dict(path: GraphPath) -> dict[str, Any]:
    return {
        "hops": list(path.hops),
        "product": path.product,
        "return_pct": (path.product - 1.0) * 100,
        "n_trades": len(path.hops) - 1,
    }


def run_from_input(input_path: Path, output_dir: Path) -> Path:
    config: dict[str, Any] = json.loads(Path(input_path).read_text())

    matrix = RateMatrix(
        currencies=tuple(config["currencies"]),
        rates=tuple(tuple(float(v) for v in row) for row in config["rates"]),
    )
    start = config["start"]
    end = config["end"]
    max_hops = int(config.get("max_hops", 5))
    top_k = int(config.get("top_k", 5))
    round_name = config.get("round", "manual-graph")

    best, top = best_path(matrix, start=start, end=end, max_hops=max_hops, top_k=top_k)

    answer = {
        "family": "graph",
        "round": round_name,
        "chosen": _path_to_dict(best),
    }
    top_alternatives = [_path_to_dict(p) for p in top]
    assumptions = {
        "currencies": list(matrix.currencies),
        "rates": [list(row) for row in matrix.rates],
        "start": start,
        "end": end,
        "max_hops": max_hops,
    }
    sensitivity = {
        "note": (
            "Graph/path arbitrage is deterministic. Sensitivity reduces "
            "to 'is the winning path unique?' — we report the gap between "
            "the best and second-best path as the robustness margin."
        ),
        "base": {"product": best.product, "hops": list(best.hops)},
        "optimistic": {"product": best.product, "hops": list(best.hops)},
        "pessimistic": {"product": best.product, "hops": list(best.hops)},
        "robust": {
            "product": best.product,
            "hops": list(best.hops),
            "margin_vs_second": (
                (top[0].product / top[1].product - 1.0) * 100 if len(top) > 1 else None
            ),
        },
    }
    submission_note = SubmissionNote(
        round_name=round_name,
        family="graph/path arbitrage",
        chosen_answer=" -> ".join(best.hops) + f"  (product={best.product:.4f})",
        payoff_explanation=(
            f"Product of {len(best.hops) - 1} edge weights on the rate matrix. "
            f"Returns {((best.product - 1) * 100):.2f}% over {start}->{end}."
        ),
        core_assumptions=[
            f"rate matrix is deterministic ({len(matrix.currencies)}x{len(matrix.currencies)})",
            f"budget = {max_hops} trades",
            "no hidden frictions (slippage, tariffs, fills) in the puzzle text",
        ],
        naive_baseline=f"no-op (stay in {start}) = 1.000",
        crowd_adjusted="single-agent problem; no opponent effect",
        robustness_range=(
            f"winning path leads the 2nd best by "
            f"{((top[0].product / top[1].product - 1.0) * 100):.2f}%"
            if len(top) > 1
            else "unique path (no alternatives enumerated)"
        ),
        backup_answer=(
            " -> ".join(top[1].hops) + f" (product={top[1].product:.4f})"
            if len(top) > 1
            else "n/a"
        ),
        failure_mode="rate matrix misread from the puzzle text",
        top_alternatives=[
            " -> ".join(p.hops) + f"  (product={p.product:.4f})" for p in top
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
    parser = argparse.ArgumentParser(description="Manual round graph/path runner.")
    parser.add_argument("--input", required=True, help="path to input JSON")
    parser.add_argument("--output", required=True, help="output directory")
    args = parser.parse_args()
    out = run_from_input(Path(args.input), Path(args.output))
    print(f"Wrote artifacts to {out}")


if __name__ == "__main__":
    main()

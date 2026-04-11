"""Integration tests for the manual-round CLI runners.

These tests mimic the full round-day loop for each family:

1. Write a canned input JSON to a temp directory.
2. Invoke the runner's ``run_from_input`` function with the input path
   and an output directory.
3. Assert every expected artifact file exists.
4. Parse the JSON artifacts and assert key fields match the solver's
   known regression answers.
5. Render the submission note and confirm the required checklist
   sections are present.

The point is to catch wiring errors between solver -> artifact writer
-> submission note renderer -- not to re-verify the solvers themselves
(those have unit tests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.manual_rounds.artifacts import (
    ANSWER_FILENAME,
    ARTIFACT_FILENAMES,
    read_artifacts,
)
from src.scripts.run_manual_crowd import run_from_input as run_crowd
from src.scripts.run_manual_graph import run_from_input as run_graph
from src.scripts.run_manual_news import run_from_input as run_news


def _write_input(tmp_path: Path, filename: str, payload: dict[str, object]) -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    return path


@pytest.mark.integration
def test_graph_runner_writes_full_artifact_pack(tmp_path: Path) -> None:
    # Prosperity 3 Round 1 FX matrix -- the runner must reproduce the
    # canonical Shell -> Snow -> SiNug -> Pizza -> Snow -> Shell path.
    input_path = _write_input(
        tmp_path,
        "round1.json",
        {
            "round": "P3-R1",
            "currencies": ["Snow", "Pizza", "SiNug", "Shell"],
            "rates": [
                [1.00, 1.45, 0.52, 0.72],
                [0.70, 1.00, 0.31, 0.48],
                [1.95, 3.10, 1.00, 1.49],
                [1.34, 1.98, 0.64, 1.00],
            ],
            "start": "Shell",
            "end": "Shell",
            "max_hops": 5,
            "top_k": 5,
        },
    )
    output_dir = tmp_path / "graph_out"
    returned = run_graph(input_path, output_dir)
    assert returned == output_dir

    # Every expected artifact must exist.
    for name in ARTIFACT_FILENAMES:
        assert (output_dir / name).exists(), f"missing {name}"

    # Answer payload.
    artifacts = read_artifacts(output_dir)
    answer = artifacts["answer"]
    assert answer["family"] == "graph"
    assert answer["chosen"]["hops"] == [
        "Shell",
        "Snow",
        "SiNug",
        "Pizza",
        "Snow",
        "Shell",
    ]
    assert 1.088 < answer["chosen"]["product"] < 1.090

    # Submission note contains all required sections.
    note_md = artifacts["submission_note_md"]
    for section in (
        "Problem family",
        "Chosen answer",
        "Payoff structure",
        "Core assumptions",
        "Robustness range",
        "Biggest failure mode",
        "Top alternatives considered",
    ):
        assert section in note_md

    # Sensitivity block is present even when trivial.
    assert "base" in artifacts["sensitivity"]
    assert "robust" in artifacts["sensitivity"]


@pytest.mark.integration
def test_crowd_runner_produces_base_and_robust(tmp_path: Path) -> None:
    # Prosperity 3 Round 2 containers (10 cells, 50k second pick).
    input_path = _write_input(
        tmp_path,
        "round2.json",
        {
            "round": "P3-R2",
            "cells": [
                {"name": "C1", "multiplier": 10, "inhabitants": 1},
                {"name": "C2", "multiplier": 80, "inhabitants": 6},
                {"name": "C3", "multiplier": 37, "inhabitants": 3},
                {"name": "C4", "multiplier": 17, "inhabitants": 1},
                {"name": "C5", "multiplier": 31, "inhabitants": 2},
                {"name": "C6", "multiplier": 50, "inhabitants": 4},
                {"name": "C7", "multiplier": 89, "inhabitants": 8},
                {"name": "C8", "multiplier": 73, "inhabitants": 4},
                {"name": "C9", "multiplier": 20, "inhabitants": 2},
                {"name": "C10", "multiplier": 90, "inhabitants": 10},
            ],
            "base_treasure": 10000,
            "coupling": 100,
            "pick_fees": [0, 50000],
            "max_picks": 2,
        },
    )
    output_dir = tmp_path / "crowd_out"
    returned = run_crowd(input_path, output_dir)
    assert returned == output_dir

    for name in ARTIFACT_FILENAMES:
        assert (output_dir / name).exists()

    artifacts = read_artifacts(output_dir)

    # Answer must reference both the robust choice and the base-optimal.
    answer = artifacts["answer"]
    assert answer["family"] == "crowding"
    assert "chosen" in answer and "cells" in answer["chosen"]
    assert "base_optimal" in answer and "cells" in answer["base_optimal"]
    assert "robust_worst_case_net_ev" in answer

    # Sensitivity must include all three scenarios + a robust pick.
    sensitivity = artifacts["sensitivity"]
    assert set(sensitivity["scenarios"].keys()) == {"base", "optimistic", "pessimistic"}
    for label in ("base", "optimistic", "pessimistic"):
        assert "best_bundle" in sensitivity["scenarios"][label]
    assert "cells" in sensitivity["robust"]

    # Robust worst-case net EV <= base-scenario net EV by construction.
    base_net = sensitivity["scenarios"]["base"]["best_bundle"]["net_ev"]
    robust_worst = sensitivity["robust"]["worst_case_net_ev"]
    assert robust_worst <= base_net + 1e-6

    # Assumptions echo the inputs -- cheap typo detection.
    assumptions = artifacts["assumptions"]
    assert assumptions["base_treasure"] == 10000
    assert assumptions["max_picks"] == 2
    assert len(assumptions["cells"]) == 10


@pytest.mark.integration
def test_news_runner_reports_sensitivity_and_robust(tmp_path: Path) -> None:
    # Mini news round with 4 products and realistic-ish returns.
    input_path = _write_input(
        tmp_path,
        "round5.json",
        {
            "round": "P4-R5-demo",
            "capital_per_unit": 10000,
            "fee_coefficient": 120,
            "budget": 100,
            "products": [
                {"name": "Alpha", "expected_return": 0.05, "rationale": "bullish"},
                {"name": "Beta", "expected_return": -0.04, "rationale": "bearish"},
                {"name": "Gamma", "expected_return": 0.02, "rationale": "weak bull"},
                {"name": "Delta", "expected_return": -0.01, "rationale": "mild bear"},
            ],
            "sensitivity_shift": 0.02,
            "shrink_factor": 0.7,
        },
    )
    output_dir = tmp_path / "news_out"
    returned = run_news(input_path, output_dir)
    assert returned == output_dir

    for name in ARTIFACT_FILENAMES:
        assert (output_dir / name).exists()

    answer = json.loads((output_dir / ANSWER_FILENAME).read_text())
    assert answer["family"] == "news_portfolio"
    assert "positions" in answer["chosen"]
    assert "positions" in answer["robust"]

    sensitivity = json.loads((output_dir / "sensitivity.json").read_text())
    assert set(sensitivity["scenarios"].keys()) == {"base", "optimistic", "pessimistic"}
    for label in ("base", "optimistic", "pessimistic"):
        s = sensitivity["scenarios"][label]
        assert "positions" in s
        assert "total_pnl" in s
        assert "binding" in s
    assert "positions" in sensitivity["robust"]

    # Shrunk-robust positions must not exceed base positions in absolute
    # value (since shrinking returns can only reduce each bet).
    base_positions = answer["chosen"]["positions"]
    robust_positions = answer["robust"]["positions"]
    for name, base_x in base_positions.items():
        robust_x = robust_positions[name]
        assert abs(robust_x) <= abs(base_x), (
            f"robust position for {name} ({robust_x}) exceeds base ({base_x})"
        )

    # Submission note is non-empty and has the checklist sections.
    note = (output_dir / "submission_note.md").read_text()
    for section in (
        "Problem family",
        "Core assumptions",
        "Robustness range",
        "Biggest failure mode",
    ):
        assert section in note

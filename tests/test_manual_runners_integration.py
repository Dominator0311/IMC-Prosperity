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
    MANIFEST_FILENAME,
    read_artifacts,
)
from src.scripts.run_manual_bid import run_from_input as run_bid
from src.scripts.run_manual_crowd import run_from_input as run_crowd
from src.scripts.run_manual_graph import run_from_input as run_graph
from src.scripts.run_manual_hybrid import run_from_input as run_hybrid
from src.scripts.run_manual_news import run_from_input as run_news


def _write_input(tmp_path: Path, filename: str, payload: dict[str, object]) -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps(payload))
    return path


def _assert_manifest_shape(
    manifest: dict[str, object] | None,
    expected_runner: str,
    expected_family: str,
    expected_input_path: Path,
) -> None:
    """Every runner must stamp an auditable manifest.json.

    Required keys: runner_name, family, input_path, timestamp,
    schema_version. git_commit and git_dirty may be None when running
    outside a git checkout; they must still be present as keys.
    """
    assert manifest is not None, "manifest.json is missing"
    for key in (
        "runner_name",
        "family",
        "input_path",
        "timestamp",
        "schema_version",
        "git_commit",
        "git_dirty",
    ):
        assert key in manifest, f"manifest missing required key {key!r}"
    assert manifest["runner_name"] == expected_runner
    assert manifest["family"] == expected_family
    # input_path is stored absolute; compare against resolved.
    assert Path(str(manifest["input_path"])) == expected_input_path.resolve()
    # Timestamp must parse as ISO 8601 with Z suffix.
    ts = str(manifest["timestamp"])
    assert ts.endswith("Z") and "T" in ts, f"bad timestamp {ts!r}"
    assert isinstance(manifest["schema_version"], int)


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

    # Manifest is present and well-formed.
    assert (output_dir / MANIFEST_FILENAME).exists()
    _assert_manifest_shape(
        artifacts["manifest"],
        expected_runner="run_manual_graph",
        expected_family="graph",
        expected_input_path=input_path,
    )


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

    _assert_manifest_shape(
        artifacts["manifest"],
        expected_runner="run_manual_crowd",
        expected_family="crowding",
        expected_input_path=input_path,
    )


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

    _assert_manifest_shape(
        read_artifacts(output_dir)["manifest"],
        expected_runner="run_manual_news",
        expected_family="news_portfolio",
        expected_input_path=input_path,
    )


@pytest.mark.integration
def test_bid_runner_reproduces_p2_r1_goldfish(tmp_path: Path) -> None:
    # Prosperity 2 Round 1: linear reserve on [900, 1000], resale 1000,
    # two bids. Canonical EV-optimal answer = (952, 978).
    input_path = _write_input(
        tmp_path,
        "round1_goldfish.json",
        {
            "round": "P2-R1",
            "distribution": {"type": "linear_ramp", "low": 900, "high": 1000},
            "resale_value": 1000,
            "bid_grid": {"start": 900, "stop": 1001, "step": 1},
            "n_bids": 2,
            "top_k": 10,
        },
    )
    output_dir = tmp_path / "bid_out"
    returned = run_bid(input_path, output_dir)
    assert returned == output_dir

    for name in ARTIFACT_FILENAMES:
        assert (output_dir / name).exists(), f"missing {name}"

    artifacts = read_artifacts(output_dir)
    answer = artifacts["answer"]
    assert answer["family"] == "bid"
    assert answer["round"] == "P2-R1"
    chosen = answer["chosen"]
    assert chosen["low_bid"] == 952
    assert chosen["high_bid"] == 978
    assert chosen["expected_pnl_per_unit"] > 0

    # Top alternatives must be sorted descending by EV and include the
    # chosen pair as the head.
    top = artifacts["top_alternatives"]["alternatives"]
    assert len(top) >= 2
    assert (top[0]["low_bid"], top[0]["high_bid"]) == (952, 978)
    for i in range(len(top) - 1):
        assert top[i]["expected_pnl_per_unit"] >= top[i + 1]["expected_pnl_per_unit"]

    # Assumptions echo the raw input so the operator can typo-diff.
    assumptions = artifacts["assumptions"]
    assert assumptions["distribution"]["type"] == "linear_ramp"
    assert assumptions["resale_value"] == 1000
    assert assumptions["n_bids"] == 2

    # Sensitivity block is trivial for single-agent bidding but must
    # still contain base/robust.
    sensitivity = artifacts["sensitivity"]
    assert "base" in sensitivity
    assert "robust" in sensitivity

    # Submission note is fully populated.
    note = artifacts["submission_note_md"]
    for section in (
        "Problem family",
        "Chosen answer",
        "Payoff structure",
        "Core assumptions",
        "Biggest failure mode",
    ):
        assert section in note
    assert "952" in note and "978" in note

    _assert_manifest_shape(
        artifacts["manifest"],
        expected_runner="run_manual_bid",
        expected_family="bid",
        expected_input_path=input_path,
    )


@pytest.mark.integration
def test_hybrid_runner_reproduces_p3_r3_flippers(tmp_path: Path) -> None:
    # Prosperity 3 Round 3: bimodal reserve on [160,200] and [250,320],
    # resale 320, cubic penalty (alpha=3), mu forecast in the 280-300
    # band. Worst-case-robust optimum should sit with low ~200 and
    # high in the 285-305 region.
    input_path = _write_input(
        tmp_path,
        "round3_flippers.json",
        {
            "round": "P3-R3",
            "distribution": {
                "type": "bimodal",
                "low_a": 160,
                "high_a": 200,
                "low_b": 250,
                "high_b": 320,
                "mass_low": 0.5,
            },
            "resale_value": 320,
            "bid_grid": {"start": 160, "stop": 321, "step": 1},
            "alpha": 3.0,
            "mu_scenarios": {
                "base": 287,
                "optimistic": 280,
                "pessimistic": 295,
            },
            "top_k": 10,
        },
    )
    output_dir = tmp_path / "hybrid_out"
    returned = run_hybrid(input_path, output_dir)
    assert returned == output_dir

    for name in ARTIFACT_FILENAMES:
        assert (output_dir / name).exists(), f"missing {name}"

    artifacts = read_artifacts(output_dir)
    answer = artifacts["answer"]
    assert answer["family"] == "hybrid_bid"
    chosen = answer["chosen"]
    # Low bid should land near the top of the lower reserve mode.
    assert 195 <= chosen["low_bid"] <= 200
    # High bid sits in the robust 285-310 band (worst-case over mu
    # scenarios), above the individual single-agent optimum of ~284.
    assert 285 <= chosen["high_bid"] <= 310

    # Expected PnL must be reported per scenario and the worst-case
    # must be <= each scenario PnL.
    ev_by_scenario = chosen["expected_pnl_by_scenario"]
    assert set(ev_by_scenario.keys()) == {"base", "optimistic", "pessimistic"}
    worst = chosen["worst_case_pnl"]
    for pnl in ev_by_scenario.values():
        assert pnl >= worst - 1e-9

    # Top alternatives sorted descending by worst-case PnL.
    top = artifacts["top_alternatives"]["alternatives"]
    assert len(top) >= 2
    for i in range(len(top) - 1):
        assert top[i]["worst_case_pnl"] >= top[i + 1]["worst_case_pnl"]

    # Sensitivity block documents every mu scenario.
    sensitivity = artifacts["sensitivity"]
    assert set(sensitivity["scenarios"].keys()) == {"base", "optimistic", "pessimistic"}
    for label in ("base", "optimistic", "pessimistic"):
        assert sensitivity["scenarios"][label]["alpha"] == 3.0

    # Submission note has every checklist section.
    note = artifacts["submission_note_md"]
    for section in (
        "Problem family",
        "Chosen answer",
        "Payoff structure",
        "Core assumptions",
        "Robustness range",
        "Biggest failure mode",
    ):
        assert section in note

    _assert_manifest_shape(
        artifacts["manifest"],
        expected_runner="run_manual_hybrid",
        expected_family="hybrid_bid",
        expected_input_path=input_path,
    )

"""Round-day artifact writer.

Every manual-round runner in ``src/scripts/run_manual_*.py`` dumps the
same standardized five-file pack into its output directory:

- ``answer.json``           — the chosen answer and its net value
- ``top_alternatives.json`` — the top-N ranked alternatives
- ``assumptions.json``      — the exact inputs the solver saw
- ``sensitivity.json``      — base / optimistic / pessimistic / robust
- ``submission_note.md``    — rendered submission-note markdown

This module is deliberately dumb: it serialises dicts and writes files.
Solvers are responsible for building the payloads, not for touching the
filesystem, so that every solver stays testable in-memory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.manual_rounds.submission_note import SubmissionNote

ANSWER_FILENAME = "answer.json"
TOP_ALT_FILENAME = "top_alternatives.json"
ASSUMPTIONS_FILENAME = "assumptions.json"
SENSITIVITY_FILENAME = "sensitivity.json"
SUBMISSION_NOTE_FILENAME = "submission_note.md"

ARTIFACT_FILENAMES: tuple[str, ...] = (
    ANSWER_FILENAME,
    TOP_ALT_FILENAME,
    ASSUMPTIONS_FILENAME,
    SENSITIVITY_FILENAME,
    SUBMISSION_NOTE_FILENAME,
)


@dataclass(frozen=True)
class Artifacts:
    """Everything a runner needs to hand back to the operator.

    ``answer`` should contain at least ``{"family": ..., "value": ...,
    "detail": ...}``. Use whatever detail shape makes sense per family;
    the renderer does not care.
    """

    answer: Mapping[str, Any]
    top_alternatives: Sequence[Mapping[str, Any]]
    assumptions: Mapping[str, Any]
    sensitivity: Mapping[str, Any]
    submission_note: SubmissionNote
    extras: Mapping[str, Any] = field(default_factory=dict)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_artifacts(out_dir: Path, artifacts: Artifacts) -> Path:
    """Write the five standard files to ``out_dir``.

    Creates the directory if it does not exist. Returns the directory
    for call-site chaining.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / ANSWER_FILENAME, dict(artifacts.answer))
    _write_json(
        out_dir / TOP_ALT_FILENAME,
        {"alternatives": [dict(alt) for alt in artifacts.top_alternatives]},
    )
    _write_json(out_dir / ASSUMPTIONS_FILENAME, dict(artifacts.assumptions))
    _write_json(out_dir / SENSITIVITY_FILENAME, dict(artifacts.sensitivity))
    (out_dir / SUBMISSION_NOTE_FILENAME).write_text(artifacts.submission_note.render())
    return out_dir


def read_artifacts(out_dir: Path) -> dict[str, Any]:
    """Load the three JSON artifacts back as a single dict.

    Useful for integration tests and for operators who want to diff two
    runs. The submission note is returned as a string under the
    ``submission_note_md`` key.
    """
    missing = [name for name in ARTIFACT_FILENAMES if not (out_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing artifacts in {out_dir}: {missing}")
    return {
        "answer": json.loads((out_dir / ANSWER_FILENAME).read_text()),
        "top_alternatives": json.loads((out_dir / TOP_ALT_FILENAME).read_text()),
        "assumptions": json.loads((out_dir / ASSUMPTIONS_FILENAME).read_text()),
        "sensitivity": json.loads((out_dir / SENSITIVITY_FILENAME).read_text()),
        "submission_note_md": (out_dir / SUBMISSION_NOTE_FILENAME).read_text(),
    }

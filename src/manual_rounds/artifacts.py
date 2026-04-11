"""Round-day artifact writer.

Every manual-round runner in ``src/scripts/run_manual_*.py`` dumps the
same standardized artifact pack into its output directory:

- ``answer.json``           — the chosen answer and its net value
- ``top_alternatives.json`` — the top-N ranked alternatives
- ``assumptions.json``      — the exact inputs the solver saw
- ``sensitivity.json``      — base / optimistic / pessimistic / robust
- ``submission_note.md``    — rendered submission-note markdown
- ``manifest.json``         — provenance (runner, family, input path,
                              timestamp, git commit). Tiny, optional,
                              always auto-populated by the runners.

This module is deliberately dumb: it serialises dicts and writes files.
Solvers are responsible for building the payloads, not for touching the
filesystem, so that every solver stays testable in-memory.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.manual_rounds.submission_note import SubmissionNote

ANSWER_FILENAME = "answer.json"
TOP_ALT_FILENAME = "top_alternatives.json"
ASSUMPTIONS_FILENAME = "assumptions.json"
SENSITIVITY_FILENAME = "sensitivity.json"
SUBMISSION_NOTE_FILENAME = "submission_note.md"
MANIFEST_FILENAME = "manifest.json"

ARTIFACT_FILENAMES: tuple[str, ...] = (
    ANSWER_FILENAME,
    TOP_ALT_FILENAME,
    ASSUMPTIONS_FILENAME,
    SENSITIVITY_FILENAME,
    SUBMISSION_NOTE_FILENAME,
    MANIFEST_FILENAME,
)

# The artifacts that held the original 5-file contract. ``read_artifacts``
# still requires these; ``manifest.json`` is tolerated as absent so that
# any hand-built or legacy artifact pack can still be read.
REQUIRED_ARTIFACT_FILENAMES: tuple[str, ...] = (
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

    ``manifest`` is a provenance dict (runner, family, input path, ISO
    timestamp, git commit). Runners build it with ``build_manifest``
    and pass it through; if ``None`` the manifest file is skipped (used
    by tests that bypass the runner layer).
    """

    answer: Mapping[str, Any]
    top_alternatives: Sequence[Mapping[str, Any]]
    assumptions: Mapping[str, Any]
    sensitivity: Mapping[str, Any]
    submission_note: SubmissionNote
    manifest: Mapping[str, Any] | None = None
    extras: Mapping[str, Any] = field(default_factory=dict)


def _git_commit_hash() -> str | None:
    """Best-effort short git hash for the current HEAD.

    Returns ``None`` if git is unavailable, we are not inside a repo,
    or the subprocess fails for any reason. Manifest writing must never
    break a round-day run because of git environment issues.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _git_dirty() -> bool | None:
    """True if the working tree has uncommitted changes, None if unknown."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def build_manifest(
    runner_name: str,
    family: str,
    input_path: Path,
) -> dict[str, Any]:
    """Assemble the provenance payload every runner writes.

    Fields:

    - ``runner_name``: e.g. ``"run_manual_crowd"``
    - ``family``:      one of graph/bid/crowding/hybrid_bid/news_portfolio
    - ``input_path``:  absolute path of the JSON config the runner read
    - ``timestamp``:   ISO 8601 UTC, second-precision
    - ``git_commit``:  short SHA or ``None`` if unavailable
    - ``git_dirty``:   bool or ``None``; warns operator if artifacts
                       were produced from an uncommitted tree
    - ``schema_version``: monotonic int for future manifest evolution
    """
    return {
        "runner_name": runner_name,
        "family": family,
        "input_path": str(Path(input_path).resolve()),
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit_hash(),
        "git_dirty": _git_dirty(),
        "schema_version": 1,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def write_artifacts(out_dir: Path, artifacts: Artifacts) -> Path:
    """Write the standard artifact files to ``out_dir``.

    Creates the directory if it does not exist. Returns the directory
    for call-site chaining. ``manifest.json`` is written iff
    ``artifacts.manifest`` is not ``None``.
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
    if artifacts.manifest is not None:
        _write_json(out_dir / MANIFEST_FILENAME, dict(artifacts.manifest))
    return out_dir


def read_artifacts(out_dir: Path) -> dict[str, Any]:
    """Load the artifact pack back as a single dict.

    Useful for integration tests and for operators who want to diff two
    runs. The submission note is returned as a string under the
    ``submission_note_md`` key. The manifest is returned under
    ``manifest`` and is ``None`` if the file is absent (so legacy
    packs still load).
    """
    missing = [name for name in REQUIRED_ARTIFACT_FILENAMES if not (out_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"missing artifacts in {out_dir}: {missing}")
    manifest_path = out_dir / MANIFEST_FILENAME
    manifest: dict[str, Any] | None = (
        json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    )
    return {
        "answer": json.loads((out_dir / ANSWER_FILENAME).read_text()),
        "top_alternatives": json.loads((out_dir / TOP_ALT_FILENAME).read_text()),
        "assumptions": json.loads((out_dir / ASSUMPTIONS_FILENAME).read_text()),
        "sensitivity": json.loads((out_dir / SENSITIVITY_FILENAME).read_text()),
        "submission_note_md": (out_dir / SUBMISSION_NOTE_FILENAME).read_text(),
        "manifest": manifest,
    }

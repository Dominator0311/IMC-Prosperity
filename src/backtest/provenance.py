"""Provenance helpers for review packs.

Every Phase 4 review pack should be reproducible: given the manifest
we should know which code commit, which input CSVs, and which engine
configuration produced it. This module collects that information so
``reporting.py`` can stay focused on layout.

Design notes:

- Git is queried via ``subprocess.run`` with a short timeout and a
  ``try / except`` net. If git is unavailable, the pack still writes
  successfully with ``git_commit`` and ``git_dirty`` set to ``None``.
- No mutation of repository state. Read-only commands only.
- The manifest is a plain ``dict`` so callers can extend it without
  touching a new dataclass layout.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.config import EngineConfig, ProductConfig
from src.core.fair_value import ESTIMATORS

_GIT_TIMEOUT_SECONDS = 2.0


def git_commit(*, cwd: Path | str | None = None) -> str | None:
    """Return the short commit hash at ``HEAD``, or ``None`` on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def git_dirty(*, cwd: Path | str | None = None) -> bool | None:
    """Return ``True`` if the working tree has uncommitted changes.

    Returns ``None`` if git is unavailable or the command fails.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return bool(result.stdout.strip())


def python_version() -> str:
    return (
        f"{sys.version_info.major}."
        f"{sys.version_info.minor}."
        f"{sys.version_info.micro}"
    )


def serialize_engine_config(config: EngineConfig | None) -> dict[str, Any] | None:
    if config is None:
        return None
    return {
        "state_version": config.state_version,
        "max_trader_data_chars": config.max_trader_data_chars,
        "diagnostics_verbosity": config.diagnostics_verbosity,
        "products": {
            name: _serialize_product_config(product)
            for name, product in config.products.items()
        },
    }


def _serialize_product_config(product: ProductConfig) -> dict[str, Any]:
    # ProductConfig is a frozen dataclass; asdict is safe and stable.
    if not is_dataclass(product):  # defensive; kept for mypy narrowing
        raise TypeError("Expected a ProductConfig dataclass")
    return asdict(product)


def estimators_per_product(
    config: EngineConfig | None,
) -> dict[str, dict[str, Any]] | None:
    if config is None:
        return None
    result: dict[str, dict[str, Any]] = {}
    known = set(ESTIMATORS)
    for name, product in config.products.items():
        result[name] = {
            "primary": product.fair_value_method,
            "primary_known": product.fair_value_method in known,
            "fallbacks": list(product.fair_value_fallbacks),
        }
    return result


def build_manifest(
    *,
    run_id: str,
    run_label: str,
    generated_at: datetime | None = None,
    engine_config: EngineConfig | None,
    data_files: Sequence[str | Path] = (),
    markout_horizons: Sequence[int],
    charts_rendered: bool,
    artifacts: Mapping[str, str],
    commit: str | None,
    dirty: bool | None,
) -> dict[str, Any]:
    """Assemble the manifest dict that `reporting.write_review_pack` persists."""
    timestamp = (generated_at or datetime.now(UTC)).isoformat()
    return {
        "run_id": run_id,
        "run_label": run_label,
        "generated_at": timestamp,
        "git_commit": commit,
        "git_dirty": dirty,
        "python_version": python_version(),
        "data_files": [str(path) for path in data_files],
        "engine_config": serialize_engine_config(engine_config),
        "estimators_per_product": estimators_per_product(engine_config),
        "markout_horizons": list(markout_horizons),
        "charts_rendered": charts_rendered,
        "artifacts": dict(artifacts),
    }

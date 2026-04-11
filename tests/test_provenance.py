"""Unit tests for ``src.backtest.provenance``."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest import mock

import pytest

from src.backtest import provenance
from src.core.config import EngineConfig, ProductConfig


def _engine_config() -> EngineConfig:
    return EngineConfig(
        products={
            "P": ProductConfig(
                position_limit=20,
                strategy_name="market_making",
                fair_value_method="anchor",
                fair_value_fallbacks=("mid", "microprice"),
                anchor_price=100.0,
            )
        }
    )


@pytest.mark.unit
def test_git_commit_returns_none_when_git_missing() -> None:
    with mock.patch(
        "src.backtest.provenance.subprocess.run", side_effect=FileNotFoundError
    ):
        assert provenance.git_commit() is None


@pytest.mark.unit
def test_git_commit_returns_none_on_nonzero_exit() -> None:
    fake = mock.Mock(returncode=1, stdout="")
    with mock.patch("src.backtest.provenance.subprocess.run", return_value=fake):
        assert provenance.git_commit() is None


@pytest.mark.unit
def test_git_commit_returns_short_hash() -> None:
    fake = mock.Mock(returncode=0, stdout="abc1234\n")
    with mock.patch("src.backtest.provenance.subprocess.run", return_value=fake):
        assert provenance.git_commit() == "abc1234"


@pytest.mark.unit
def test_git_dirty_true_when_porcelain_nonempty() -> None:
    fake = mock.Mock(returncode=0, stdout=" M src/foo.py\n")
    with mock.patch("src.backtest.provenance.subprocess.run", return_value=fake):
        assert provenance.git_dirty() is True


@pytest.mark.unit
def test_git_dirty_false_when_porcelain_empty() -> None:
    fake = mock.Mock(returncode=0, stdout="")
    with mock.patch("src.backtest.provenance.subprocess.run", return_value=fake):
        assert provenance.git_dirty() is False


@pytest.mark.unit
def test_git_dirty_returns_none_on_failure() -> None:
    with mock.patch(
        "src.backtest.provenance.subprocess.run", side_effect=OSError
    ):
        assert provenance.git_dirty() is None


@pytest.mark.unit
def test_serialize_engine_config_roundtrips_all_fields() -> None:
    config = _engine_config()
    payload = provenance.serialize_engine_config(config)
    assert payload is not None
    assert payload["state_version"] == config.state_version
    assert payload["max_trader_data_chars"] == config.max_trader_data_chars
    product_payload = payload["products"]["P"]
    assert product_payload["position_limit"] == 20
    assert product_payload["fair_value_method"] == "anchor"
    assert product_payload["fair_value_fallbacks"] == ("mid", "microprice")


@pytest.mark.unit
def test_estimators_per_product_captures_primary_and_fallbacks() -> None:
    per_product = provenance.estimators_per_product(_engine_config())
    assert per_product is not None
    entry = per_product["P"]
    assert entry["primary"] == "anchor"
    assert entry["primary_known"] is True
    assert entry["fallbacks"] == ["mid", "microprice"]


@pytest.mark.unit
def test_build_manifest_shape() -> None:
    generated_at = datetime(2026, 4, 11, 18, 0, tzinfo=UTC)
    manifest = provenance.build_manifest(
        run_id="20260411T180000Z_phase_4a_smoke",
        run_label="phase_4a_smoke",
        generated_at=generated_at,
        engine_config=_engine_config(),
        data_files=["data/raw/tutorial_round_1/prices_round_0_day_-1.csv"],
        markout_horizons=(1, 5, 20),
        charts_rendered=True,
        artifacts={
            "summary_json": "summary.json",
            "summary_text": "summary.txt",
            "trades_json": "trades.json",
            "series_json": "series.json",
            "charts_dir": "charts",
            "notes_md": "notes.md",
        },
        commit="abc1234",
        dirty=False,
    )

    assert manifest["run_id"] == "20260411T180000Z_phase_4a_smoke"
    assert manifest["run_label"] == "phase_4a_smoke"
    assert manifest["generated_at"].startswith("2026-04-11T18:00:00")
    assert manifest["git_commit"] == "abc1234"
    assert manifest["git_dirty"] is False
    assert manifest["markout_horizons"] == [1, 5, 20]
    assert manifest["charts_rendered"] is True
    assert manifest["data_files"] == ["data/raw/tutorial_round_1/prices_round_0_day_-1.csv"]
    assert manifest["estimators_per_product"]["P"]["primary"] == "anchor"
    assert manifest["engine_config"]["products"]["P"]["anchor_price"] == 100.0
    assert manifest["artifacts"]["charts_dir"] == "charts"


@pytest.mark.unit
def test_build_manifest_without_engine_config() -> None:
    manifest = provenance.build_manifest(
        run_id="no_config",
        run_label="",
        engine_config=None,
        data_files=(),
        markout_horizons=(1, 5, 20),
        charts_rendered=False,
        artifacts={},
        commit=None,
        dirty=None,
    )
    assert manifest["engine_config"] is None
    assert manifest["estimators_per_product"] is None
    assert manifest["git_commit"] is None
    assert manifest["git_dirty"] is None

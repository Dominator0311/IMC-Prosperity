"""Unit tests for ``src.core.config``.

Config validation happens at construction time so bad runs fail before
we ever reach the live loop.
"""

from __future__ import annotations

import pytest

from src.core.config import EngineConfig, ProductConfig, default_engine_config


@pytest.mark.unit
def test_default_engine_config_contains_emeralds_and_tomatoes() -> None:
    config = default_engine_config()
    assert "EMERALDS" in config.products
    assert "TOMATOES" in config.products
    assert config.products["EMERALDS"].fair_value_method == "anchor"
    assert config.products["EMERALDS"].anchor_price == 10_000.0
    assert config.products["TOMATOES"].fair_value_method == "weighted_mid"
    assert config.products["TOMATOES"].fair_value_fallbacks == ("mid", "microprice")
    assert config.products["TOMATOES"].maker_edge == 1.0
    assert config.products["TOMATOES"].taker_edge == 1.0
    assert config.products["TOMATOES"].inventory_skew == 3.0


@pytest.mark.unit
def test_product_config_lookup_returns_none_for_unknown_product() -> None:
    config = default_engine_config()
    assert config.product_config("EMERALDS") is config.products["EMERALDS"]
    assert config.product_config("PEARLS") is None


@pytest.mark.unit
def test_anchor_method_requires_anchor_price() -> None:
    with pytest.raises(ValueError, match="anchor_price"):
        ProductConfig(
            position_limit=20,
            strategy_name="market_making",
            fair_value_method="anchor",
            anchor_price=None,
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "kwargs",
    [
        {"position_limit": 0},
        {"position_limit": -1},
        {"tick_size": 0},
        {"quote_size": -1},
        {"max_aggressive_size": -1},
        {"taker_edge": -0.1},
        {"maker_edge": -0.1},
        {"inventory_skew": -0.5},
        {"flatten_threshold": 1.5},
        {"flatten_threshold": -0.1},
        {"history_length": -1},
    ],
)
def test_product_config_rejects_invalid_args(kwargs: dict[str, object]) -> None:
    base = dict(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="mid",
        anchor_price=None,
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        ProductConfig(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_engine_config_validates_state_version_and_budget() -> None:
    with pytest.raises(ValueError):
        EngineConfig(state_version=0)
    with pytest.raises(ValueError):
        EngineConfig(max_trader_data_chars=0)

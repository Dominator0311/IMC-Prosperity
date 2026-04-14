"""Unit tests for ``src.core.config``.

Config validation happens at construction time so bad runs fail before
we ever reach the live loop.
"""

from __future__ import annotations

import pytest

from src.core.config import (
    KNOWN_ESTIMATOR_NAMES,
    KNOWN_STRATEGY_NAMES,
    ROUND1_PRODUCTS,
    EngineConfig,
    ProductConfig,
    default_engine_config,
    round1_alt_engine_config,
    round1_baseline_engine_config,
    round1_engine_config,
    round1_promoted_engine_config,
)
from src.core.fair_value import ESTIMATORS
from src.strategies import STRATEGY_REGISTRY


@pytest.mark.unit
def test_default_engine_config_contains_emeralds_and_tomatoes() -> None:
    config = default_engine_config()
    assert "EMERALDS" in config.products
    assert "TOMATOES" in config.products
    assert config.products["EMERALDS"].fair_value_method == "anchor"
    assert config.products["EMERALDS"].anchor_price == 10_000.0
    assert config.products["TOMATOES"].fair_value_method == "wall_mid"
    assert config.products["TOMATOES"].fair_value_fallbacks == ("mid", "microprice")
    assert config.products["TOMATOES"].maker_edge == 1.0
    assert config.products["TOMATOES"].taker_edge == 1.0
    assert config.products["TOMATOES"].inventory_skew == 12.0


@pytest.mark.unit
def test_product_config_lookup_returns_none_for_unknown_product() -> None:
    config = default_engine_config()
    assert config.product_config("EMERALDS") is config.products["EMERALDS"]
    assert config.product_config("PEARLS") is None


@pytest.mark.unit
def test_known_validation_names_match_live_registries() -> None:
    assert tuple(sorted(STRATEGY_REGISTRY)) == KNOWN_STRATEGY_NAMES
    assert tuple(sorted(ESTIMATORS)) == KNOWN_ESTIMATOR_NAMES


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
def test_anchor_fallback_requires_anchor_price() -> None:
    with pytest.raises(ValueError, match="anchor_price"):
        ProductConfig(
            position_limit=20,
            strategy_name="market_making",
            fair_value_method="mid",
            fair_value_fallbacks=("anchor",),
            anchor_price=None,
        )


@pytest.mark.unit
def test_product_config_rejects_unknown_strategy_name() -> None:
    with pytest.raises(ValueError, match="strategy_name"):
        ProductConfig(
            position_limit=20,
            strategy_name="does_not_exist",
            fair_value_method="mid",
        )


@pytest.mark.unit
def test_product_config_rejects_unknown_primary_estimator() -> None:
    with pytest.raises(ValueError, match="fair_value_method"):
        ProductConfig(
            position_limit=20,
            strategy_name="market_making",
            fair_value_method="not_real",
        )


@pytest.mark.unit
def test_product_config_rejects_unknown_fallback_estimator() -> None:
    with pytest.raises(ValueError, match="fair_value_fallbacks"):
        ProductConfig(
            position_limit=20,
            strategy_name="market_making",
            fair_value_method="mid",
            fair_value_fallbacks=("microprice", "not_real"),
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
@pytest.mark.parametrize("alpha", [0.0, -0.1, 1.01, 2.0, -1.0])
def test_product_config_rejects_invalid_ewma_alpha(alpha: float) -> None:
    with pytest.raises(ValueError, match="ewma_alpha"):
        ProductConfig(
            position_limit=20,
            strategy_name="market_making",
            fair_value_method="ewma_mid",
            anchor_price=None,
            ewma_alpha=alpha,
        )


@pytest.mark.unit
def test_product_config_accepts_ewma_alpha_none() -> None:
    config = ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="ewma_mid",
        anchor_price=None,
        ewma_alpha=None,
    )
    assert config.ewma_alpha is None


@pytest.mark.unit
@pytest.mark.parametrize("alpha", [0.01, 0.3, 0.5, 0.99, 1.0])
def test_product_config_accepts_ewma_alpha_inside_interval(alpha: float) -> None:
    config = ProductConfig(
        position_limit=20,
        strategy_name="market_making",
        fair_value_method="ewma_mid",
        anchor_price=None,
        ewma_alpha=alpha,
    )
    assert config.ewma_alpha == alpha


@pytest.mark.unit
def test_engine_config_validates_state_version_and_budget() -> None:
    with pytest.raises(ValueError):
        EngineConfig(state_version=0)
    with pytest.raises(ValueError):
        EngineConfig(max_trader_data_chars=0)


@pytest.mark.unit
def test_round1_engine_config_contains_only_round1_products() -> None:
    config = round1_engine_config()
    assert set(config.products) == set(ROUND1_PRODUCTS)
    # Tutorial products should be absent.
    assert "EMERALDS" not in config.products
    assert "TOMATOES" not in config.products


@pytest.mark.unit
def test_round1_baseline_is_the_round1_default() -> None:
    baseline = round1_baseline_engine_config()
    reference = round1_engine_config()
    # Baseline must equal the round-1 default verbatim: this is the
    # Phase-3 MVB reference point.
    for product in ROUND1_PRODUCTS:
        assert baseline.product_config(product) == reference.product_config(product)


@pytest.mark.unit
def test_round1_promoted_uses_phase5_parameters() -> None:
    """C-ASH-A (ewma_mid, t=0.25) + C-PEP-A (linear_drift, t=2.0, flat=0.7)."""
    promoted = round1_promoted_engine_config()
    ash = promoted.product_config("ASH_COATED_OSMIUM")
    pepper = promoted.product_config("INTARIAN_PEPPER_ROOT")
    assert ash is not None and pepper is not None
    assert ash.fair_value_method == "ewma_mid"
    assert ash.taker_edge == 0.25
    assert ash.maker_edge == 1.0
    assert pepper.fair_value_method == "linear_drift"
    assert pepper.taker_edge == 2.0
    assert pepper.inventory_skew == 2.0
    assert pepper.flatten_threshold == 0.7
    assert pepper.history_length == 32


@pytest.mark.unit
def test_round1_alt_uses_phase5_higher_upside_parameters() -> None:
    """C-ASH-B (wall_mid, t=0.5) + C-PEP-B (linear_drift, skew=1.0, flat=0.9)."""
    alt = round1_alt_engine_config()
    ash = alt.product_config("ASH_COATED_OSMIUM")
    pepper = alt.product_config("INTARIAN_PEPPER_ROOT")
    assert ash is not None and pepper is not None
    assert ash.fair_value_method == "wall_mid"
    assert ash.taker_edge == 0.5
    assert ash.maker_edge == 1.5
    assert pepper.fair_value_method == "linear_drift"
    assert pepper.inventory_skew == 1.0
    assert pepper.flatten_threshold == 0.9
    assert pepper.history_length == 32


@pytest.mark.unit
def test_round1_variants_only_contain_round1_products() -> None:
    """All three Phase-6 variants must contain exactly the round-1 products."""
    for variant in (
        round1_baseline_engine_config(),
        round1_promoted_engine_config(),
        round1_alt_engine_config(),
    ):
        assert set(variant.products) == set(ROUND1_PRODUCTS)

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
    round1_f5_engine_config,
    round1_h1_engine_config,
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
    """All Phase-6 / Phase-8.5 / Phase-9 variants contain only round-1 products."""
    for variant in (
        round1_baseline_engine_config(),
        round1_promoted_engine_config(),
        round1_alt_engine_config(),
        round1_h1_engine_config(),
        round1_f5_engine_config(),
    ):
        assert set(variant.products) == set(ROUND1_PRODUCTS)


@pytest.mark.unit
def test_round1_f5_uses_asymmetric_taker_edges_on_pepper() -> None:
    """Phase-9 F5 candidate: wall-based ASH + asymmetric-taker PEPPER.

    ASH leg must match the H1 / Alt wall-based leg byte-for-byte so
    the two shipped bundles continue to serve as references for the
    ASH side. PEPPER leg must be identical to the shipped Promoted
    leg on every knob EXCEPT the per-side taker edges.
    """
    f5 = round1_f5_engine_config()
    h1 = round1_h1_engine_config()
    promoted = round1_promoted_engine_config()

    ash_f5 = f5.product_config("ASH_COATED_OSMIUM")
    ash_h1 = h1.product_config("ASH_COATED_OSMIUM")
    assert ash_f5 is not None and ash_h1 is not None
    assert ash_f5 == ash_h1  # ASH leg is shared with H1

    pepper_f5 = f5.product_config("INTARIAN_PEPPER_ROOT")
    pepper_promoted = promoted.product_config("INTARIAN_PEPPER_ROOT")
    assert pepper_f5 is not None and pepper_promoted is not None

    # Exactly the two per-side taker knobs are new; everything else
    # must equal the shipped Promoted PEPPER.
    assert pepper_f5.taker_edge_buy == 1.5
    assert pepper_f5.taker_edge_sell == 3.0
    assert pepper_f5.taker_edge == pepper_promoted.taker_edge == 2.0
    assert pepper_f5.fair_value_method == pepper_promoted.fair_value_method
    assert pepper_f5.fair_value_fallbacks == pepper_promoted.fair_value_fallbacks
    assert pepper_f5.maker_edge == pepper_promoted.maker_edge
    assert pepper_f5.inventory_skew == pepper_promoted.inventory_skew
    assert pepper_f5.flatten_threshold == pepper_promoted.flatten_threshold
    assert pepper_f5.history_length == pepper_promoted.history_length

    # All early-window / short-cap knobs stay at neutral defaults so
    # F5 is a pure full-day taker-asymmetry candidate.
    assert pepper_f5.early_window == 0
    assert pepper_f5.early_taker_edge_buy is None
    assert pepper_f5.early_taker_edge_sell is None
    assert pepper_f5.early_short_cap is None
    assert pepper_f5.early_short_skew_mult == 1.0
    assert pepper_f5.early_short_flatten is None


@pytest.mark.unit
def test_round1_f5_does_not_mutate_promoted_or_h1() -> None:
    """Building F5 must not perturb the shipped Promoted / H1 configs."""
    promoted_before = round1_promoted_engine_config()
    h1_before = round1_h1_engine_config()
    _ = round1_f5_engine_config()
    promoted_after = round1_promoted_engine_config()
    h1_after = round1_h1_engine_config()
    assert promoted_before.products == promoted_after.products
    assert h1_before.products == h1_after.products


@pytest.mark.unit
def test_round1_f5_variant_is_registered_in_exporter() -> None:
    """The Phase-9 F5 variant must be reachable through the exporter registry."""
    from src.scripts.round_1.export_round1_submission import VARIANTS

    assert "f5" in VARIANTS
    entry = VARIANTS["f5"]
    assert entry["factory_name"] == "round1_f5_engine_config"
    assert entry["factory"] is round1_f5_engine_config
    # Exporter must advertise the variant as additive, not a replacement.
    assert "additive" not in entry["label"].lower()  # label is short; purpose covers rationale
    assert isinstance(entry["purpose"], str) and entry["purpose"]


# ---- Phase-9 fastsearch knob validation ----


def _base_kwargs() -> dict:
    return {
        "position_limit": 20,
        "strategy_name": "market_making",
        "fair_value_method": "mid",
    }


@pytest.mark.unit
def test_product_config_phase9_defaults_are_neutral() -> None:
    """New Phase-9 knobs default to neutral no-op values."""
    config = ProductConfig(**_base_kwargs())
    assert config.taker_edge_buy is None
    assert config.taker_edge_sell is None
    assert config.early_window == 0
    assert config.early_taker_edge_buy is None
    assert config.early_taker_edge_sell is None
    assert config.early_short_cap is None
    assert config.early_short_skew_mult == 1.0
    assert config.early_short_flatten is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "field,value",
    [
        ("taker_edge_buy", -0.1),
        ("taker_edge_sell", -0.1),
        ("early_window", -1),
        ("early_taker_edge_buy", -0.1),
        ("early_taker_edge_sell", -0.1),
        ("early_short_skew_mult", -1.0),
    ],
)
def test_product_config_rejects_negative_phase9_knobs(field: str, value: float) -> None:
    with pytest.raises(ValueError):
        ProductConfig(**{**_base_kwargs(), field: value})


@pytest.mark.unit
@pytest.mark.parametrize("value", [-0.01, 1.01, 2.0])
def test_product_config_rejects_out_of_range_early_short_flatten(value: float) -> None:
    with pytest.raises(ValueError, match="early_short_flatten"):
        ProductConfig(**{**_base_kwargs(), "early_short_flatten": value})


@pytest.mark.unit
def test_product_config_rejects_positive_early_short_cap() -> None:
    """``early_short_cap`` is a floor on net short; must be <= 0."""
    with pytest.raises(ValueError, match="early_short_cap"):
        ProductConfig(**{**_base_kwargs(), "early_short_cap": 5})


@pytest.mark.unit
def test_product_config_accepts_phase9_knob_set() -> None:
    """A representative Family-1/2/4/5 combo constructs without error."""
    config = ProductConfig(
        **_base_kwargs(),
        taker_edge_buy=1.0,
        taker_edge_sell=2.5,
        early_window=25_000,
        early_taker_edge_buy=0.5,
        early_taker_edge_sell=3.0,
        early_short_cap=-8,
        early_short_skew_mult=2.0,
        early_short_flatten=0.6,
    )
    assert config.early_window == 25_000
    assert config.early_short_cap == -8

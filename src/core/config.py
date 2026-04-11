from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProductConfig:
    position_limit: int
    strategy_name: str
    fair_value_method: str
    tick_size: int = 1
    anchor_price: float | None = None
    taker_edge: float = 1.0
    maker_edge: float = 1.0
    quote_size: int = 5
    max_aggressive_size: int = 10
    inventory_skew: float = 2.0
    flatten_threshold: float = 0.8
    history_length: int = 32


@dataclass(frozen=True)
class EngineConfig:
    state_version: int = 1
    max_trader_data_chars: int = 50_000
    diagnostics_verbosity: int = 1
    products: dict[str, ProductConfig] = field(default_factory=dict)


def default_engine_config() -> EngineConfig:
    return EngineConfig(
        products={
            "EMERALDS": ProductConfig(
                position_limit=20,
                strategy_name="stable_anchor",
                fair_value_method="anchor",
                anchor_price=10_000.0,
                taker_edge=1.0,
                maker_edge=2.0,
                quote_size=5,
                max_aggressive_size=10,
                inventory_skew=2.0,
                flatten_threshold=0.75,
                history_length=32,
            ),
            "TOMATOES": ProductConfig(
                position_limit=20,
                strategy_name="adaptive_quote",
                fair_value_method="weighted_mid",
                taker_edge=1.0,
                maker_edge=2.0,
                quote_size=4,
                max_aggressive_size=8,
                inventory_skew=2.5,
                flatten_threshold=0.7,
                history_length=48,
            ),
        }
    )


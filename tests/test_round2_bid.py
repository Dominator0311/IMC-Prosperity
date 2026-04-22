"""Round-2 Market Access Fee plumbing — config + Trader.bid().

Covers:

- ``EngineConfig.bid_value`` defaults and validation.
- ``with_bid_value`` returns a new EngineConfig with the bid overridden
  while preserving every other field (frozen dataclass replace).
- ``Trader.bid()`` reads from ``self.config.bid_value`` rather than a
  hardcoded constant.
- All shipped Round-1 factories default ``bid_value`` to 0 (the
  abstain-from-auction safe value).
"""

from __future__ import annotations

import pytest

from src.core.config import (
    EngineConfig,
    default_engine_config,
    round1_alt_engine_config,
    round1_baseline_engine_config,
    round1_f5_engine_config,
    round1_h1_engine_config,
    round1_promoted_engine_config,
    with_bid_value,
)
from src.trader import Trader


@pytest.mark.unit
def test_engine_config_default_bid_is_zero() -> None:
    config = EngineConfig()
    assert config.bid_value == 0


@pytest.mark.unit
def test_engine_config_accepts_positive_bid() -> None:
    config = EngineConfig(bid_value=1500)
    assert config.bid_value == 1500


@pytest.mark.unit
def test_engine_config_rejects_negative_bid() -> None:
    with pytest.raises(ValueError, match="bid_value must be >= 0"):
        EngineConfig(bid_value=-1)


@pytest.mark.unit
def test_engine_config_rejects_non_int_bid() -> None:
    with pytest.raises(TypeError, match="bid_value must be int"):
        EngineConfig(bid_value=1500.0)  # type: ignore[arg-type]


@pytest.mark.unit
def test_engine_config_rejects_bool_bid() -> None:
    # bool is a subclass of int in Python; we explicitly exclude it
    # because ``True`` would silently bid 1.
    with pytest.raises(TypeError, match="bid_value must be int"):
        EngineConfig(bid_value=True)  # type: ignore[arg-type]


@pytest.mark.unit
def test_with_bid_value_overrides_only_bid() -> None:
    base = default_engine_config()
    out = with_bid_value(base, 750)
    assert out.bid_value == 750
    assert base.bid_value == 0  # original untouched (frozen dataclass)
    assert out.products is base.products
    assert out.state_version == base.state_version
    assert out.max_trader_data_chars == base.max_trader_data_chars
    assert out.scanner_config == base.scanner_config
    assert out.residual_config == base.residual_config


@pytest.mark.unit
def test_with_bid_value_validates() -> None:
    with pytest.raises(ValueError, match="bid_value must be >= 0"):
        with_bid_value(default_engine_config(), -100)


@pytest.mark.unit
def test_trader_bid_reads_from_config_default() -> None:
    trader = Trader()
    assert trader.bid() == 0


@pytest.mark.unit
def test_trader_bid_reads_from_config_override() -> None:
    config = with_bid_value(default_engine_config(), 1200)
    trader = Trader(config=config)
    assert trader.bid() == 1200


@pytest.mark.unit
@pytest.mark.parametrize(
    "factory",
    [
        round1_baseline_engine_config,
        round1_promoted_engine_config,
        round1_alt_engine_config,
        round1_h1_engine_config,
        round1_f5_engine_config,
    ],
)
def test_round1_factories_default_to_zero_bid(factory) -> None:
    """Round-1 bundles must not accidentally bid in Round-2 auction.

    The MAF auction is Round-2 only; a non-zero default would be a
    real-money silent auto-bid if any Round-1 bundle were re-uploaded.
    """
    config = factory()
    assert config.bid_value == 0

"""Strategy registry.

Product configs reference a strategy by name (``ProductConfig.strategy_name``)
and the ``Trader`` looks up that name in ``STRATEGY_REGISTRY`` to
construct the strategy instance.

Adding a new strategy means:

1. implement a subclass of ``BaseStrategy`` in a new module,
2. register it here under a unique name,
3. set ``ProductConfig.strategy_name`` on the products that should use
   it.

No changes to ``Trader.__init__`` are needed for new products that
reuse an existing strategy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType

from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.strategies.base import BaseStrategy
from src.strategies.market_making import MarketMakingStrategy

StrategyFactory = Callable[[FairValueEngine, SignalEngine], BaseStrategy]

STRATEGY_REGISTRY: Mapping[str, StrategyFactory] = MappingProxyType(
    {
        "market_making": MarketMakingStrategy,
    }
)

__all__ = [
    "STRATEGY_REGISTRY",
    "BaseStrategy",
    "MarketMakingStrategy",
    "StrategyFactory",
]

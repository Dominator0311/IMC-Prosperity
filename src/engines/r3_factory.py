"""R3 submission entry-point factory.

This module is the LAST module in the R3 bundle. It re-defines ``Trader``
so the Prosperity container (which calls ``Trader()`` with no args) gets a
fully-wired R3 Trader: EngineOrchestrator with R3Engine registered.

Bundle mechanics: the src-import of Trader is stripped; ``_BaseTrader = Trader``
resolves to the class already in the bundle's flat namespace (from trader.py).
In local dev the import runs normally before the alias executes.
"""

from __future__ import annotations

from src.core.config_core import EngineConfig
from src.core.primitives.engine_orchestrator import EngineOrchestrator
from src.engines.r3_engine import R3Engine
from src.trader import Trader  # stripped in bundle; in dev populates ``Trader``

_BaseTrader = Trader  # in dev: imported above; in bundle: already in flat ns

_R3_CONFIG = EngineConfig(
    products={},
    state_version=1,
    max_trader_data_chars=50_000,
)


class Trader(_BaseTrader):
    """R3 submission Trader. Zero-arg constructor for Prosperity platform."""

    def __init__(self) -> None:
        super().__init__(
            config=_R3_CONFIG,
            orchestrator=EngineOrchestrator([R3Engine()]),
        )

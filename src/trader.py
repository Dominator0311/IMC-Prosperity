"""Entrypoint for the Prosperity live trading container.

Responsibilities of this file are deliberately narrow:

1. Restore persistent state from ``state.traderData``.
2. Normalize the incoming ``TradingState`` into canonical snapshots.
3. Dispatch each known product to its configured strategy.
4. Route the strategy's intent through execution and risk layers.
5. Update rolling per-product memory.
6. Serialize next-iteration state back into ``traderData``.
7. Return ``(orders, conversions, traderData)``.

This file must never contain product-specific pricing or execution
heuristics. Those live in ``strategies/`` and ``core/``.
"""

from __future__ import annotations

from src.core.config import EngineConfig, ProductConfig, default_engine_config
from src.core.execution import ExecutionEngine
from src.core.fair_value import FairValueEngine
from src.core.logger import DecisionLogger
from src.core.market_data import MarketDataAdapter
from src.core.risk import RiskManager
from src.core.signals import SignalEngine
from src.core.state_store import StateStore
from src.core.types import EngineState, NormalizedSnapshot, ProductMemory
from src.core.utils import bounded_append
from src.datamodel import Order, TradingState
from src.strategies.adaptive_quote import AdaptiveQuoteStrategy
from src.strategies.base import BaseStrategy, StrategyContext
from src.strategies.stable_anchor import StableAnchorStrategy


class Trader:
    def __init__(self, config: EngineConfig | None = None) -> None:
        self.config = config or default_engine_config()
        self.state_store = StateStore(
            version=self.config.state_version,
            max_chars=self.config.max_trader_data_chars,
        )
        self.market_data = MarketDataAdapter()
        self.fair_value_engine = FairValueEngine()
        self.signal_engine = SignalEngine()
        self.execution_engine = ExecutionEngine()
        self.risk_manager = RiskManager()
        self.logger = DecisionLogger()

        self.strategies: dict[str, BaseStrategy] = {
            "stable_anchor": StableAnchorStrategy(self.fair_value_engine, self.signal_engine),
            "adaptive_quote": AdaptiveQuoteStrategy(self.fair_value_engine, self.signal_engine),
        }

    # Some Prosperity rounds require a ``bid()`` method on Trader.
    # Keep this stub so contract changes do not break submissions.
    def bid(self) -> int:
        return 15

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        engine_state = self.state_store.load(state.traderData)
        engine_state.version = self.config.state_version

        snapshots = self.market_data.normalize_state(state)
        results: dict[str, list[Order]] = {}

        for product, snapshot in snapshots.items():
            product_config = self.config.product_config(product)
            if product_config is None:
                # Unknown product -> no orders, no state side effects.
                results[product] = []
                continue

            strategy = self.strategies.get(product_config.strategy_name)
            if strategy is None:
                results[product] = []
                continue

            memory = engine_state.for_product(product)
            legal_orders = self._step_product(
                product=product,
                snapshot=snapshot,
                memory=memory,
                product_config=product_config,
                strategy=strategy,
                timestamp=state.timestamp,
            )
            results[product] = legal_orders
            self._update_memory(memory, snapshot, product_config.history_length)

        trader_data = self.state_store.save(engine_state)
        conversions = 0
        return results, conversions, trader_data

    # ---------------------------------------------------------- per-product

    def _step_product(
        self,
        *,
        product: str,
        snapshot: NormalizedSnapshot,
        memory: ProductMemory,
        product_config: ProductConfig,
        strategy: BaseStrategy,
        timestamp: int,
    ) -> list[Order]:
        context = StrategyContext(
            product=product,
            snapshot=snapshot,
            memory=memory,
            config=product_config,
        )
        intent = strategy.generate_intent(context)
        raw_orders = self.execution_engine.generate_orders(snapshot, intent, product_config)
        legal_orders = self.risk_manager.clip_orders(
            product=product,
            orders=raw_orders,
            current_position=snapshot.position,
            limit=product_config.position_limit,
        )

        self.logger.record(
            {
                "timestamp": timestamp,
                "product": product,
                "fair_value": round(intent.fair_value.price, 4),
                "method": intent.fair_value.method,
                "position": snapshot.position,
                "mode": intent.mode,
                "orders": [(order.price, order.quantity) for order in legal_orders],
            }
        )
        return legal_orders

    @staticmethod
    def _update_memory(
        memory: ProductMemory, snapshot: NormalizedSnapshot, history_length: int
    ) -> None:
        if history_length <= 0:
            return
        if snapshot.mid is not None:
            bounded_append(memory.recent_mids, float(snapshot.mid), history_length)
        if snapshot.spread is not None:
            bounded_append(memory.recent_spreads, float(snapshot.spread), history_length)

    # ------------------------------------------------------------- helpers

    def reset(self) -> None:
        """Drop any transient in-memory state (diagnostics only).

        The live runtime never persists class members between iterations,
        but offline replay reuses one ``Trader`` instance across many
        ``run()`` calls. This helper keeps replay deterministic by
        letting callers clear the local ``DecisionLogger``.
        """
        self.logger = DecisionLogger()

    def engine_state_from(self, trader_data: str | None) -> EngineState:
        """Expose the state store to callers that need to inspect memory."""
        return self.state_store.load(trader_data)

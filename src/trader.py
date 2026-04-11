from __future__ import annotations

from src.core.config import default_engine_config
from src.core.execution import ExecutionEngine
from src.core.logger import DecisionLogger
from src.core.market_data import MarketDataAdapter
from src.core.risk import RiskManager
from src.core.state_store import StateStore
from src.core.utils import bounded_append
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.datamodel import Order, TradingState
from src.strategies.adaptive_quote import AdaptiveQuoteStrategy
from src.strategies.base import StrategyContext
from src.strategies.stable_anchor import StableAnchorStrategy


class Trader:
    def __init__(self) -> None:
        self.config = default_engine_config()
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
        self.strategies = {
            "stable_anchor": StableAnchorStrategy(
                self.fair_value_engine, self.signal_engine
            ),
            "adaptive_quote": AdaptiveQuoteStrategy(
                self.fair_value_engine, self.signal_engine
            ),
        }

    def bid(self) -> int:
        return 15

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        engine_state = self.state_store.load(state.traderData)
        snapshots = self.market_data.normalize_state(state)
        results: dict[str, list[Order]] = {}

        for product, snapshot in snapshots.items():
            product_config = self.config.products.get(product)
            if product_config is None:
                results[product] = []
                continue

            memory = engine_state.for_product(product)
            strategy = self.strategies[product_config.strategy_name]
            context = StrategyContext(
                product=product,
                snapshot=snapshot,
                memory=memory,
                config=product_config,
            )
            intent = strategy.generate_intent(context)
            orders = self.execution_engine.generate_orders(snapshot, intent, product_config)
            legal_orders = self.risk_manager.clip_orders(
                product=product,
                orders=orders,
                current_position=snapshot.position,
                limit=product_config.position_limit,
            )
            results[product] = legal_orders

            self._update_memory(memory, snapshot, product_config.history_length)
            self.logger.record(
                {
                    "timestamp": state.timestamp,
                    "product": product,
                    "fair_value": round(intent.fair_value.price, 4),
                    "method": intent.fair_value.method,
                    "position": snapshot.position,
                    "mode": intent.mode,
                    "orders": [(order.price, order.quantity) for order in legal_orders],
                }
            )

        trader_data = self.state_store.save(engine_state)
        conversions = 0
        return results, conversions, trader_data

    @staticmethod
    def _update_memory(memory, snapshot, history_length: int) -> None:
        if snapshot.mid is not None:
            bounded_append(memory.recent_mids, float(snapshot.mid), history_length)
        if snapshot.spread is not None:
            bounded_append(memory.recent_spreads, float(snapshot.spread), history_length)

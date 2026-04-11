"""Raw ``TradingState`` -> canonical ``NormalizedSnapshot`` adapter.

Everything downstream of this module consumes ``NormalizedSnapshot``s, so
this is the only place that has to know how Prosperity lays out raw
order-book and trade data.

Conventions enforced here:

- Bids are sorted price-descending; asks are sorted price-ascending.
  Strategies can then rely on ``bids[0]`` being the best bid.
- Ask volumes are always returned as *positive* integers, regardless of
  whether the raw ``sell_orders`` dict uses Prosperity's negative-volume
  convention or an already-positive mirror. Zero-volume levels are
  dropped.
- Trade lists combine own and market trades and are sorted by timestamp,
  with a ``source`` tag preserved so diagnostics can distinguish them.

This module produces no orders and holds no state.
"""

from __future__ import annotations

from src.core.types import BookLevel, NormalizedSnapshot, TradePrint
from src.datamodel import OrderDepth, Trade, TradingState


class MarketDataAdapter:
    def normalize_state(self, state: TradingState) -> dict[str, NormalizedSnapshot]:
        snapshots: dict[str, NormalizedSnapshot] = {}
        for product, order_depth in state.order_depths.items():
            bids, asks = self._normalize_depth(order_depth)
            trades = self._normalize_trades(
                state.own_trades.get(product, []) if state.own_trades else [],
                state.market_trades.get(product, []) if state.market_trades else [],
            )
            snapshots[product] = NormalizedSnapshot(
                product=product,
                timestamp=state.timestamp,
                bids=bids,
                asks=asks,
                position=state.position.get(product, 0) if state.position else 0,
                trades=trades,
            )
        return snapshots

    @staticmethod
    def _normalize_depth(
        order_depth: OrderDepth,
    ) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        buys = getattr(order_depth, "buy_orders", {}) or {}
        sells = getattr(order_depth, "sell_orders", {}) or {}

        bids = tuple(
            BookLevel(price=int(price), volume=int(volume))
            for price, volume in sorted(buys.items(), key=lambda item: item[0], reverse=True)
            if int(volume) > 0
        )
        # Prosperity convention: sell_orders use negative volume.
        # We accept either convention and always return positive volumes.
        asks = tuple(
            BookLevel(price=int(price), volume=abs(int(volume)))
            for price, volume in sorted(sells.items(), key=lambda item: item[0])
            if int(volume) != 0
        )
        return bids, asks

    @staticmethod
    def _normalize_trades(
        own_trades: list[Trade], market_trades: list[Trade]
    ) -> tuple[TradePrint, ...]:
        combined: list[TradePrint] = []
        combined.extend(
            TradePrint(
                price=int(trade.price),
                quantity=int(trade.quantity),
                buyer=trade.buyer,
                seller=trade.seller,
                timestamp=int(trade.timestamp),
                source="own",
            )
            for trade in own_trades or []
        )
        combined.extend(
            TradePrint(
                price=int(trade.price),
                quantity=int(trade.quantity),
                buyer=trade.buyer,
                seller=trade.seller,
                timestamp=int(trade.timestamp),
                source="market",
            )
            for trade in market_trades or []
        )
        combined.sort(key=lambda trade: trade.timestamp)
        return tuple(combined)

from __future__ import annotations

from src.core.types import BookLevel, NormalizedSnapshot, TradePrint
from src.datamodel import OrderDepth, Trade, TradingState


class MarketDataAdapter:
    def normalize_state(self, state: TradingState) -> dict[str, NormalizedSnapshot]:
        snapshots: dict[str, NormalizedSnapshot] = {}
        for product, order_depth in state.order_depths.items():
            bids, asks = self._normalize_depth(order_depth)
            trades = self._normalize_trades(
                state.own_trades.get(product, []),
                state.market_trades.get(product, []),
            )
            snapshots[product] = NormalizedSnapshot(
                product=product,
                timestamp=state.timestamp,
                bids=bids,
                asks=asks,
                position=state.position.get(product, 0),
                trades=trades,
            )
        return snapshots

    @staticmethod
    def _normalize_depth(
        order_depth: OrderDepth,
    ) -> tuple[tuple[BookLevel, ...], tuple[BookLevel, ...]]:
        bids = tuple(
            BookLevel(price=price, volume=volume)
            for price, volume in sorted(
                order_depth.buy_orders.items(), key=lambda item: item[0], reverse=True
            )
            if volume > 0
        )
        asks = tuple(
            BookLevel(price=price, volume=abs(volume))
            for price, volume in sorted(order_depth.sell_orders.items(), key=lambda item: item[0])
            if volume < 0
        )
        return bids, asks

    @staticmethod
    def _normalize_trades(
        own_trades: list[Trade], market_trades: list[Trade]
    ) -> tuple[TradePrint, ...]:
        trades = [
            TradePrint(
                price=trade.price,
                quantity=trade.quantity,
                buyer=trade.buyer,
                seller=trade.seller,
                timestamp=trade.timestamp,
                source="own",
            )
            for trade in own_trades
        ]
        trades.extend(
            TradePrint(
                price=trade.price,
                quantity=trade.quantity,
                buyer=trade.buyer,
                seller=trade.seller,
                timestamp=trade.timestamp,
                source="market",
            )
            for trade in market_trades
        )
        trades.sort(key=lambda trade: trade.timestamp)
        return tuple(trades)


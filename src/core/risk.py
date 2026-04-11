"""Per-product position legality and clipping.

This is the single place where we enforce Prosperity's hard position
limits. Strategies must never assume their orders are final: the risk
manager always owns the decision about what quantity actually leaves the
trader.

The clipping model:
- We compute remaining buy and sell capacity from the current position
  and the product's limit.
- We walk through the strategy's orders in submission order, reducing
  each to fit the remaining capacity on that side.
- Orders that would have zero quantity after clipping are dropped.
- Zero-quantity input orders are silently dropped.
- An order whose ``symbol`` does not match the product being clipped is
  a programming error and raises ``ValueError`` immediately.

The rationale for clipping per-side instead of per-order is that
Prosperity will reject an entire side if the aggregate would breach the
limit. By aggregating capacity here, we make the exchange reject nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.datamodel import Order


@dataclass(frozen=True)
class Capacity:
    buy: int
    sell: int


class RiskManager:
    @staticmethod
    def remaining_buy_capacity(position: int, limit: int) -> int:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        return max(0, limit - position)

    @staticmethod
    def remaining_sell_capacity(position: int, limit: int) -> int:
        if limit < 0:
            raise ValueError("limit must be >= 0")
        return max(0, limit + position)

    @classmethod
    def capacity(cls, position: int, limit: int) -> Capacity:
        return Capacity(
            buy=cls.remaining_buy_capacity(position, limit),
            sell=cls.remaining_sell_capacity(position, limit),
        )

    @staticmethod
    def inventory_ratio(position: int, limit: int) -> float:
        if limit <= 0:
            return 0.0
        return position / limit

    def clip_orders(
        self,
        product: str,
        orders: list[Order],
        current_position: int,
        limit: int,
    ) -> list[Order]:
        if limit < 0:
            raise ValueError("limit must be >= 0")

        buy_capacity = self.remaining_buy_capacity(current_position, limit)
        sell_capacity = self.remaining_sell_capacity(current_position, limit)
        clipped: list[Order] = []

        for order in orders:
            if order.symbol != product:
                raise ValueError(
                    f"risk.clip_orders: order symbol {order.symbol!r} does not "
                    f"match product {product!r}"
                )
            if order.quantity == 0:
                continue

            if order.quantity > 0:
                quantity = min(order.quantity, buy_capacity)
                if quantity > 0:
                    clipped.append(Order(order.symbol, order.price, quantity))
                    buy_capacity -= quantity
            else:
                quantity = min(-order.quantity, sell_capacity)
                if quantity > 0:
                    clipped.append(Order(order.symbol, order.price, -quantity))
                    sell_capacity -= quantity

        return clipped

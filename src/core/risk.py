from __future__ import annotations

from src.datamodel import Order


class RiskManager:
    @staticmethod
    def remaining_buy_capacity(position: int, limit: int) -> int:
        return max(0, limit - position)

    @staticmethod
    def remaining_sell_capacity(position: int, limit: int) -> int:
        return max(0, limit + position)

    @staticmethod
    def inventory_ratio(position: int, limit: int) -> float:
        if limit <= 0:
            return 0.0
        return position / limit

    def clip_orders(
        self, product: str, orders: list[Order], current_position: int, limit: int
    ) -> list[Order]:
        buy_capacity = self.remaining_buy_capacity(current_position, limit)
        sell_capacity = self.remaining_sell_capacity(current_position, limit)
        clipped: list[Order] = []

        for order in orders:
            if order.quantity > 0:
                quantity = min(order.quantity, buy_capacity)
                if quantity > 0:
                    clipped.append(Order(product, order.price, quantity))
                    buy_capacity -= quantity
            elif order.quantity < 0:
                quantity = min(-order.quantity, sell_capacity)
                if quantity > 0:
                    clipped.append(Order(product, order.price, -quantity))
                    sell_capacity -= quantity

        return clipped


from __future__ import annotations

from dataclasses import dataclass, field

from src.datamodel import Order


@dataclass
class RunMetrics:
    order_count: int = 0
    buy_order_count: int = 0
    sell_order_count: int = 0
    orders_by_product: dict[str, int] = field(default_factory=dict)

    def record_orders(self, product: str, orders: list[Order]) -> None:
        self.orders_by_product[product] = self.orders_by_product.get(product, 0) + len(orders)
        self.order_count += len(orders)
        self.buy_order_count += sum(1 for order in orders if order.quantity > 0)
        self.sell_order_count += sum(1 for order in orders if order.quantity < 0)

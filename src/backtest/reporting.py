from __future__ import annotations

from src.backtest.metrics import RunMetrics


def build_review_pack(metrics: RunMetrics) -> dict[str, object]:
    return {
        "summary": {
            "order_count": metrics.order_count,
            "buy_order_count": metrics.buy_order_count,
            "sell_order_count": metrics.sell_order_count,
        },
        "orders_by_product": dict(metrics.orders_by_product),
    }


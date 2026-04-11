from src.core.risk import RiskManager
from src.datamodel import Order


def test_risk_manager_clips_orders_to_position_limit() -> None:
    risk = RiskManager()
    orders = [
        Order("EMERALDS", 9998, 8),
        Order("EMERALDS", 9997, 7),
        Order("EMERALDS", 10002, -6),
    ]

    clipped = risk.clip_orders("EMERALDS", orders, current_position=15, limit=20)

    assert [order.quantity for order in clipped] == [5, -6]


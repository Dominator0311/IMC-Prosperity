from __future__ import annotations

from dataclasses import dataclass

from src.core.types import NormalizedSnapshot
from src.datamodel import Order


@dataclass(frozen=True)
class FillModelConfig:
    passive_fills_enabled: bool = False


class FillModel:
    def __init__(self, config: FillModelConfig | None = None) -> None:
        self.config = config or FillModelConfig()

    def marketable_fill_quantity(self, order: Order, snapshot: NormalizedSnapshot) -> int:
        if order.quantity > 0:
            filled = 0
            remaining = order.quantity
            for ask in snapshot.asks:
                if ask.price > order.price or remaining <= 0:
                    break
                quantity = min(ask.volume, remaining)
                filled += quantity
                remaining -= quantity
            return filled

        if order.quantity < 0:
            filled = 0
            remaining = -order.quantity
            for bid in snapshot.bids:
                if bid.price < order.price or remaining <= 0:
                    break
                quantity = min(bid.volume, remaining)
                filled += quantity
                remaining -= quantity
            return filled

        return 0

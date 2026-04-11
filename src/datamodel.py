from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from json import JSONEncoder
from typing import Any

Time = int
Symbol = str
Product = str
Position = int
UserId = str


@dataclass
class Listing:
    symbol: Symbol
    product: Product
    denomination: Product


@dataclass
class ConversionObservation:
    bidPrice: float
    askPrice: float
    transportFees: float
    exportTariff: float
    importTariff: float
    sunlight: float
    humidity: float


@dataclass
class Observation:
    plainValueObservations: dict[Product, int] = field(default_factory=dict)
    conversionObservations: dict[Product, ConversionObservation] = field(
        default_factory=dict
    )


@dataclass
class Order:
    symbol: Symbol
    price: int
    quantity: int


@dataclass
class OrderDepth:
    buy_orders: dict[int, int] = field(default_factory=dict)
    sell_orders: dict[int, int] = field(default_factory=dict)


@dataclass
class Trade:
    symbol: Symbol
    price: int
    quantity: int
    buyer: UserId | None = None
    seller: UserId | None = None
    timestamp: int = 0


@dataclass
class TradingState:
    traderData: str
    timestamp: Time
    listings: dict[Symbol, Listing]
    order_depths: dict[Symbol, OrderDepth]
    own_trades: dict[Symbol, list[Trade]]
    market_trades: dict[Symbol, list[Trade]]
    position: dict[Product, Position]
    observations: Observation

    def to_json(self) -> str:
        return json.dumps(self, cls=ProsperityEncoder, sort_keys=True)


class ProsperityEncoder(JSONEncoder):
    def default(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "__dict__"):
            return value.__dict__
        return super().default(value)


from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Product = str
Timestamp = int
Scalar = int | float | str | bool
ExecutionMode = Literal["idle", "maker", "taker", "recovery", "hybrid"]


@dataclass(frozen=True)
class BookLevel:
    price: int
    volume: int


@dataclass(frozen=True)
class TradePrint:
    price: int
    quantity: int
    buyer: str | None = None
    seller: str | None = None
    timestamp: int = 0
    source: Literal["own", "market"] = "market"


@dataclass(frozen=True)
class NormalizedSnapshot:
    product: Product
    timestamp: Timestamp
    bids: tuple[BookLevel, ...] = ()
    asks: tuple[BookLevel, ...] = ()
    position: int = 0
    trades: tuple[TradePrint, ...] = ()

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if not self.best_bid or not self.best_ask:
            return None
        return (self.best_bid.price + self.best_ask.price) / 2.0

    @property
    def spread(self) -> float | None:
        if not self.best_bid or not self.best_ask:
            return None
        return float(self.best_ask.price - self.best_bid.price)

    @property
    def book_imbalance(self) -> float | None:
        if not self.best_bid or not self.best_ask:
            return None
        total = self.best_bid.volume + self.best_ask.volume
        if total <= 0:
            return None
        return (self.best_bid.volume - self.best_ask.volume) / total

    @property
    def microprice(self) -> float | None:
        if not self.best_bid or not self.best_ask:
            return None
        total = self.best_bid.volume + self.best_ask.volume
        if total <= 0:
            return None
        return (
            (self.best_bid.price * self.best_ask.volume)
            + (self.best_ask.price * self.best_bid.volume)
        ) / total


@dataclass
class ProductMemory:
    recent_mids: list[float] = field(default_factory=list)
    recent_spreads: list[float] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    flags: dict[str, bool] = field(default_factory=dict)
    values: dict[str, float] = field(default_factory=dict)


@dataclass
class EngineState:
    version: int = 1
    products: dict[Product, ProductMemory] = field(default_factory=dict)

    def for_product(self, product: Product) -> ProductMemory:
        if product not in self.products:
            self.products[product] = ProductMemory()
        return self.products[product]


@dataclass(frozen=True)
class FairValueEstimate:
    price: float
    method: str
    confidence: float | None = None
    components: dict[str, Scalar] = field(default_factory=dict)


@dataclass(frozen=True)
class QuoteIntent:
    bid_price: int | None = None
    bid_size: int = 0
    ask_price: int | None = None
    ask_size: int = 0


@dataclass(frozen=True)
class SignalIntent:
    product: Product
    fair_value: FairValueEstimate
    mode: ExecutionMode = "idle"
    buy_below: float | None = None
    sell_above: float | None = None
    quote: QuoteIntent | None = None
    rationale: str = ""
    metadata: dict[str, Scalar] = field(default_factory=dict)


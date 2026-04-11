from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.core.config import ProductConfig
from src.core.types import NormalizedSnapshot, ProductMemory, SignalIntent


@dataclass(frozen=True)
class StrategyContext:
    product: str
    snapshot: NormalizedSnapshot
    memory: ProductMemory
    config: ProductConfig


class BaseStrategy(ABC):
    @abstractmethod
    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        raise NotImplementedError

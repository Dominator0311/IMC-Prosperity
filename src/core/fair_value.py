from __future__ import annotations

from src.core.config import ProductConfig
from src.core.types import FairValueEstimate, NormalizedSnapshot, ProductMemory
from src.core.utils import weighted_average


class FairValueEngine:
    def estimate(
        self,
        product: str,
        snapshot: NormalizedSnapshot,
        memory: ProductMemory,
        config: ProductConfig,
    ) -> FairValueEstimate:
        method = config.fair_value_method

        if method == "anchor" and config.anchor_price is not None:
            return FairValueEstimate(
                price=float(config.anchor_price),
                method="anchor",
                confidence=1.0,
                components={"anchor_price": config.anchor_price},
            )

        if method == "microprice" and snapshot.microprice is not None:
            return FairValueEstimate(
                price=float(snapshot.microprice),
                method="microprice",
                confidence=0.8,
                components={"imbalance": snapshot.book_imbalance or 0.0},
            )

        if method == "mid" and snapshot.mid is not None:
            return FairValueEstimate(
                price=float(snapshot.mid),
                method="mid",
                confidence=0.7,
            )

        if method == "rolling_mid":
            history = memory.recent_mids + ([snapshot.mid] if snapshot.mid is not None else [])
            if history:
                price = sum(history) / len(history)
                return FairValueEstimate(price=price, method="rolling_mid", confidence=0.65)

        if method == "weighted_mid":
            history = memory.recent_mids[-4:]
            if snapshot.mid is not None:
                values = [*history, snapshot.mid]
                weights = list(range(1, len(values) + 1))
                price = weighted_average(values, weights)
                return FairValueEstimate(price=price, method="weighted_mid", confidence=0.7)

        if snapshot.microprice is not None:
            return FairValueEstimate(price=float(snapshot.microprice), method="microprice_fallback")

        if snapshot.mid is not None:
            return FairValueEstimate(price=float(snapshot.mid), method="mid_fallback")

        if memory.recent_mids:
            return FairValueEstimate(price=memory.recent_mids[-1], method="memory_fallback")

        if config.anchor_price is not None:
            return FairValueEstimate(price=float(config.anchor_price), method="anchor_fallback")

        return FairValueEstimate(price=0.0, method="zero_fallback", confidence=0.0)

"""Slim R3 VELVET/options submission factory.

This profile intentionally bypasses the generic Trader/orchestrator stack so
the diagnostic upload stays below the Prosperity bundle-size limit.
"""

from __future__ import annotations

import json
from collections import defaultdict

from src.core.market_data import MarketDataAdapter
from src.engines.r3_velvet_options_engine import R3VelvetOptionsEngine
from src.datamodel import Order, TradingState


class Trader:
    """Zero-arg Prosperity Trader for the isolated VELVET/options sleeve."""

    def __init__(self) -> None:
        self.market_data = MarketDataAdapter()
        self.engine = R3VelvetOptionsEngine()

    def run(self, state: TradingState) -> tuple[dict[str, list[Order]], int, str]:
        try:
            blob = _load_state_blob(state.traderData)
            engine_blob = blob.get("engine", {})
            if isinstance(engine_blob, dict):
                self.engine.from_state(engine_blob)

            snapshots = self.market_data.normalize_state(state)
            positions = {product: snap.position for product, snap in snapshots.items()}
            orders = self.engine.step(
                snapshots=snapshots,
                positions=positions,
                timestamp=int(state.timestamp),
            )

            grouped: dict[str, list[Order]] = defaultdict(list)
            for order in orders:
                grouped[order.symbol].append(order)

            next_blob = {"v": 1, "engine": self.engine.to_state()}
            trader_data = json.dumps(next_blob, separators=(",", ":"))
            return dict(grouped), 0, trader_data
        except Exception:
            return {}, 0, state.traderData


def _load_state_blob(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        blob = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return blob if isinstance(blob, dict) else {}

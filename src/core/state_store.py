from __future__ import annotations

import json
from dataclasses import asdict

from src.core.types import EngineState, ProductMemory


class StateStore:
    def __init__(self, version: int = 1, max_chars: int = 50_000) -> None:
        self.version = version
        self.max_chars = max_chars

    def load(self, trader_data: str | None) -> EngineState:
        if not trader_data:
            return EngineState(version=self.version)

        try:
            raw = json.loads(trader_data)
        except (TypeError, json.JSONDecodeError):
            return EngineState(version=self.version)

        if not isinstance(raw, dict):
            return EngineState(version=self.version)

        state = EngineState(version=int(raw.get("version", self.version)))
        raw_products = raw.get("products", {})
        if not isinstance(raw_products, dict):
            return state

        for product, payload in raw_products.items():
            if not isinstance(payload, dict):
                continue
            state.products[product] = ProductMemory(
                recent_mids=self._coerce_float_list(payload.get("recent_mids")),
                recent_spreads=self._coerce_float_list(payload.get("recent_spreads")),
                counters=self._coerce_int_dict(payload.get("counters")),
                flags=self._coerce_bool_dict(payload.get("flags")),
                values=self._coerce_float_dict(payload.get("values")),
            )

        return state

    def save(self, state: EngineState) -> str:
        payload = asdict(state)
        payload["version"] = self.version

        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if len(encoded) <= self.max_chars:
            return encoded

        compact = {"version": self.version, "products": {}}
        for product, memory in state.products.items():
            compact["products"][product] = {
                "recent_mids": memory.recent_mids[-8:],
                "recent_spreads": memory.recent_spreads[-8:],
                "counters": memory.counters,
                "flags": memory.flags,
                "values": memory.values,
            }

        encoded = json.dumps(compact, separators=(",", ":"), sort_keys=True)
        if len(encoded) <= self.max_chars:
            return encoded

        return json.dumps({"version": self.version, "products": {}}, separators=(",", ":"))

    @staticmethod
    def _coerce_float_list(value: object) -> list[float]:
        if not isinstance(value, list):
            return []
        return [float(item) for item in value if isinstance(item, (int, float))]

    @staticmethod
    def _coerce_int_dict(value: object) -> dict[str, int]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): int(item)
            for key, item in value.items()
            if isinstance(item, (int, float))
        }

    @staticmethod
    def _coerce_bool_dict(value: object) -> dict[str, bool]:
        if not isinstance(value, dict):
            return {}
        return {str(key): bool(item) for key, item in value.items()}

    @staticmethod
    def _coerce_float_dict(value: object) -> dict[str, float]:
        if not isinstance(value, dict):
            return {}
        return {
            str(key): float(item)
            for key, item in value.items()
            if isinstance(item, (int, float))
        }


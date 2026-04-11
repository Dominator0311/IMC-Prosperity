from __future__ import annotations

import json


class DecisionLogger:
    def __init__(self, max_events: int = 256) -> None:
        self.max_events = max_events
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]

    def to_json(self, max_chars: int = 4_000) -> str:
        payload = json.dumps(self.events, separators=(",", ":"), sort_keys=True)
        if len(payload) <= max_chars:
            return payload
        return payload[: max_chars - 3] + "..."

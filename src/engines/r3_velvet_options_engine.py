"""Minimal live engine for the isolated R3 VELVET/options branch."""

from __future__ import annotations

from src.core.r3_products import VELVETFRUIT_EXTRACT, VOUCHER_STRIKES
from src.core.types import NormalizedSnapshot
from src.datamodel import Order
from src.strategies.round_3.velvet_options_rolling_iv import (
    RollingIVOptionsConfig,
    RollingIVOptionsState,
    rolling_iv_option_orders,
)


class R3VelvetOptionsEngine:
    """VELVET/options-only engine for attribution uploads."""

    def __init__(self) -> None:
        self._state = RollingIVOptionsState()
        self._config = RollingIVOptionsConfig(terminal_flatten_start=None)

    def to_state(self) -> dict:
        return {"rolling_iv_options": self._state.to_state()}

    def from_state(self, blob: dict) -> None:
        if not isinstance(blob, dict):
            return
        rolling_blob = blob.get("rolling_iv_options", {})
        if isinstance(rolling_blob, dict):
            self._state.from_state(rolling_blob)

    def step(
        self,
        *,
        snapshots: dict[str, NormalizedSnapshot],
        positions: dict[str, int],
        timestamp: int,
    ) -> list[Order]:
        option_snaps: dict[str, NormalizedSnapshot] = {}
        for strike in VOUCHER_STRIKES:
            product = f"VEV_{strike}"
            snap = snapshots.get(product)
            if snap is not None:
                option_snaps[product] = snap

        return rolling_iv_option_orders(
            velvet_snapshot=snapshots.get(VELVETFRUIT_EXTRACT),
            option_snapshots=option_snaps,
            positions=positions,
            timestamp=timestamp,
            state=self._state,
            config=self._config,
        )

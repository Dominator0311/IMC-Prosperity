"""Generic trade-flow pattern detection framework.

This module is an **observational** layer. It detects patterns in the
market trade tape (repeated sizes, directional flow, trades near local
extrema) and returns an ephemeral ``FlowReport``. It never alters
strategy behaviour, fair-value estimates, or execution decisions.

Persisted state (via ``ProductMemory``) is kept to the absolute minimum
needed for cross-call continuity:

- ``values["scan_flow_score"]`` — decayed directional score in [-1, 1].
- ``counters["scan_step_count"]`` — number of steps the scanner has run.

Extrema (high / low) are derived from ``memory.recent_mids`` each step
and are **not** persisted.

Net-flow convention (heuristic, not true aggressor inference):
- Trade with only ``buyer`` populated → +quantity (buy pressure proxy).
- Trade with only ``seller`` populated -> -quantity (sell pressure proxy).
- Trade with both or neither → 0 (ambiguous, excluded from flow).
"""

from __future__ import annotations

from collections import Counter
from types import MappingProxyType

from src.core.types import (
    FlowReport,
    NormalizedSnapshot,
    ProductMemory,
    ScannerConfig,
    TradePrint,
)

# ---------------------------------------------------------------- keys

_KEY_FLOW_SCORE = "scan_flow_score"
_KEY_STEP_COUNT = "scan_step_count"


class FlowAnalyzer:
    """Stateless scanner — all mutable state lives in ``ProductMemory``."""

    def __init__(self, config: ScannerConfig) -> None:
        self.config = config

    # -------------------------------------------------------------- public

    def scan(
        self,
        snapshot: NormalizedSnapshot,
        memory: ProductMemory,
    ) -> FlowReport | None:
        """Analyse the current step's trade tape and return a report.

        Returns ``None`` when the scanner is disabled so the caller can
        skip any downstream logging unconditionally.
        """
        if not self.config.enabled:
            return None

        market_trades = tuple(t for t in snapshot.trades if t.source == "market")

        repeated_sizes = _count_sizes(market_trades)
        net_flow = _compute_net_flow(market_trades)
        total_volume = sum(t.quantity for t in market_trades) or 1

        old_score = memory.values.get(_KEY_FLOW_SCORE, 0.0)
        normalised = max(-1.0, min(1.0, net_flow / total_volume))
        new_score = self.config.flow_decay * old_score + (1.0 - self.config.flow_decay) * normalised
        new_score = max(-1.0, min(1.0, new_score))

        recent_high, recent_low = _derive_extrema(memory.recent_mids, self.config.extrema_window)
        near_high = _any_near(market_trades, recent_high, self.config.extrema_tolerance)
        near_low = _any_near(market_trades, recent_low, self.config.extrema_tolerance)

        flags = _build_flags(
            repeated_sizes=repeated_sizes,
            flow_score=new_score,
            near_high=near_high,
            near_low=near_low,
            threshold=self.config.repeated_size_threshold,
        )

        # Persist minimal state -------------------------------------------
        memory.values[_KEY_FLOW_SCORE] = new_score
        memory.counters[_KEY_STEP_COUNT] = memory.counters.get(_KEY_STEP_COUNT, 0) + 1

        return FlowReport(
            product=snapshot.product,
            timestamp=snapshot.timestamp,
            repeated_sizes=MappingProxyType(repeated_sizes),
            net_flow=net_flow,
            flow_score=round(new_score, 6),
            near_high=near_high,
            near_low=near_low,
            flags=flags,
            metadata=MappingProxyType(
                {
                    "market_trade_count": len(market_trades),
                    "total_volume": total_volume,
                }
            ),
        )


# -------------------------------------------------------------- helpers


def _count_sizes(trades: tuple[TradePrint, ...]) -> dict[int, int]:
    """Count how many times each trade quantity appears."""
    return dict(Counter(t.quantity for t in trades))


def _compute_net_flow(trades: tuple[TradePrint, ...]) -> int:
    """Heuristic signed net volume.

    This is a *proxy* for directional pressure — it does not claim to
    infer the true aggressor side. The convention is intentionally
    conservative: ambiguous trades (both buyer and seller populated, or
    neither) contribute zero.
    """
    net = 0
    for t in trades:
        has_buyer = t.buyer is not None and t.buyer != ""
        has_seller = t.seller is not None and t.seller != ""
        if has_buyer and not has_seller:
            net += t.quantity
        elif has_seller and not has_buyer:
            net -= t.quantity
        # both or neither → ambiguous, skip
    return net


def _derive_extrema(recent_mids: list[float], window: int) -> tuple[float | None, float | None]:
    """Return (high, low) from the last *window* mid prices, or None."""
    if not recent_mids:
        return None, None
    tail = recent_mids[-window:] if window > 0 else recent_mids
    return max(tail), min(tail)


def _any_near(
    trades: tuple[TradePrint, ...],
    level: float | None,
    tolerance: float,
) -> bool:
    """True if any trade price is within *tolerance* of *level*."""
    if level is None or not trades:
        return False
    return any(abs(t.price - level) <= tolerance for t in trades)


def _build_flags(
    *,
    repeated_sizes: dict[int, int],
    flow_score: float,
    near_high: bool,
    near_low: bool,
    threshold: int,
) -> tuple[str, ...]:
    """Build a tuple of human-readable pattern labels."""
    flags: list[str] = []

    for qty, count in sorted(repeated_sizes.items()):
        if count >= threshold:
            flags.append(f"repeated_size_{qty}x{count}")

    if flow_score > 0.5:
        flags.append("buy_pressure")
    elif flow_score < -0.5:
        flags.append("sell_pressure")

    if near_high:
        flags.append("near_local_high")
    if near_low:
        flags.append("near_local_low")

    return tuple(flags)

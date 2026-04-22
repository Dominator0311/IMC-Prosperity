"""Research-only ASH ladder strategy for Phase-I I2a upload.

Self-contained (no imports from ash_shape_override) so the bundler's
single-module inlining works. Implements tick-rotation quote ladder:
each tick we pick one of N edge levels in round-robin order and post
bid/ask at that edge. Over many ticks this approximates a multi-level
maker book.

NOT part of the shipped submission. Registered at bundle tail under
STRATEGY_REGISTRY["ash_ladder"] by the export script.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    ExecutionMode,
    FairValueEstimate,
    NormalizedSnapshot,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class LadderParams:
    """Tick-rotation ladder parameters with Phase-J extensions."""

    # Edge levels (ticks away from fair). One is selected per tick.
    edges: tuple[float, ...] = (2.5, 5.0, 8.0, 12.0)
    size_mults: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)
    skew_coef: float = 2.0
    flatten_threshold: float = 0.7

    # Phase-J: weighted rotation. If None, equal weight (F3a-I2a behavior).
    # If given, level i gets weights[i] / sum(weights) of tick-slots.
    # Implemented as deterministic pattern (not random), repeating every
    # sum(weights) ticks.
    weights: tuple[int, ...] | None = None

    # Phase-J: spread-gated outer levels. If True, outer levels
    # (index > 0) are only used when book_spread >= gate_spread.
    # At inner level, always use edges[0].
    spread_gate_enabled: bool = False
    gate_spread: int = 16

    # Phase-J: inventory-asymmetric. If True, when long (pos > 0) only
    # use outer levels on SELL side; when short, only on BUY side. Inner
    # side always uses edges[0].
    inventory_asymmetric: bool = False

    # Phase-K: per-side asymmetric schedule. If set, use these instead
    # of `edges`/`size_mults`/`weights` for the respective side.
    buy_edges: tuple[float, ...] | None = None
    buy_size_mults: tuple[float, ...] | None = None
    buy_weights: tuple[int, ...] | None = None
    sell_edges: tuple[float, ...] | None = None
    sell_size_mults: tuple[float, ...] | None = None
    sell_weights: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if not self.edges:
            raise ValueError("edges must be non-empty")
        if len(self.edges) != len(self.size_mults):
            raise ValueError("edges and size_mults must match length")
        if not 0.0 <= self.flatten_threshold <= 1.0:
            raise ValueError("flatten_threshold must be in [0, 1]")
        if self.weights is not None and len(self.weights) != len(self.edges):
            raise ValueError("weights must match edges length")
        if self.weights is not None and any(w < 0 for w in self.weights):
            raise ValueError("weights must be non-negative")
        # Per-side schedule validation
        for side_edges, side_mults, side_weights in (
            (self.buy_edges, self.buy_size_mults, self.buy_weights),
            (self.sell_edges, self.sell_size_mults, self.sell_weights),
        ):
            if side_edges is None:
                continue
            if side_mults is None or len(side_mults) != len(side_edges):
                raise ValueError("per-side size_mults must match edges length")
            if side_weights is not None and len(side_weights) != len(side_edges):
                raise ValueError("per-side weights must match edges length")


class AshLadderStrategy(BaseStrategy):
    """Tick-rotation ladder market-maker for ASH.

    Each tick, the strategy picks edge level `tick_counter % len(edges)`
    and posts bid at `fair - edge - skew` / ask at `fair + edge - skew`.
    Skew is linear in normalized position (F3a shape). Hard-flattens
    when |position/limit| >= threshold.
    """

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: LadderParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def _build_schedule(
        self, weights: tuple[int, ...] | None, n: int, cache_name: str,
    ) -> tuple[int, ...]:
        cached = getattr(self, cache_name, None)
        if cached is not None:
            return cached
        if weights is None:
            sched = tuple(range(n))
        else:
            sched = []
            for i, w in enumerate(weights):
                sched.extend([i] * int(w))
            if not sched:
                sched = list(range(n))
            sched = tuple(sched)
        object.__setattr__(self, cache_name, sched)
        return sched

    def _pick_level(
        self, counter: int, snapshot: NormalizedSnapshot,
    ) -> int:
        """Select which edge level this tick uses (symmetric path)."""
        params = self.params
        sched = self._build_schedule(
            params.weights, len(params.edges), "_cached_schedule",
        )
        return sched[counter % len(sched)]

    def _pick_side_level(
        self, counter: int, side: str,
    ) -> tuple[float, float] | None:
        """Pick edge & size mult for a given side if per-side schedule is set.

        Returns None if no per-side override is configured.
        """
        params = self.params
        if side == "buy":
            edges = params.buy_edges
            mults = params.buy_size_mults
            weights = params.buy_weights
            cache = "_cached_buy_schedule"
        else:
            edges = params.sell_edges
            mults = params.sell_size_mults
            weights = params.sell_weights
            cache = "_cached_sell_schedule"
        if edges is None:
            return None
        sched = self._build_schedule(weights, len(edges), cache)
        idx = sched[counter % len(sched)]
        return float(edges[idx]), float(mults[idx])

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        memory = context.memory
        params = self.params

        fair_value = self.fair_value_engine.estimate(
            product, snapshot, memory, config
        )

        # Pick ladder level for this tick.
        counter = int(memory.counters.get("ash_ladder_counter", 0))
        level = self._pick_level(counter, snapshot)
        edge = float(params.edges[level])
        size_mult = float(params.size_mults[level])
        memory.counters["ash_ladder_counter"] = counter + 1

        # Spread gating: if the book spread is tight, force inner level.
        if params.spread_gate_enabled and level > 0:
            if snapshot.best_bid is not None and snapshot.best_ask is not None:
                book_spread = int(snapshot.best_ask.price - snapshot.best_bid.price)
                if book_spread < params.gate_spread:
                    level = 0
                    edge = float(params.edges[0])
                    size_mult = float(params.size_mults[0])

        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        skew = params.skew_coef * position_ratio

        flattening = abs(position_ratio) >= params.flatten_threshold

        buy_below: float | None = fair_value.price - config.taker_edge - skew
        sell_above: float | None = fair_value.price + config.taker_edge - skew

        # Default: use `edge` on both sides, with global size_mult.
        bid_edge = edge
        ask_edge = edge
        bid_mult = size_mult
        ask_mult = size_mult

        # Phase-K per-side asymmetric override.
        buy_ps = self._pick_side_level(counter, "buy")
        if buy_ps is not None:
            bid_edge, bid_mult = buy_ps
        sell_ps = self._pick_side_level(counter, "sell")
        if sell_ps is not None:
            ask_edge, ask_mult = sell_ps

        # Phase-J inventory-asymmetric: apply outer only on the unwinding side.
        if params.inventory_asymmetric and level > 0:
            inner_edge = float(params.edges[0])
            if snapshot.position > 0:
                bid_edge = inner_edge
            elif snapshot.position < 0:
                ask_edge = inner_edge

        raw_bid = math.floor(fair_value.price - bid_edge - skew)
        raw_ask = math.ceil(fair_value.price + ask_edge - skew)

        if snapshot.best_ask is not None:
            raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
        if snapshot.best_bid is not None:
            raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

        base_size = config.quote_size
        bid_size = max(1, int(round(base_size * bid_mult)))
        ask_size = max(1, int(round(base_size * ask_mult)))

        mode: ExecutionMode = "hybrid"
        rationale = f"ash_ladder_lvl{level}"
        if flattening:
            mode = "recovery"
            rationale = "ash_ladder_recovery"
            if snapshot.position > 0:
                bid_size = 0
                buy_below = None
                raw_ask = min(raw_ask, math.floor(fair_value.price))
            elif snapshot.position < 0:
                ask_size = 0
                sell_above = None
                raw_bid = max(raw_bid, math.ceil(fair_value.price))

        quote = QuoteIntent(
            bid_price=raw_bid if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=raw_ask if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "position_ratio": round(position_ratio, 4),
            "skew": round(skew, 4),
            "edge": edge,
            "level": level,
            "size_mult": size_mult,
            "flattening": flattening,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode=mode,
            buy_below=buy_below,
            sell_above=sell_above,
            quote=quote,
            rationale=rationale,
            metadata=MappingProxyType(metadata),
        )

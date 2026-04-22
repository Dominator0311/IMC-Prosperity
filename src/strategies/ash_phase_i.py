"""Research-only ASH strategies for Phase I (post-Phase-H exploration).

Four parameterized extensions on top of the F3a/shape-override baseline:

- **passive_only**: disables taker entirely (buy_below/sell_above = None).
- **profit_target**: tracks a weighted-average entry price in memory and
  flattens when current mid is >= ``profit_target_ticks`` in our favor.
- **spread_regime**: scales maker_edge by the observed book spread
  (wide spread → tighter quotes relative to fair, narrow spread →
  wider quotes or skip).
- **scalp_reload**: when inventory is non-zero and below the flatten
  threshold, tightens the *unwinding* side by ``scalp_tighten_ticks``
  to capture the OU reversion.

All four features can be combined via ``PhaseIParams``. All four reuse
the F3a shape primitives (linear skew, hard flatten, constant size).

NOT part of the shipped submission bundle; registered only at runtime
by the Phase-I runner cells.
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
    ProductMemory,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.ash_shape_override import (
    ShapeParams,
    compute_flatten,
    compute_sizes,
    compute_skew,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class PhaseIParams:
    """All tunable knobs for the four Phase-I features."""

    # Shape defaults identical to F3a
    shape: ShapeParams = ShapeParams(
        skew_mode="linear", skew_coef=2.0,
        flatten_mode="hard", flatten_threshold=0.7,
        size_mode="constant",
    )

    # I1: passive_only
    passive_only: bool = False

    # I3: profit_target — flatten if (mid - avg_entry) * sign(position) >= ticks
    profit_target_enabled: bool = False
    profit_target_ticks: float = 3.0

    # I4: spread_regime
    # If book_spread >= wide_spread_threshold: use wide_maker_edge_mult * base
    # If book_spread <= narrow_spread_threshold: skip quoting (or use narrow_mult)
    spread_regime_enabled: bool = False
    wide_spread_threshold: int = 16      # >=16 → "normal/wide"
    narrow_spread_threshold: int = 12    # <=12 → tight market, skip or mult
    wide_maker_edge_mult: float = 1.0    # no change in wide regime
    narrow_maker_edge_mult: float = 1.0  # no change in narrow regime
    skip_in_narrow: bool = False         # if True, return empty quote in narrow

    # I5: scalp_reload — tighten the unwinding side
    scalp_reload_enabled: bool = False
    scalp_tighten_ticks: float = 1.0

    # I2: ladder — rotate quote levels across consecutive ticks
    # Each tick we quote at ladder_edges[tick_index % len]
    # Size multiplies base quote_size by ladder_sizes[tick_index % len]
    ladder_enabled: bool = False
    ladder_edges: tuple[float, ...] = (2.5, 5.0, 8.0, 12.0)
    ladder_size_mults: tuple[float, ...] = (1.0, 1.5, 2.0, 3.0)

    def __post_init__(self) -> None:
        if self.profit_target_ticks < 0:
            raise ValueError("profit_target_ticks must be >= 0")
        if self.scalp_tighten_ticks < 0:
            raise ValueError("scalp_tighten_ticks must be >= 0")
        if self.ladder_enabled:
            if not self.ladder_edges:
                raise ValueError("ladder_edges must be non-empty when ladder_enabled")
            if len(self.ladder_edges) != len(self.ladder_size_mults):
                raise ValueError("ladder_edges and ladder_size_mults must have same length")


# Memory keys for profit_target state
_AVG_ENTRY_KEY = "phase_i_avg_entry"
_PRIOR_POSITION_KEY = "phase_i_prior_position"


class AshPhaseIStrategy(BaseStrategy):
    """Research strategy with passive / profit-target / regime / scalp features."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: PhaseIParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        memory = context.memory
        params = self.params

        fair_value = self.fair_value_engine.estimate(
            product, snapshot, memory, config
        )

        # --- I3: update avg entry price based on position change since last tick
        self._update_entry_tracker(snapshot, memory)

        # --- I3: profit-target flatten check (overrides the usual flatten logic)
        pt_flatten = self._check_profit_target(snapshot, memory)

        # --- I4: spread-regime gate
        if params.spread_regime_enabled:
            book_spread = self._book_spread(snapshot)
            if book_spread is not None:
                if (
                    params.skip_in_narrow
                    and book_spread <= params.narrow_spread_threshold
                ):
                    return self._empty_intent(product, fair_value, "i4_narrow_skip")

        # Build the regular shape-override intent with feature overlays
        return self._build_intent(
            product, snapshot, fair_value, config, params, memory, pt_flatten,
        )

    # ----------------------------------------------------------------- helpers

    def _update_entry_tracker(
        self, snapshot: NormalizedSnapshot, memory: ProductMemory,
    ) -> None:
        prior = memory.values.get(_PRIOR_POSITION_KEY, 0.0)
        current = float(snapshot.position)
        delta = current - prior
        if delta != 0 and snapshot.mid is not None:
            # Position grew in the direction of `delta` at approximately `mid`.
            # If we added to the existing direction, weighted-avg the entry.
            # If we reduced (delta opposes position), leave avg unchanged.
            old_avg = memory.values.get(_AVG_ENTRY_KEY, float(snapshot.mid))
            # Position went further from zero?
            further = (current * delta) > 0  # same sign → adding
            if further and current != 0:
                new_avg = (
                    (old_avg * prior + float(snapshot.mid) * delta) / current
                )
                memory.values[_AVG_ENTRY_KEY] = new_avg
            elif current == 0:
                # Fully flat — reset tracker
                memory.values[_AVG_ENTRY_KEY] = float(snapshot.mid)
        memory.values[_PRIOR_POSITION_KEY] = current

    def _check_profit_target(
        self, snapshot: NormalizedSnapshot, memory: ProductMemory,
    ) -> bool:
        if not self.params.profit_target_enabled:
            return False
        if snapshot.position == 0 or snapshot.mid is None:
            return False
        avg = memory.values.get(_AVG_ENTRY_KEY)
        if avg is None:
            return False
        sign = 1.0 if snapshot.position > 0 else -1.0
        markout = (float(snapshot.mid) - avg) * sign
        return markout >= self.params.profit_target_ticks

    def _book_spread(self, snapshot: NormalizedSnapshot) -> float | None:
        if snapshot.best_bid is None or snapshot.best_ask is None:
            return None
        return float(snapshot.best_ask.price - snapshot.best_bid.price)

    def _empty_intent(
        self, product: str, fair_value: FairValueEstimate, rationale: str,
    ) -> SignalIntent:
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=None,
            sell_above=None,
            quote=QuoteIntent(),
            rationale=rationale,
            metadata=MappingProxyType({}),
        )

    def _build_intent(
        self,
        product: str,
        snapshot: NormalizedSnapshot,
        fair_value: FairValueEstimate,
        config: ProductConfig,
        params: PhaseIParams,
        memory: ProductMemory,
        pt_flatten: bool,
    ) -> SignalIntent:
        shape = params.shape
        position_ratio = (
            snapshot.position / config.position_limit if config.position_limit else 0.0
        )
        time_remaining = max(
            0.0, float(shape.as_horizon) - float(snapshot.timestamp),
        )
        skew = compute_skew(
            position_ratio=position_ratio,
            config=config,
            params=shape,
            time_remaining=time_remaining,
        )
        flattening, extra_skew = compute_flatten(
            position_ratio=position_ratio, config=config, params=shape,
        )
        skew += extra_skew
        # Profit-target takes priority as a flatten signal
        if pt_flatten:
            flattening = True

        # --- I4: spread-regime maker edge scaling
        maker_edge = float(config.maker_edge)
        if params.spread_regime_enabled:
            book_spread = self._book_spread(snapshot)
            if book_spread is not None:
                if book_spread >= params.wide_spread_threshold:
                    maker_edge *= params.wide_maker_edge_mult
                elif book_spread <= params.narrow_spread_threshold:
                    maker_edge *= params.narrow_maker_edge_mult

        # --- I2: ladder — rotate through edge levels tick-by-tick
        size_mult = 1.0
        if params.ladder_enabled:
            tick_idx = int(memory.counters.get("phase_i_ladder_counter", 0))
            level = tick_idx % len(params.ladder_edges)
            maker_edge = float(params.ladder_edges[level])
            size_mult = float(params.ladder_size_mults[level])
            memory.counters["phase_i_ladder_counter"] = tick_idx + 1

        # --- I1: passive_only disables taker
        if params.passive_only:
            buy_below: float | None = None
            sell_above: float | None = None
        else:
            buy_below = fair_value.price - config.taker_edge - skew
            sell_above = fair_value.price + config.taker_edge - skew

        raw_bid = math.floor(fair_value.price - maker_edge - skew)
        raw_ask = math.ceil(fair_value.price + maker_edge - skew)

        # --- I5: scalp-reload tightens the unwinding side
        if params.scalp_reload_enabled and snapshot.position != 0 and not flattening:
            if snapshot.position > 0:
                # Long; tighten the ask (unwinding side)
                raw_ask = math.ceil(
                    fair_value.price + max(0.0, maker_edge - params.scalp_tighten_ticks)
                    - skew
                )
            else:
                # Short; tighten the bid
                raw_bid = math.floor(
                    fair_value.price - max(0.0, maker_edge - params.scalp_tighten_ticks)
                    - skew
                )

        if snapshot.best_ask is not None:
            raw_bid = min(raw_bid, snapshot.best_ask.price - config.tick_size)
        if snapshot.best_bid is not None:
            raw_ask = max(raw_ask, snapshot.best_bid.price + config.tick_size)

        bid_size, ask_size = compute_sizes(
            position_ratio=position_ratio, config=config, params=shape,
        )

        # --- I2: scale sizes by ladder size multiplier
        if params.ladder_enabled:
            bid_size = max(1, int(round(bid_size * size_mult)))
            ask_size = max(1, int(round(ask_size * size_mult)))

        mode: ExecutionMode = "hybrid"
        rationale = "ash_phase_i"
        if flattening:
            mode = "recovery"
            rationale = (
                "ash_phase_i_profit_target" if pt_flatten else "ash_phase_i_recovery"
            )
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
            "maker_edge": round(maker_edge, 4),
            "flattening": flattening,
            "pt_flatten": pt_flatten,
            "passive_only": params.passive_only,
            "scalp_reload": params.scalp_reload_enabled,
            "spread_regime": params.spread_regime_enabled,
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

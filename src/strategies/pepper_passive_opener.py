"""PEPPER passive-first opening strategy (research-only).

All prior PEPPER opening experiments (V2, V3, J-series) open with a
TAKER cross. That pays the full half-spread on 30-80 units of opening
inventory — roughly 7-15 ticks × 30-80 units = 200-1200 PnL donated
to the book at t=0.

This strategy flips the opening:

1. t=0 to t=opening_passive_window: post a passive bid at
   ``best_bid + tick`` with quote_size=max_aggressive_size. Do NOT
   take the ask. If the book walks to our level, we fill passively.
2. At ``opening_taker_fallback_tick``: if we still haven't reached
   the seed target, transition to taker fallback (cross asks up to
   ``max_aggressive_size`` per tick).
3. After opening: steady-state is a drift-aware carry with small
   maker overlay, identical in spirit to ``PepperPassiveMaker`` but
   biased toward the passive-first entry signature.

Rationale: PEPPER's drift is +~0.1/tick. Waiting 5-10 ticks to fill
passively costs ~0.5-1 tick of drift gain per unit, but saves
6-7 ticks of half-spread per unit. Net: ~5-6 ticks × 40 units ≈
+200-240 PnL of opening edge, which neither the level1_only nor
all_asks V3 opens captured.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import (
    FairValueEstimate,
    QuoteIntent,
    Scalar,
    SignalIntent,
)
from src.strategies.base import BaseStrategy, StrategyContext


@dataclass(frozen=True)
class PassiveOpenerParams:
    """Tunable knobs for PepperPassiveOpener.

    Defaults from first-principles:

    - ``opening_passive_window=3`` ticks: short enough that passive
      non-fills don't cost meaningful drift carry (3 × 0.1 = 0.3 ticks
      of drift per unit), long enough for book walk to fill inside
      orders.
    - ``opening_taker_fallback_tick=3``: start taker at end of passive
      window if seed not met.
    - ``passive_bid_improve=1``: improve best bid by exactly one tick.
      Minimal improvement maximizes fill prob while minimizing
      chase-cost if the book re-quotes.
    - ``seed_size=40``: same 40 as the other strategies — balanced
      between drift-carry and maker-cycling capacity.
    - ``opening_max_size_per_tick=20``: cap per-tick exposure during
      the passive window. If 20 units fill passively at t=0, that's
      already 25% of full position with zero spread cost.
    - ``steady_core_target=40``: same as passive_maker for consistency.
    """

    # --- Opening executor ---
    opening_passive_window: int = 3
    opening_taker_fallback_tick: int = 3
    passive_bid_improve: int = 1
    opening_max_size_per_tick: int = 20
    # --- Target inventory during open ---
    seed_size: int = 40
    # --- Steady-state carry ---
    steady_core_target: int = 40
    # --- Maker overlay ---
    maker_bid_edge: float = 3.0
    maker_ask_edge: float = 5.0
    maker_quote_size: int = 5
    inventory_skew_coef: float = 0.04
    # --- Hard limits ---
    floor: int = 0
    ceiling: int = 80
    # --- Safety ---
    min_spread_for_maker: int = 4
    # Memory key for open-phase tick counter.
    opener_tick_key: str = "passive_opener_ticks"

    def __post_init__(self) -> None:
        if self.opening_passive_window < 0:
            raise ValueError(
                "opening_passive_window must be >= 0 "
                f"(got {self.opening_passive_window})"
            )
        if self.opening_taker_fallback_tick < 0:
            raise ValueError(
                "opening_taker_fallback_tick must be >= 0 "
                f"(got {self.opening_taker_fallback_tick})"
            )
        if self.passive_bid_improve < 0:
            raise ValueError(
                f"passive_bid_improve must be >= 0 "
                f"(got {self.passive_bid_improve})"
            )
        if self.opening_max_size_per_tick < 0:
            raise ValueError(
                f"opening_max_size_per_tick must be >= 0 "
                f"(got {self.opening_max_size_per_tick})"
            )
        if self.seed_size < 0:
            raise ValueError(f"seed_size must be >= 0 (got {self.seed_size})")
        if self.steady_core_target < 0:
            raise ValueError(
                f"steady_core_target must be >= 0 "
                f"(got {self.steady_core_target})"
            )
        if self.maker_bid_edge < 0 or self.maker_ask_edge < 0:
            raise ValueError("maker_*_edge must be >= 0")
        if self.maker_quote_size < 0:
            raise ValueError(
                f"maker_quote_size must be >= 0 (got {self.maker_quote_size})"
            )
        if self.inventory_skew_coef < 0:
            raise ValueError(
                f"inventory_skew_coef must be >= 0 "
                f"(got {self.inventory_skew_coef})"
            )
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if self.seed_size > self.ceiling:
            raise ValueError(
                f"seed_size ({self.seed_size}) must be <= ceiling ({self.ceiling})"
            )
        if not self.floor <= self.steady_core_target <= self.ceiling:
            raise ValueError(
                "steady_core_target must lie in [floor, ceiling] "
                f"(got {self.steady_core_target})"
            )
        if self.min_spread_for_maker < 0:
            raise ValueError(
                f"min_spread_for_maker must be >= 0 "
                f"(got {self.min_spread_for_maker})"
            )


class PepperPassiveOpenerStrategy(BaseStrategy):
    """Passive-first opening; drift-maker carry after open."""

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: PassiveOpenerParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        memory = context.memory
        config = context.config
        params = self.params

        fair_value: FairValueEstimate = self.fair_value_engine.estimate(
            product, snapshot, memory, config
        )
        fair_price = float(fair_value.price)
        effective_ceiling = min(params.ceiling, config.position_limit)

        # --- Track elapsed ticks since first decision ---
        # We use a memory counter instead of snapshot.timestamp because
        # the official simulator and local replay have different tick
        # scales (100 vs 1 per snapshot). A counter gives us a stable
        # "snapshots since start" that is simulator-agnostic.
        tick_count = memory.counters.get(params.opener_tick_key, 0)
        memory.counters[params.opener_tick_key] = tick_count + 1

        below_seed = snapshot.position < params.seed_size
        in_passive_open = (
            tick_count < params.opening_passive_window and below_seed
        )
        in_taker_fallback = (
            tick_count >= params.opening_taker_fallback_tick
            and below_seed
            and params.seed_size > 0
        )

        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        spread = snapshot.spread
        mid = snapshot.mid if snapshot.mid is not None else fair_price

        # --- Opening passive bid ---
        bid_price: int | None = None
        ask_price: int | None = None
        bid_size = 0
        ask_size = 0
        taker_buy_px: float | None = None
        taker_sell_px: float | None = None

        if in_passive_open and best_bid is not None:
            # Improve the touch
            passive_px = best_bid.price + params.passive_bid_improve
            # Don't cross the ask.
            if best_ask is not None:
                passive_px = min(passive_px, best_ask.price - config.tick_size)
            buy_capacity = min(
                effective_ceiling - snapshot.position,
                params.seed_size - snapshot.position,
                params.opening_max_size_per_tick,
            )
            if buy_capacity > 0:
                bid_price = int(passive_px)
                bid_size = int(buy_capacity)

        if in_taker_fallback:
            # Switch to cross-any-ask (BuyAndHold semantics) to
            # finish seeding.
            taker_buy_px = 1e9

        # --- Steady-state maker (after opening) ---
        maker_enabled = spread is None or spread >= params.min_spread_for_maker
        past_opening = not below_seed or tick_count >= max(
            params.opening_passive_window,
            params.opening_taker_fallback_tick + 2,
        )
        if past_opening and maker_enabled:
            # Asymmetric maker around drift_fair with inventory skew.
            inventory_dev = snapshot.position - params.steady_core_target
            inv_skew = params.inventory_skew_coef * inventory_dev
            bid_edge = max(0.0, params.maker_bid_edge + inv_skew)
            ask_edge = max(0.0, params.maker_ask_edge - inv_skew)

            raw_bid_px = math.floor(fair_price - bid_edge)
            raw_ask_px = math.ceil(fair_price + ask_edge)
            if best_ask is not None:
                raw_bid_px = min(raw_bid_px, best_ask.price - config.tick_size)
            if best_bid is not None:
                raw_ask_px = max(raw_ask_px, best_bid.price + config.tick_size)
            if best_bid is not None:
                raw_bid_px = max(raw_bid_px, best_bid.price + config.tick_size)
            if best_ask is not None:
                raw_ask_px = min(raw_ask_px, best_ask.price - config.tick_size)
            if raw_ask_px <= raw_bid_px:
                raw_bid_px = raw_ask_px - config.tick_size

            qs = max(0, params.maker_quote_size)
            buy_capacity = effective_ceiling - snapshot.position
            sell_capacity = snapshot.position - params.floor

            # Overwrite the maker slot only if we aren't already using
            # it for a passive open bid.
            if qs > 0 and bid_price is None:
                if buy_capacity > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
            if qs > 0 and ask_price is None:
                if sell_capacity > 0 and snapshot.position > params.floor:
                    ask_price = raw_ask_px
                    ask_size = min(qs, sell_capacity)

        # --- Hard gates ---
        if snapshot.position >= effective_ceiling:
            bid_price = None
            bid_size = 0
            taker_buy_px = None
        if snapshot.position <= params.floor:
            ask_price = None
            ask_size = 0
            taker_sell_px = None
        # Never sell during the whole opening (until we hit seed).
        if below_seed and params.seed_size > 0:
            ask_price = None
            ask_size = 0
            taker_sell_px = None

        quote = QuoteIntent(
            bid_price=bid_price if bid_size > 0 else None,
            bid_size=bid_size,
            ask_price=ask_price if ask_size > 0 else None,
            ask_size=ask_size,
        )
        metadata: dict[str, Scalar] = {
            "fair_value": round(fair_price, 4),
            "mid": round(mid, 4),
            "spread": int(spread) if spread is not None else "none",
            "tick_count": tick_count,
            "below_seed": below_seed,
            "in_passive_open": in_passive_open,
            "in_taker_fallback": in_taker_fallback,
            "past_opening": past_opening,
            "maker_enabled": maker_enabled,
            "position": snapshot.position,
            "seed_size": params.seed_size,
            "steady_core_target": params.steady_core_target,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=taker_buy_px,
            sell_above=taker_sell_px,
            quote=quote,
            rationale="pepper_passive_opener",
            metadata=MappingProxyType(metadata),
        )

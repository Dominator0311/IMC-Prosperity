"""PEPPER passive-maker strategy (research-only).

Quote passively inside the touch, anchored to the ``linear_drift``
forecast (not mid), with an asymmetric long bias. The core idea:

- PEPPER has a ~13-tick wide spread but only ~2-3 ticks of residual noise.
- Taker round-trips cannot profitably capture the oscillation (spread
  eats the edge). Maker round-trips can.
- With a positive drift, the natural long-bias tilt is: tighter bid
  (get filled often on buys), wider ask (only sell on overshoot).

The strategy does four things per tick:

1. Compute drift-forecast fair value (``linear_drift``, via the
   FairValueEngine).
2. Bootstrap long to ``core_target`` via a passive bid (``seed_mode="passive"``)
   or taker fallback if not filled fast enough.
3. Steady-state: post bid at ``drift_fair - bid_edge``, ask at
   ``drift_fair + ask_edge``, with ``ask_edge > bid_edge`` when net-long.
4. Pull quotes inside the touch (``best_bid+1``/``best_ask-1``) as the
   binding constraint — never rest outside the touch.

Intentionally separate from ``PepperCoreLongStrategy``: that strategy
is drift-carry-plus-residual; this one is inside-spread-maker with
carry as a secondary. Registered research-only (not in
``STRATEGY_REGISTRY``); wired in via export bundles following the
``pepper_core_long`` pattern.
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

SEED_MODES: tuple[str, ...] = ("passive", "taker", "off")


@dataclass(frozen=True)
class PassiveMakerParams:
    """Tunable knobs for PepperPassiveMaker.

    Defaults are chosen from FIRST-PRINCIPLES microstructure properties
    observed across all 3 real days (not fitted to any single day):

    - Spread is dominantly 13-16 ticks wide. ``bid_edge=3`` / ``ask_edge=5``
      both sit *inside* the dominant spread, and keep ``ask_edge > bid_edge``
      to give PEPPER's positive drift a long bias.
    - Core long target 40 (not 80): leaves 40 units of headroom for
      maker cycling. 80-core freezes the strategy into buy-and-hold,
      which is the local optimum the V3 family already hit.
    - Quote size 5: matches default ``ProductConfig.quote_size`` and
      keeps maker orders small so adverse selection is bounded.
    - Seed window 500 ticks: matches V3 open_window so opening
      execution cost is comparable across families.

    All new knobs default to values that degrade gracefully: passing
    ``core_target=0`` + ``seed_size=0`` reduces the strategy to a pure
    symmetric maker around drift_fair.
    """

    # --- Steady-state maker quoting ---
    bid_edge: float = 3.0
    ask_edge: float = 5.0
    quote_size: int = 5
    # Inventory-skew: as position grows above core_target, widen bid
    # and tighten ask. Small by default so the core idea (asymmetric
    # drift bias) dominates.
    inventory_skew_coef: float = 0.04
    # --- Position targeting ---
    core_target: int = 40
    floor: int = 0
    ceiling: int = 80
    # --- Opening acquisition ---
    seed_mode: str = "passive"
    seed_size: int = 40
    seed_window: int = 500
    # Taker fallback after this many ticks of passive seeding failed
    # to reach seed_size. 0 disables fallback.
    seed_taker_fallback_after: int = 3
    # --- Safety ---
    # If spread is tighter than this, do not post inside it (we'd be
    # giving up edge for no reason). Keep conservative.
    min_spread_for_maker: int = 4

    def __post_init__(self) -> None:
        if self.bid_edge < 0:
            raise ValueError(f"bid_edge must be >= 0 (got {self.bid_edge})")
        if self.ask_edge < 0:
            raise ValueError(f"ask_edge must be >= 0 (got {self.ask_edge})")
        if self.quote_size < 0:
            raise ValueError(f"quote_size must be >= 0 (got {self.quote_size})")
        if self.inventory_skew_coef < 0:
            raise ValueError(
                f"inventory_skew_coef must be >= 0 (got {self.inventory_skew_coef})"
            )
        if self.core_target < 0:
            raise ValueError(f"core_target must be >= 0 (got {self.core_target})")
        if self.floor < 0:
            raise ValueError(f"floor must be >= 0 (got {self.floor})")
        if self.ceiling < self.floor:
            raise ValueError(
                f"ceiling must be >= floor (got floor={self.floor}, "
                f"ceiling={self.ceiling})"
            )
        if not self.floor <= self.core_target <= self.ceiling:
            raise ValueError(
                f"core_target ({self.core_target}) must lie in "
                f"[floor={self.floor}, ceiling={self.ceiling}]"
            )
        if self.seed_mode not in SEED_MODES:
            raise ValueError(
                f"seed_mode must be one of {SEED_MODES!r} (got {self.seed_mode!r})"
            )
        if self.seed_size < 0:
            raise ValueError(f"seed_size must be >= 0 (got {self.seed_size})")
        if self.seed_size > self.ceiling:
            raise ValueError(
                f"seed_size ({self.seed_size}) must be <= ceiling ({self.ceiling})"
            )
        if self.seed_window < 0:
            raise ValueError(f"seed_window must be >= 0 (got {self.seed_window})")
        if self.seed_taker_fallback_after < 0:
            raise ValueError(
                "seed_taker_fallback_after must be >= 0 "
                f"(got {self.seed_taker_fallback_after})"
            )
        if self.min_spread_for_maker < 0:
            raise ValueError(
                f"min_spread_for_maker must be >= 0 (got {self.min_spread_for_maker})"
            )


class PepperPassiveMakerStrategy(BaseStrategy):
    """Passive maker around ``linear_drift`` with long-biased asymmetry."""

    _SEED_TICK_KEY = "passive_maker_seed_ticks"

    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
        params: PassiveMakerParams,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine
        self.params = params

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        product = context.product
        snapshot = context.snapshot
        config = context.config
        params = self.params

        fair_value: FairValueEstimate = self.fair_value_engine.estimate(
            product, snapshot, context.memory, config
        )
        fair_price = float(fair_value.price)
        effective_ceiling = min(params.ceiling, config.position_limit)

        best_bid = snapshot.best_bid
        best_ask = snapshot.best_ask
        spread = snapshot.spread
        mid = snapshot.mid if snapshot.mid is not None else fair_price

        # --- Opening phase ---
        in_opening = (
            params.seed_size > 0 and snapshot.timestamp <= params.seed_window
        )
        seed_ticks = context.memory.counters.get(self._SEED_TICK_KEY, 0)
        if in_opening:
            context.memory.counters[self._SEED_TICK_KEY] = seed_ticks + 1
        below_seed = snapshot.position < params.seed_size

        # --- Inventory-skewed edges ---
        inventory_dev = snapshot.position - params.core_target
        inv_skew = params.inventory_skew_coef * inventory_dev
        bid_edge = max(0.0, params.bid_edge + inv_skew)
        ask_edge = max(0.0, params.ask_edge - inv_skew)

        # --- Raw quote prices (anchored to drift_fair, not mid) ---
        raw_bid_px = math.floor(fair_price - bid_edge)
        raw_ask_px = math.ceil(fair_price + ask_edge)

        # --- Pull INSIDE the touch: never rest worse than best-touch±1 ---
        if best_ask is not None:
            raw_bid_px = min(raw_bid_px, best_ask.price - config.tick_size)
        if best_bid is not None:
            raw_ask_px = max(raw_ask_px, best_bid.price + config.tick_size)
        # Improve the touch: rest inside best_bid/best_ask if we'd
        # otherwise sit at the worse side.
        if best_bid is not None:
            raw_bid_px = max(raw_bid_px, best_bid.price + config.tick_size)
        if best_ask is not None:
            raw_ask_px = min(raw_ask_px, best_ask.price - config.tick_size)
        # Guard against crossing our own quotes.
        if raw_ask_px <= raw_bid_px:
            raw_bid_px = raw_ask_px - config.tick_size

        # --- Disable maker if spread is too tight to earn edge ---
        maker_enabled = spread is None or spread >= params.min_spread_for_maker

        # --- Taker eligibility ---
        # Open seed: passive-first, taker-fallback after N failed ticks.
        taker_buy_px: float | None = None
        taker_sell_px: float | None = None
        seeding_passively = (
            in_opening and below_seed and params.seed_mode == "passive"
        )
        seeding_takingly = in_opening and below_seed and (
            params.seed_mode == "taker"
            or (
                params.seed_mode == "passive"
                and seed_ticks >= params.seed_taker_fallback_after
            )
        )
        if seeding_takingly and best_ask is not None:
            # Cross any ask (match BuyAndHold semantics).
            taker_buy_px = 1e9

        # --- Quote sizes ---
        bid_size = 0
        ask_size = 0
        bid_price: int | None = None
        ask_price: int | None = None

        if maker_enabled:
            buy_capacity = effective_ceiling - snapshot.position
            sell_capacity = snapshot.position - params.floor
            qs = max(0, params.quote_size)

            # When seeding passively, bias the bid aggressively (full qs
            # to close seed gap), suppress ask.
            if seeding_passively:
                if buy_capacity > 0 and qs > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
            else:
                # Steady-state: both sides up to qs, bounded by capacity.
                if buy_capacity > 0 and qs > 0:
                    bid_price = raw_bid_px
                    bid_size = min(qs, buy_capacity)
                if sell_capacity > 0 and qs > 0:
                    # Only post ask if we are above the floor AND have
                    # drift-locked inventory to sell (don't sell into
                    # emptiness).
                    if snapshot.position > params.floor:
                        ask_price = raw_ask_px
                        ask_size = min(qs, sell_capacity)

        # --- Hard limit gates ---
        if snapshot.position >= effective_ceiling:
            bid_price = None
            bid_size = 0
            taker_buy_px = None
        if snapshot.position <= params.floor:
            ask_price = None
            ask_size = 0
            taker_sell_px = None

        # Opening: never sell while seeding.
        if in_opening and below_seed:
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
            "mid": round(mid, 4) if mid is not None else "none",
            "spread": int(spread) if spread is not None else "none",
            "bid_edge_eff": round(bid_edge, 3),
            "ask_edge_eff": round(ask_edge, 3),
            "inv_skew": round(inv_skew, 3),
            "core_target": params.core_target,
            "in_opening": in_opening,
            "below_seed": below_seed,
            "seed_ticks": seed_ticks,
            "seeding_passively": seeding_passively,
            "seeding_takingly": seeding_takingly,
            "maker_enabled": maker_enabled,
            "position": snapshot.position,
        }
        return SignalIntent(
            product=product,
            fair_value=fair_value,
            mode="hybrid",
            buy_below=taker_buy_px,
            sell_above=taker_sell_px,
            quote=quote,
            rationale="pepper_passive_maker",
            metadata=MappingProxyType(metadata),
        )

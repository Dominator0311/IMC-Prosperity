"""Rolling-IV residual taker sleeve for R3 VELVET vouchers.

Research status: diagnostic candidate, not a proven production sleeve.

The model deliberately avoids the static cross-sectional smile as the
primary fair value. On the historical tapes, per-strike rolling IV residuals
were more robust than a global smile fit, and this implementation mirrors
that simpler hypothesis:

    fair[K, t] = Black-Scholes(S_t, K, T_t, EWMA_IV[K, t-1])

It only trades core strikes where the option surface actually moves. Deep ITM
and lottery vouchers are excluded until separate evidence justifies them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.core.r3_products import POS_LIMITS, STRIKE_TO_PRODUCT, tte_live
from src.core.types import NormalizedSnapshot
from src.datamodel import Order
from src.options.bsm import BSMInputs, call_greeks, call_price, implied_vol


@dataclass(frozen=True)
class RollingIVOptionsConfig:
    traded_strikes: tuple[int, ...] = (5000, 5100, 5200, 5300, 5400, 5500)
    entry_edge: float = 0.5
    exit_edge: float = 0.10
    residual_scale: float = 4.0
    max_position: int = 120
    max_order: int = 18
    max_abs_delta: float = 80.0
    rolling_halflife: float = 40.0
    rolling_warmup: int = 40
    terminal_flatten_start: int | None = None
    iv_min: float = 0.001
    iv_max: float = 0.20


@dataclass
class RollingIVOptionsState:
    ewma_iv: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)

    def to_state(self) -> dict:
        return {
            "ewma_iv": dict(self.ewma_iv),
            "counts": dict(self.counts),
        }

    def from_state(self, blob: dict) -> None:
        if not isinstance(blob, dict):
            return
        ewma = blob.get("ewma_iv", {})
        counts = blob.get("counts", {})
        if isinstance(ewma, dict):
            self.ewma_iv = {
                str(product): float(value)
                for product, value in ewma.items()
                if _is_finite_number(value)
            }
        if isinstance(counts, dict):
            parsed: dict[str, int] = {}
            for product, value in counts.items():
                try:
                    parsed[str(product)] = int(value)
                except (TypeError, ValueError):
                    continue
            self.counts = parsed


DEFAULT_ROLLING_IV_OPTIONS_CONFIG = RollingIVOptionsConfig()


def rolling_iv_option_orders(
    *,
    velvet_snapshot: NormalizedSnapshot | None,
    option_snapshots: dict[str, NormalizedSnapshot],
    positions: dict[str, int],
    timestamp: int,
    state: RollingIVOptionsState,
    config: RollingIVOptionsConfig = DEFAULT_ROLLING_IV_OPTIONS_CONFIG,
) -> list[Order]:
    """Generate L1 taker orders from rolling-IV residuals.

    State update is part of this function: each tick trades against the
    previous EWMA IV and only then observes the current market IV.
    """
    if velvet_snapshot is None or velvet_snapshot.mid is None:
        return []

    spot = float(velvet_snapshot.mid)
    tte_days = tte_live(timestamp)
    if spot <= 0 or tte_days <= 0:
        return []

    working_positions = dict(positions)
    orders: list[Order] = []

    views = _build_option_views(
        spot=spot,
        tte_days=tte_days,
        option_snapshots=option_snapshots,
        state=state,
        config=config,
    )

    if (
        config.terminal_flatten_start is not None
        and timestamp >= config.terminal_flatten_start
    ):
        orders.extend(
            _flatten_orders(
                option_snapshots=option_snapshots,
                working_positions=working_positions,
                views=views,
                config=config,
            )
        )
        _observe_current_ivs(
            spot=spot,
            tte_days=tte_days,
            option_snapshots=option_snapshots,
            state=state,
            config=config,
        )
        return orders

    for strike in config.traded_strikes:
        product = STRIKE_TO_PRODUCT[strike]
        snapshot = option_snapshots.get(product)
        view = views.get(product)
        if snapshot is None or view is None:
            continue
        bid = snapshot.best_bid
        ask = snapshot.best_ask
        mid = snapshot.mid
        if bid is None or ask is None or mid is None:
            continue

        fair = view.fair
        signal = fair - float(mid)
        if abs(signal) <= config.exit_edge:
            target = 0
        else:
            raw_target = int(round(signal / config.residual_scale * config.max_position))
            target = max(-config.max_position, min(config.max_position, raw_target))

        current = working_positions.get(product, 0)
        desired_delta = target - current
        if desired_delta > 0:
            edge = fair - ask.price
            if edge >= config.entry_edge:
                qty = min(desired_delta, config.max_order, ask.volume)
                qty = _clip_for_position(product, qty, working_positions, config, side=1)
                qty = _clip_for_delta_cap(
                    product=product,
                    qty=qty,
                    side=1,
                    positions=working_positions,
                    views=views,
                    config=config,
                )
                if qty > 0:
                    orders.append(Order(product, ask.price, qty))
                    working_positions[product] = current + qty
        elif desired_delta < 0:
            edge = bid.price - fair
            if edge >= config.entry_edge:
                qty = min(-desired_delta, config.max_order, bid.volume)
                qty = _clip_for_position(product, qty, working_positions, config, side=-1)
                qty = _clip_for_delta_cap(
                    product=product,
                    qty=qty,
                    side=-1,
                    positions=working_positions,
                    views=views,
                    config=config,
                )
                if qty > 0:
                    orders.append(Order(product, bid.price, -qty))
                    working_positions[product] = current - qty

    _observe_current_ivs(
        spot=spot,
        tte_days=tte_days,
        option_snapshots=option_snapshots,
        state=state,
        config=config,
    )
    return orders


@dataclass(frozen=True)
class _OptionView:
    fair: float
    delta: float


def _build_option_views(
    *,
    spot: float,
    tte_days: float,
    option_snapshots: dict[str, NormalizedSnapshot],
    state: RollingIVOptionsState,
    config: RollingIVOptionsConfig,
) -> dict[str, _OptionView]:
    views: dict[str, _OptionView] = {}
    for strike in config.traded_strikes:
        product = STRIKE_TO_PRODUCT[strike]
        if state.counts.get(product, 0) < config.rolling_warmup:
            continue
        vol = state.ewma_iv.get(product)
        if vol is None or not (config.iv_min <= vol <= config.iv_max):
            continue
        snapshot = option_snapshots.get(product)
        if snapshot is None or snapshot.mid is None:
            continue
        maybe_view = _price_and_delta(spot, float(strike), tte_days, vol)
        if maybe_view is not None:
            views[product] = maybe_view
    return views


def _observe_current_ivs(
    *,
    spot: float,
    tte_days: float,
    option_snapshots: dict[str, NormalizedSnapshot],
    state: RollingIVOptionsState,
    config: RollingIVOptionsConfig,
) -> None:
    alpha = 1.0 - 0.5 ** (1.0 / config.rolling_halflife)
    for strike in config.traded_strikes:
        product = STRIKE_TO_PRODUCT[strike]
        snapshot = option_snapshots.get(product)
        if snapshot is None or snapshot.mid is None:
            continue
        iv = implied_vol(
            float(snapshot.mid),
            spot=spot,
            strike=float(strike),
            time_to_expiry=tte_days,
            lo=config.iv_min,
            hi=1.0,
        )
        if iv is None or not (config.iv_min <= iv <= config.iv_max):
            continue
        previous = state.ewma_iv.get(product)
        state.ewma_iv[product] = (
            iv if previous is None else alpha * iv + (1.0 - alpha) * previous
        )
        state.counts[product] = state.counts.get(product, 0) + 1


def _price_and_delta(
    spot: float,
    strike: float,
    tte_days: float,
    vol: float,
) -> _OptionView | None:
    try:
        inputs = BSMInputs(
            spot=spot,
            strike=strike,
            time_to_expiry=tte_days,
            volatility=vol,
        )
        fair = call_price(inputs)
        delta = call_greeks(inputs).delta
    except (ValueError, OverflowError, ZeroDivisionError):
        return None
    if not (math.isfinite(fair) and math.isfinite(delta)):
        return None
    return _OptionView(fair=fair, delta=max(0.0, min(1.0, delta)))


def _flatten_orders(
    *,
    option_snapshots: dict[str, NormalizedSnapshot],
    working_positions: dict[str, int],
    views: dict[str, _OptionView],
    config: RollingIVOptionsConfig,
) -> list[Order]:
    orders: list[Order] = []
    for strike in config.traded_strikes:
        product = STRIKE_TO_PRODUCT[strike]
        pos = working_positions.get(product, 0)
        if pos == 0:
            continue
        snapshot = option_snapshots.get(product)
        if snapshot is None:
            continue
        if pos > 0:
            bid = snapshot.best_bid
            if bid is None:
                continue
            qty = min(pos, config.max_order, bid.volume)
            qty = _clip_for_delta_cap(
                product=product,
                qty=qty,
                side=-1,
                positions=working_positions,
                views=views,
                config=config,
            )
            if qty > 0:
                orders.append(Order(product, bid.price, -qty))
                working_positions[product] = pos - qty
        else:
            ask = snapshot.best_ask
            if ask is None:
                continue
            qty = min(-pos, config.max_order, ask.volume)
            qty = _clip_for_delta_cap(
                product=product,
                qty=qty,
                side=1,
                positions=working_positions,
                views=views,
                config=config,
            )
            if qty > 0:
                orders.append(Order(product, ask.price, qty))
                working_positions[product] = pos + qty
    return orders


def _clip_for_position(
    product: str,
    qty: int,
    positions: dict[str, int],
    config: RollingIVOptionsConfig,
    *,
    side: int,
) -> int:
    if qty <= 0:
        return 0
    exchange_limit = POS_LIMITS.get(product, 300)
    limit = min(exchange_limit, config.max_position)
    current = positions.get(product, 0)
    if side > 0:
        return max(0, min(qty, limit - current))
    return max(0, min(qty, limit + current))


def _clip_for_delta_cap(
    *,
    product: str,
    qty: int,
    side: int,
    positions: dict[str, int],
    views: dict[str, _OptionView],
    config: RollingIVOptionsConfig,
) -> int:
    if qty <= 0:
        return 0
    current_delta = _net_delta(positions, views)
    delta_per_unit = views.get(product, _OptionView(0.0, 0.5)).delta
    for clipped in range(qty, 0, -1):
        projected = current_delta + side * clipped * delta_per_unit
        if (
            abs(projected) <= config.max_abs_delta
            or abs(projected) < abs(current_delta)
        ):
            return clipped
    return 0


def _net_delta(
    positions: dict[str, int],
    views: dict[str, _OptionView],
) -> float:
    total = 0.0
    for product, view in views.items():
        total += positions.get(product, 0) * view.delta
    return total


def _is_finite_number(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False

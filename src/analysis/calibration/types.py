"""Frozen dataclasses shared across the calibration pipeline.

Every fitted-parameter object is immutable. Callers that need to mix
fits across products or days build new container objects rather than
mutating shared state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class BookLevel:
    """One side of one level of an order book at a single tick."""

    price: int
    volume: int  # always positive (sign carried by side, not volume)


@dataclass(frozen=True)
class FactRow:
    """Per-tick, per-product joined record of FV + book + own PnL.

    Bid/ask levels are ordered best-first (best_bid is bids[0]).
    Empty levels are simply absent from the list (length-3 not enforced
    because some ticks have fewer levels visible).
    """

    timestamp: int
    product: str
    server_fv: float
    bids: tuple[BookLevel, ...]
    asks: tuple[BookLevel, ...]
    mid_price: float | None
    pnl: float


@dataclass(frozen=True)
class TradeRow:
    """One observed market trade."""

    timestamp: int
    product: str
    price: int
    quantity: int
    buyer: str | None = None
    seller: str | None = None


@dataclass(frozen=True)
class FairValueFit:
    """Fitted parameters for the latent fair-value process.

    The process model is a discrete-time Gaussian random walk:

        FV(t+1) = FV(t) + sigma * Z_{t+1},  Z_t ~ N(0, 1) i.i.d.

    ``ar1_phi`` is reported for diagnostics (chrispyroberts found a
    small negative AR(1) on tutorial returns and chose to ignore it).
    ``variance_ratio`` is computed at each horizon in ``vr_horizons``;
    values close to 1.0 confirm the random-walk assumption.
    """

    sigma: float
    mean_return: float
    n_returns: int
    ar1_phi: float
    ar1_phi_se: float
    vr_horizons: tuple[int, ...]
    variance_ratio: tuple[float, ...]
    quantization_grid: float | None  # None = continuous, else min step in FV
    fv_min: float
    fv_max: float


@dataclass(frozen=True)
class DepthBand:
    """A statistical layer of the book identified by offset from FV."""

    name: str
    side: str  # "bid" or "ask"
    offset_min: float
    offset_max: float
    presence_rate: float  # fraction of ticks where >= 1 level falls in band


@dataclass(frozen=True)
class QuoteRule:
    """A discovered quote-placement formula for one bot side.

    Formula:  price = round_fn(server_fv + shift) + offset

    where ``round_fn`` is one of {floor, ceil, round}. Returned fits
    document which formula won the brute-force search and how well it
    matched the empirical data.
    """

    bot_name: str
    side: str  # "bid" or "ask"
    round_fn: str  # "floor", "ceil", or "round"
    shift: float
    offset: int
    match_rate: float  # fraction of ticks where formula predicted observed
    n_samples: int


@dataclass(frozen=True)
class VolumeFit:
    """Discrete-uniform volume fit for a quote level."""

    bot_name: str
    side: str
    min_volume: int
    max_volume: int
    n_samples: int
    chi_squared: float  # uniformity test on observed values
    p_value_uniform: float


@dataclass(frozen=True)
class TradeArrivalFit:
    """Per-tick Bernoulli rate for trade arrivals.

    Equivalent to a Poisson with rate lambda = p for small p (< 0.1).
    Interarrival gap survival is checked against the geometric
    distribution that this Bernoulli implies.
    """

    p_active: float  # P(at least one trade this tick)
    p_buy_given_active: float
    n_ticks_total: int
    n_ticks_active: int
    n_trades_total: int
    geometric_ks_stat: float  # Kolmogorov-Smirnov vs geometric on gaps


@dataclass(frozen=True)
class TradeSizeFit:
    """Empirical categorical distribution of trade sizes."""

    side: str  # "buy" or "sell"
    sizes: tuple[int, ...]  # support
    probabilities: tuple[float, ...]  # same length as sizes
    n_samples: int


@dataclass(frozen=True)
class TradePriceLocationFit:
    """Empirical distribution of (trade_price - server_fv) per side."""

    side: str
    bin_edges: tuple[float, ...]
    counts: tuple[int, ...]
    n_samples: int


@dataclass(frozen=True)
class ProductCalibration:
    """All fits for a single product, with metadata."""

    product: str
    n_ticks: int
    fair_value: FairValueFit
    depth_bands: tuple[DepthBand, ...]
    quote_rules: tuple[QuoteRule, ...]
    volume_fits: tuple[VolumeFit, ...]
    trade_arrivals: TradeArrivalFit
    trade_sizes_buy: TradeSizeFit
    trade_sizes_sell: TradeSizeFit
    trade_locations_buy: TradePriceLocationFit
    trade_locations_sell: TradePriceLocationFit
    metadata: Mapping[str, object] = field(
        default_factory=lambda: MappingProxyType({})
    )

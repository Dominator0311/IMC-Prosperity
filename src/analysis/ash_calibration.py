# Ruff RUF001/RUF002 are suppressed at file scope because this module
# deliberately emits Unicode math notation (sigma, multiplication-sign,
# minus-sign) inside the human-readable markdown report.
# ruff: noqa: RUF001, RUF002
"""ASH Round-1 calibration & diagnostics (Phase A of the deep-dive plan).

Phase A of ``outputs/round_1/ash_deep_dive/PLAN.md``. Computes the
quantities every subsequent phase (B / C / D) relies on:

1. **OU fit of mid** — ``ds = theta*(mu - s)*dt + sigma*dW`` → exports
   theta, mu, sigma, half-life, residual RMSE per day.
2. **Fill-intensity curve** ``lambda(delta) = A * exp(-k*delta)`` from
   the market trade tape, with per-side fits.
3. **OFI → next-H-tick Delta-mid regression** (Cont-Stoikov-Talreja
   definition) per horizon in ``{1, 5, 20}``.
4. **Residual → forward-return markout curves** for
   ``{wall_mid, microprice, ewma_mid, depth_mid}``.
5. **Local-vs-official fill-mix reality check** (optional; gated on
   flag because it requires a sim run).

Emits:

- ``<out_dir>/fits.json`` — machine-readable summary (all numeric
  fits).
- ``<out_dir>/calibration_report.md`` — human-readable memo.

Pure-function design: every primitive takes explicit data in and
returns frozen dataclasses. Read-only with respect to the engine and
all live config factories.

**Research-only.** No module imported here (aside from
``src.core.types`` / ``src.core.fair_value`` / ``src.datamodel``) is
modified. Nothing in this module is imported by any shipped strategy,
live engine path, or ``round1_*`` config factory.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import math
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

import numpy as np

from src.core.config import ProductConfig
from src.core.fair_value import ESTIMATORS
from src.core.types import BookLevel, NormalizedSnapshot, ProductMemory

# --------------------------------------------------------------- constants

PRODUCT: Literal["ASH_COATED_OSMIUM"] = "ASH_COATED_OSMIUM"
TICK_CADENCE = 100  # raw-timestamp units per snapshot step
DEFAULT_DAYS: tuple[int, ...] = (-2, -1, 0)
DEFAULT_FILL_OFFSETS: tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
DEFAULT_OFI_HORIZONS: tuple[int, ...] = (1, 5, 20)
DEFAULT_MARKOUT_HORIZONS: tuple[int, ...] = (1, 5, 20, 50)
DEFAULT_FV_METHODS: tuple[str, ...] = ("wall_mid", "microprice", "ewma_mid", "depth_mid")

# Official day-0 ASH fill counts for the `Alt` variant (= C_h1_alt):
# 56 maker + 25 taker fills over 100k-tick day. See
# ``outputs/round_1/official_results/analysis/bucket_breakdown.md``:
# Alt rows for ASH_COATED_OSMIUM sum maker=16+14+15+11=56, taker=4+6+8+7=25.
OFFICIAL_ASH_MAKER_FILLS_ALT: int = 56
OFFICIAL_ASH_TAKER_FILLS_ALT: int = 25
OFFICIAL_ASH_PNL_ALT: float = 982.81

# --------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class OUParams:
    """Maximum-likelihood OU fit.

    ``theta`` is reported in units of 1/ticks (per-dt=1 even if the
    caller passed a coarser dt — the fit rescales).

    ``degenerate`` flags inputs that don't admit a sensible OU fit
    (e.g., constant series, fewer than 2 samples).
    """

    theta: float
    mu: float
    sigma: float
    half_life: float
    residual_rmse: float
    n_samples: int
    degenerate: bool = False


@dataclass(frozen=True)
class FillIntensity:
    """Poisson-exponential fit ``lambda(delta) = A * exp(-k * delta)``.

    ``fit_points`` is the raw measured ``(offset, rate)`` grid. ``r_squared``
    is the coefficient of determination of the log-linear fit.
    ``side`` is 'bid' or 'ask' (per-side fits are separately exported).
    """

    a: float
    k: float
    r_squared: float
    fit_points: tuple[tuple[float, float], ...]
    side: Literal["bid", "ask"]
    n_points: int

    @classmethod
    def from_points(
        cls,
        fit_points: Sequence[tuple[float, float]],
        *,
        side: Literal["bid", "ask"] = "bid",
    ) -> FillIntensity:
        """Convenience factory that fits an exponential to a prebuilt grid.

        Used by the unit tests and by ``fit_fill_intensity``.
        """

        pts = [(float(d), float(r)) for d, r in fit_points if r > 0.0]
        if len(pts) < 2:
            return cls(a=0.0, k=0.0, r_squared=0.0,
                       fit_points=tuple(fit_points), side=side, n_points=len(pts))
        deltas = np.array([d for d, _ in pts])
        log_rates = np.log(np.array([r for _, r in pts]))
        # log(lambda) = log(A) - k * delta → OLS in (delta, log rate).
        slope, intercept = np.polyfit(deltas, log_rates, 1)
        a = float(math.exp(float(intercept)))
        k = float(-slope)
        predicted = intercept + slope * deltas
        ss_res = float(np.sum((log_rates - predicted) ** 2))
        ss_tot = float(np.sum((log_rates - np.mean(log_rates)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return cls(a=a, k=k, r_squared=r_squared,
                   fit_points=tuple(fit_points), side=side, n_points=len(pts))


@dataclass(frozen=True)
class OFIFit:
    """Cont-Stoikov-Talreja regression at a fixed horizon H:

    ``mid[t + H] - mid[t] = slope * OFI[t] + intercept + eps``.
    """

    horizon: int
    slope: float
    intercept: float
    r_squared: float
    residual_sigma: float
    n_samples: int

    @classmethod
    def from_pairs(
        cls,
        ofi_series: Sequence[float],
        d_mid_series: Sequence[float],
        horizon: int,
    ) -> OFIFit:
        x = np.array(list(ofi_series), dtype=float)
        y = np.array(list(d_mid_series), dtype=float)
        if x.size < 2 or y.size != x.size:
            return cls(horizon=horizon, slope=0.0, intercept=0.0, r_squared=0.0,
                       residual_sigma=0.0, n_samples=int(x.size))
        design = np.column_stack([x, np.ones_like(x)])
        coef, *_ = np.linalg.lstsq(design, y, rcond=None)
        slope = float(coef[0])
        intercept = float(coef[1])
        pred = design @ coef
        residuals = y - pred
        ss_res = float(np.sum(residuals**2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        residual_sigma = float(np.sqrt(ss_res / max(x.size - 2, 1)))
        return cls(horizon=horizon, slope=slope, intercept=intercept,
                   r_squared=r_squared, residual_sigma=residual_sigma,
                   n_samples=int(x.size))


@dataclass(frozen=True)
class MarkoutCurve:
    """Residual-bucketed forward-return curve for one FV method.

    ``deciles`` entries are ``(mean_residual_in_bucket, {horizon: mean_fwd_return})``
    sorted ascending by bucket residual.
    """

    fv_method: str
    residual_sigma: float
    horizons: tuple[int, ...]
    deciles: tuple[tuple[float, Mapping[int, float]], ...]
    n_samples: int
    correlation_by_horizon: Mapping[int, float]


@dataclass(frozen=True)
class FillReality:
    """Local-vs-official fill-mix comparison for C_h1_alt on ASH.

    ``*_scale`` fields are local/official ratios. Higher-than-1 means
    the local simulator over-fires that fill type relative to the
    official day; less-than-1 means the local simulator under-fires.
    """

    local_maker_count: int
    local_taker_count: int
    local_total_pnl: float
    official_maker_count: int
    official_taker_count: int
    official_total_pnl: float
    maker_scale: float
    taker_scale: float
    pnl_scale: float


@dataclass(frozen=True)
class DaySnapshot:
    """All ASH-rooted data for one day, kept in-memory for the analysis."""

    day: int
    snapshots: tuple[NormalizedSnapshot, ...]
    mids: tuple[float, ...]
    market_trades_by_ts: Mapping[int, tuple[tuple[int, int], ...]]
    # tuple of (price, qty) per timestamp (positive qty, sign-less).


@dataclass(frozen=True)
class CalibrationReport:
    """All Phase-A outputs, bundled for JSON + markdown rendering."""

    days: tuple[int, ...]
    per_day_ou: Mapping[int, OUParams]
    fill_intensity: Mapping[int, Mapping[str, FillIntensity]]
    ofi_fits: Mapping[int, Mapping[int, OFIFit]]
    markout_curves: Mapping[int, Mapping[str, MarkoutCurve]]
    fill_reality: FillReality | None


# ----------------------------------------------------------------- loaders


def load_ash_snapshots(prices_csv: Path) -> list[NormalizedSnapshot]:
    """Parse an ``ASH_COATED_OSMIUM`` series from a Prosperity prices CSV.

    Only rows where ``product == "ASH_COATED_OSMIUM"`` become snapshots.
    Rows with missing mid or missing both sides are still emitted (with
    empty tuples) so the consumer can decide per-snapshot what to skip.
    """

    out: list[NormalizedSnapshot] = []
    with prices_csv.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            if row["product"] != PRODUCT:
                continue
            ts = int(row["timestamp"])
            bids = _parse_side(row, prefix="bid")
            asks = _parse_side(row, prefix="ask")
            out.append(NormalizedSnapshot(
                product=PRODUCT, timestamp=ts, bids=bids, asks=asks,
            ))
    return out


def load_ash_trades(trades_csv: Path) -> dict[int, list[tuple[int, int]]]:
    """Parse ASH trades from a Prosperity trades CSV.

    Returns a ``{timestamp: [(price, qty), ...]}`` map. Quantities are
    positive; side is not inferred from the blank buyer/seller fields.
    """

    out: dict[int, list[tuple[int, int]]] = {}
    if not trades_csv.exists():
        return out
    with trades_csv.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            if row.get("symbol") != PRODUCT:
                continue
            ts = int(row["timestamp"])
            price = round(float(row["price"]))
            qty = round(float(row["quantity"]))
            out.setdefault(ts, []).append((price, qty))
    return out


def load_day(day: int, *, data_dir: Path) -> DaySnapshot:
    prices = load_ash_snapshots(data_dir / f"prices_round_1_day_{day}.csv")
    trades = load_ash_trades(data_dir / f"trades_round_1_day_{day}.csv")
    mids: list[float] = []
    for snap in prices:
        m = snap.mid
        if m is not None:
            mids.append(float(m))
    trade_map: dict[int, tuple[tuple[int, int], ...]] = {
        ts: tuple(v) for ts, v in trades.items()
    }
    return DaySnapshot(
        day=day,
        snapshots=tuple(prices),
        mids=tuple(mids),
        market_trades_by_ts=MappingProxyType(trade_map),
    )


def _parse_side(row: Mapping[str, str], *, prefix: Literal["bid", "ask"]) -> tuple[BookLevel, ...]:
    out: list[BookLevel] = []
    for lvl in (1, 2, 3):
        price_s = row.get(f"{prefix}_price_{lvl}") or ""
        vol_s = row.get(f"{prefix}_volume_{lvl}") or ""
        if not price_s or not vol_s:
            continue
        try:
            price = round(float(price_s))
            volume = round(float(vol_s))
        except ValueError:
            continue
        if volume <= 0:
            continue
        out.append(BookLevel(price=price, volume=volume))
    # Bids sorted descending, asks ascending.
    out.sort(key=lambda lv: lv.price, reverse=(prefix == "bid"))
    return tuple(out)


# -------------------------------------------------------------------- fits


def fit_ou(mids: Sequence[float], *, dt: int = 1) -> OUParams:
    """Closed-form MLE for the discretised OU process.

    Uses the AR(1) connection: if ``s_{t+1} = alpha + beta * s_t + eps``
    with ``eps ~ N(0, sigma_e^2)`` then ``theta = -ln(beta) / dt``,
    ``mu = alpha / (1 - beta)``, ``sigma^2 = sigma_e^2 * 2 * theta / (1 - beta^2)``.

    Degenerate cases (constant series, n < 2) return ``degenerate=True``.
    """

    arr = np.asarray(list(mids), dtype=float)
    n = int(arr.size)
    if n < 2 or float(np.ptp(arr)) < 1e-12:
        mu = float(np.mean(arr)) if n > 0 else 0.0
        return OUParams(theta=0.0, mu=mu, sigma=0.0, half_life=float("inf"),
                        residual_rmse=0.0, n_samples=n, degenerate=True)
    x = arr[:-1]
    y = arr[1:]
    # AR(1) OLS.
    design = np.column_stack([x, np.ones_like(x)])
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    beta = float(coef[0])
    alpha = float(coef[1])
    residuals = y - (beta * x + alpha)
    sigma_e = float(np.sqrt(np.mean(residuals**2)))
    # Clamp beta into (0, 1) for a stable theta; we flag degenerate otherwise.
    if beta <= 0.0 or beta >= 1.0:
        # No mean reversion detected under the AR(1) mapping; report degenerate
        # but still emit mu estimate (sample mean).
        return OUParams(theta=0.0, mu=float(np.mean(arr)), sigma=sigma_e,
                        half_life=float("inf"),
                        residual_rmse=sigma_e, n_samples=n, degenerate=True)
    theta = -math.log(beta) / float(dt)
    mu = alpha / (1.0 - beta)
    sigma = sigma_e * math.sqrt(2.0 * theta / (1.0 - beta**2))
    half_life = math.log(2.0) / theta
    return OUParams(theta=theta, mu=mu, sigma=sigma,
                    half_life=half_life, residual_rmse=sigma_e,
                    n_samples=n, degenerate=False)


def fit_fill_intensity(
    snapshots: Sequence[NormalizedSnapshot],
    trades_by_ts: Mapping[int, Sequence[tuple[int, int]]],
    offsets: Sequence[float],
    *,
    side: Literal["bid", "ask"] = "bid",
    fair_of_snapshot: Callable[[NormalizedSnapshot], float] | None = None,
) -> FillIntensity:
    """Measure empirical fill intensity for a grid of maker offsets.

    For ``side='bid'`` (we post bids): a snapshot "would have filled" at
    offset ``delta`` if, in the interval leading up to the *next* snapshot,
    a market sell prints at price ``<= fair - delta``. For ``side='ask'``,
    a market buy prints at price ``>= fair + delta``.

    The fair reference is ``fair_of_snapshot(snapshot)`` — defaults to
    ``snapshot.mid``, falling back to the midpoint of the top-of-book
    if mid is unavailable.

    Returns a log-linear exponential fit ``lambda(delta) = A * exp(-k * delta)``.
    """

    if fair_of_snapshot is None:
        def fair_of_snapshot(s: NormalizedSnapshot) -> float:
            if s.mid is not None:
                return float(s.mid)
            if s.best_bid is not None and s.best_ask is not None:
                return (s.best_bid.price + s.best_ask.price) / 2.0
            return 0.0
    n_valid = 0
    fill_counts: dict[float, int] = {d: 0 for d in offsets}
    for i, snap in enumerate(snapshots):
        fair = fair_of_snapshot(snap)
        if fair <= 0.0:
            continue
        trades = trades_by_ts.get(snap.timestamp, ())
        if i + 1 < len(snapshots):
            trades_next = trades_by_ts.get(snapshots[i + 1].timestamp, ())
            trades = tuple(trades) + tuple(trades_next)
        n_valid += 1
        for d in offsets:
            threshold = fair - d if side == "bid" else fair + d
            if side == "bid":
                for price, _qty in trades:
                    if price <= threshold:
                        fill_counts[d] += 1
                        break  # at most one "would have filled" event per snapshot
            else:
                for price, _qty in trades:
                    if price >= threshold:
                        fill_counts[d] += 1
                        break
    fit_points: list[tuple[float, float]] = []
    for d in offsets:
        rate = fill_counts[d] / n_valid if n_valid > 0 else 0.0
        fit_points.append((float(d), float(rate)))
    return FillIntensity.from_points(fit_points, side=side)


def fit_ofi_signal(
    snapshots: Sequence[NormalizedSnapshot],
    horizons: Sequence[int] = DEFAULT_OFI_HORIZONS,
) -> dict[int, OFIFit]:
    """Per-horizon OFI regression on the sequence of snapshots.

    OFI increment definition follows Cont-Stoikov-Talreja (2010) applied
    to top-of-book only. Returns an :class:`OFIFit` per horizon.
    """

    # Build per-step (ofi, mid) pairs, skipping one-sided snapshots.
    ofi_series: list[float] = []
    mid_series: list[float] = []
    prev: tuple[int, int, int, int] | None = None
    for snap in snapshots:
        ba = _bid_ask_from_snapshot(snap)
        if ba is None:
            continue
        bid_price, bid_volume, ask_price, ask_volume = ba
        mid = (bid_price + ask_price) / 2.0
        if prev is None:
            prev = (bid_price, bid_volume, ask_price, ask_volume)
            mid_series.append(mid)
            ofi_series.append(0.0)
            continue
        prev_bid_price, prev_bid_volume, prev_ask_price, prev_ask_volume = prev
        e = _order_flow_increment(
            prev_bid_price=prev_bid_price, prev_bid_volume=prev_bid_volume,
            curr_bid_price=bid_price, curr_bid_volume=bid_volume,
            prev_ask_price=prev_ask_price, prev_ask_volume=prev_ask_volume,
            curr_ask_price=ask_price, curr_ask_volume=ask_volume,
        )
        ofi_series.append(float(e))
        mid_series.append(mid)
        prev = (bid_price, bid_volume, ask_price, ask_volume)

    out: dict[int, OFIFit] = {}
    for h in horizons:
        pairs_ofi: list[float] = []
        pairs_dmid: list[float] = []
        for i in range(len(mid_series) - h):
            pairs_ofi.append(ofi_series[i])
            pairs_dmid.append(mid_series[i + h] - mid_series[i])
        out[h] = OFIFit.from_pairs(ofi_series=pairs_ofi, d_mid_series=pairs_dmid, horizon=h)
    return out


def fit_residual_markout(
    snapshots: Sequence[NormalizedSnapshot],
    future_mids_by_horizon: Mapping[int, Sequence[float]],
    fv_method: str,
    *,
    n_deciles: int = 10,
) -> MarkoutCurve:
    """Bucket residuals into ``n_deciles``; report mean forward-return per bucket.

    ``future_mids_by_horizon[h][i]`` is the mid *observed* h steps after
    snapshot ``i`` (already aligned; caller truncates the tail).

    For each snapshot we compute ``residual = fv - mid``. We bucket
    by residual decile and, per horizon, emit the mean forward-return
    ``(future_mid - current_mid)``.

    The correlation-by-horizon entry uses Pearson on the raw
    (residual, forward-return) pairs — same sign / relative magnitude
    as the dossier's −0.6 figure.
    """

    horizons = tuple(sorted(future_mids_by_horizon))
    residuals: list[float] = []
    fwd_by_horizon: dict[int, list[float]] = {h: [] for h in horizons}
    current_mids: list[float] = []
    # Maintain a rolling ProductMemory so estimators that depend on
    # history (ewma_mid, rolling_mid, weighted_mid, linear_drift) see a
    # realistic recent-mid window. Cap at 200 samples to bound memory.
    memory = ProductMemory()
    history_cap = 200
    for i, snap in enumerate(snapshots):
        m = snap.mid
        if m is None:
            continue
        r = _residual_value(snap, fv_method=fv_method, memory=memory)
        # Update memory *after* the estimator has observed the pre-step state,
        # mirroring the live engine's ordering.
        memory.recent_mids.append(float(m))
        if len(memory.recent_mids) > history_cap:
            del memory.recent_mids[: len(memory.recent_mids) - history_cap]
        if r is None:
            continue
        valid = True
        for h in horizons:
            series = future_mids_by_horizon[h]
            if i >= len(series):
                valid = False
                break
            fval = series[i]
            if not math.isfinite(fval):
                valid = False
                break
        if not valid:
            continue
        residuals.append(float(r))
        current_mids.append(float(m))
        for h in horizons:
            fwd_by_horizon[h].append(float(future_mids_by_horizon[h][i]) - float(m))

    if not residuals:
        return MarkoutCurve(
            fv_method=fv_method, residual_sigma=0.0, horizons=horizons,
            deciles=(), n_samples=0,
            correlation_by_horizon=MappingProxyType({h: 0.0 for h in horizons}),
        )

    arr = np.array(residuals)
    residual_sigma = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    # Decile assignment by quantile.
    order = np.argsort(arr)
    chunk = math.ceil(arr.size / n_deciles)
    decile_entries: list[tuple[float, Mapping[int, float]]] = []
    for d in range(n_deciles):
        idx = order[d * chunk : (d + 1) * chunk]
        if idx.size == 0:
            continue
        mean_residual = float(np.mean(arr[idx]))
        per_horizon: dict[int, float] = {}
        for h in horizons:
            fwd_arr = np.array([fwd_by_horizon[h][j] for j in idx])
            per_horizon[h] = float(np.mean(fwd_arr)) if fwd_arr.size else 0.0
        decile_entries.append((mean_residual, MappingProxyType(per_horizon)))

    correlations: dict[int, float] = {}
    for h in horizons:
        fwd = np.array(fwd_by_horizon[h])
        if fwd.size > 2 and np.std(arr) > 0 and np.std(fwd) > 0:
            correlations[h] = float(np.corrcoef(arr, fwd)[0, 1])
        else:
            correlations[h] = 0.0

    return MarkoutCurve(
        fv_method=fv_method,
        residual_sigma=residual_sigma,
        horizons=horizons,
        deciles=tuple(decile_entries),
        n_samples=int(arr.size),
        correlation_by_horizon=MappingProxyType(correlations),
    )


# ----------------------------------------------------------- helpers (pure)


def _bid_ask_from_snapshot(
    snap: NormalizedSnapshot,
) -> tuple[int, int, int, int] | None:
    """Return ``(bid_price, bid_volume, ask_price, ask_volume)`` or ``None``."""
    if snap.best_bid is None or snap.best_ask is None:
        return None
    return (
        snap.best_bid.price, snap.best_bid.volume,
        snap.best_ask.price, snap.best_ask.volume,
    )


def _order_flow_increment(
    *,
    prev_bid_price: int, prev_bid_volume: int,
    curr_bid_price: int, curr_bid_volume: int,
    prev_ask_price: int, prev_ask_volume: int,
    curr_ask_price: int, curr_ask_volume: int,
) -> int:
    """Cont-Stoikov-Talreja (2010) OFI increment for one step.

    Positive = buy-pressure; negative = sell-pressure.
    """
    if curr_bid_price > prev_bid_price:
        bid_term = curr_bid_volume
    elif curr_bid_price < prev_bid_price:
        bid_term = -prev_bid_volume
    else:
        bid_term = curr_bid_volume - prev_bid_volume

    if curr_ask_price > prev_ask_price:
        ask_term = -prev_ask_volume
    elif curr_ask_price < prev_ask_price:
        ask_term = curr_ask_volume
    else:
        ask_term = -(curr_ask_volume - prev_ask_volume)

    return int(bid_term + ask_term)


_FV_PROBE_CONFIG = ProductConfig(
    position_limit=80,
    strategy_name="market_making",
    fair_value_method="wall_mid",
    fair_value_fallbacks=("mid", "microprice"),
    anchor_price=10_000.0,
    taker_edge=0.5,
    maker_edge=1.5,
    quote_size=5,
    max_aggressive_size=10,
    inventory_skew=4.0,
    flatten_threshold=0.7,
    history_length=48,
)


def _residual_value(
    snap: NormalizedSnapshot,
    fv_method: str,
    *,
    memory: ProductMemory | None = None,
) -> float | None:
    """Compute ``residual = mid - fair`` using the named estimator.

    Uses the same sign convention as ``src/strategies/ash_target_position.py``
    and the Phase-1 dossier: positive residual = mid above fair (price
    overvalued), which standard mean-reversion dynamics predict will
    drop → negative forward return. Correlation ``corr(residual, fwd_return)``
    is therefore negative under reversion.

    Returns ``None`` if either mid or the fair estimate is unavailable.
    """
    if snap.mid is None:
        return None
    estimator = ESTIMATORS.get(fv_method)
    if estimator is None:
        raise KeyError(f"unknown estimator: {fv_method!r}")
    mem = memory if memory is not None else ProductMemory()
    est = estimator.estimate(snap, mem, _FV_PROBE_CONFIG)
    if est is None:
        return None
    return float(snap.mid) - float(est.price)


# --------------------------------------------------------- orchestration


def run_calibration(
    days: Sequence[int] = DEFAULT_DAYS,
    *,
    data_dir: Path,
    fv_methods: Sequence[str] = DEFAULT_FV_METHODS,
    fill_offsets: Sequence[float] = DEFAULT_FILL_OFFSETS,
    ofi_horizons: Sequence[int] = DEFAULT_OFI_HORIZONS,
    markout_horizons: Sequence[int] = DEFAULT_MARKOUT_HORIZONS,
    fill_reality: FillReality | None = None,
) -> CalibrationReport:
    per_day_ou: dict[int, OUParams] = {}
    fill_intensity: dict[int, dict[str, FillIntensity]] = {}
    ofi_fits: dict[int, dict[int, OFIFit]] = {}
    markout_curves: dict[int, dict[str, MarkoutCurve]] = {}
    for day in days:
        ds = load_day(day, data_dir=data_dir)
        per_day_ou[day] = fit_ou(ds.mids, dt=1)
        fill_intensity[day] = {
            "bid": fit_fill_intensity(ds.snapshots, ds.market_trades_by_ts,
                                      fill_offsets, side="bid"),
            "ask": fit_fill_intensity(ds.snapshots, ds.market_trades_by_ts,
                                      fill_offsets, side="ask"),
        }
        ofi_fits[day] = fit_ofi_signal(ds.snapshots, horizons=ofi_horizons)
        # Build future-mid series per horizon — aligned to valid mid-bearing snapshots.
        mids_arr = [float(s.mid) if s.mid is not None else float("nan") for s in ds.snapshots]
        fut_by_h: dict[int, list[float]] = {}
        for h in markout_horizons:
            fut = [
                mids_arr[i + h] if (i + h) < len(mids_arr) else float("nan")
                for i in range(len(mids_arr))
            ]
            fut_by_h[h] = fut
        day_curves: dict[str, MarkoutCurve] = {}
        for fv in fv_methods:
            day_curves[fv] = fit_residual_markout(
                ds.snapshots,
                future_mids_by_horizon={h: fut_by_h[h] for h in markout_horizons},
                fv_method=fv,
            )
        markout_curves[day] = day_curves
    return CalibrationReport(
        days=tuple(days),
        per_day_ou=MappingProxyType(per_day_ou),
        fill_intensity=MappingProxyType(
            {d: MappingProxyType(m) for d, m in fill_intensity.items()}
        ),
        ofi_fits=MappingProxyType({d: MappingProxyType(m) for d, m in ofi_fits.items()}),
        markout_curves=MappingProxyType(
            {d: MappingProxyType(m) for d, m in markout_curves.items()}
        ),
        fill_reality=fill_reality,
    )


# ------------------------------------------------ fill-reality measurement


def measure_fill_reality(*, data_dir: Path, days: Sequence[int] = DEFAULT_DAYS) -> FillReality:
    """Run C_h1_alt on 3-day local and compare ASH fills to the official day-0 figures.

    Imports are deferred to keep the module loadable without the backtest
    engine (e.g. for ``pytest`` unit runs of the synthetic fixtures).
    """

    from dataclasses import replace

    from src.backtest.replay_engine import ReplayEngine
    from src.backtest.simulator import BacktestSimulator
    from src.core.config import round1_h1_engine_config, round1_test_engine_config
    from src.trader import Trader

    # ASH leg from h1 / C_h1_alt; PEPPER leg from round1_test (buy_and_hold_80).
    ash_src = round1_h1_engine_config()
    pepper_src = round1_test_engine_config()
    products = {
        "ASH_COATED_OSMIUM": ash_src.products["ASH_COATED_OSMIUM"],
        "INTARIAN_PEPPER_ROOT": pepper_src.products["INTARIAN_PEPPER_ROOT"],
    }
    engine = replace(ash_src, products=products)

    maker = 0
    taker = 0
    total_pnl = 0.0
    for day in days:
        prices = data_dir / f"prices_round_1_day_{day}.csv"
        trades = data_dir / f"trades_round_1_day_{day}.csv"
        replay = ReplayEngine.from_files(price_paths=[prices], trade_paths=[trades])
        trader = Trader(config=engine)
        result = BacktestSimulator(trader=trader).run(replay)
        r = result.per_product.get(PRODUCT)
        if r is None:
            continue
        maker += r.maker_trade_count
        taker += r.taker_trade_count
        total_pnl += r.pnl

    # Normalize 3-day local to a per-day basis so ratios compare like-for-like.
    n_days = max(len(days), 1)
    local_maker_per_day = maker / n_days
    local_taker_per_day = taker / n_days
    local_pnl_per_day = total_pnl / n_days
    maker_scale = (
        local_maker_per_day / OFFICIAL_ASH_MAKER_FILLS_ALT
        if OFFICIAL_ASH_MAKER_FILLS_ALT > 0 else 0.0
    )
    taker_scale = (
        local_taker_per_day / OFFICIAL_ASH_TAKER_FILLS_ALT
        if OFFICIAL_ASH_TAKER_FILLS_ALT > 0 else 0.0
    )
    pnl_scale = local_pnl_per_day / OFFICIAL_ASH_PNL_ALT if OFFICIAL_ASH_PNL_ALT > 0 else 0.0
    return FillReality(
        local_maker_count=maker,
        local_taker_count=taker,
        local_total_pnl=total_pnl,
        official_maker_count=OFFICIAL_ASH_MAKER_FILLS_ALT,
        official_taker_count=OFFICIAL_ASH_TAKER_FILLS_ALT,
        official_total_pnl=OFFICIAL_ASH_PNL_ALT,
        maker_scale=maker_scale,
        taker_scale=taker_scale,
        pnl_scale=pnl_scale,
    )


# ----------------------------------------------------------------- render


def render_fits_json(report: CalibrationReport) -> str:
    return json.dumps(_report_to_jsonable(report), indent=2, sort_keys=True)


def _report_to_jsonable(report: CalibrationReport) -> Mapping[str, object]:
    def ou_to_dict(ou: OUParams) -> Mapping[str, object]:
        return dataclasses.asdict(ou)

    def fill_to_dict(fill: FillIntensity) -> Mapping[str, object]:
        return {
            "a": fill.a, "k": fill.k, "r_squared": fill.r_squared,
            "side": fill.side, "n_points": fill.n_points,
            "fit_points": [[float(d), float(r)] for d, r in fill.fit_points],
        }

    def ofi_to_dict(ofi: OFIFit) -> Mapping[str, object]:
        return dataclasses.asdict(ofi)

    def curve_to_dict(c: MarkoutCurve) -> Mapping[str, object]:
        return {
            "fv_method": c.fv_method,
            "residual_sigma": c.residual_sigma,
            "horizons": list(c.horizons),
            "n_samples": c.n_samples,
            "correlation_by_horizon": dict(c.correlation_by_horizon),
            "deciles": [
                {"residual_mid": r, "markout": dict(m)} for r, m in c.deciles
            ],
        }

    return {
        "days": list(report.days),
        "per_day_ou": {str(d): ou_to_dict(v) for d, v in report.per_day_ou.items()},
        "fill_intensity": {
            str(d): {side: fill_to_dict(v) for side, v in m.items()}
            for d, m in report.fill_intensity.items()
        },
        "ofi_fits": {
            str(d): {str(h): ofi_to_dict(v) for h, v in m.items()}
            for d, m in report.ofi_fits.items()
        },
        "markout_curves": {
            str(d): {fv: curve_to_dict(v) for fv, v in m.items()}
            for d, m in report.markout_curves.items()
        },
        "fill_reality": (
            dataclasses.asdict(report.fill_reality) if report.fill_reality else None
        ),
    }


def render_report_markdown(report: CalibrationReport) -> str:
    lines: list[str] = []
    lines.append("# Phase A — ASH calibration report")
    lines.append("")
    lines.append("Generated by `src/analysis/ash_calibration.py`. All fits are from")
    lines.append("ASH_COATED_OSMIUM rows only; PEPPER-held-at-buy_hold is irrelevant here")
    lines.append("since Phase A is data-only and does not run the simulator unless the")
    lines.append("``--measure-fill-reality`` flag is set.")
    lines.append("")

    # --- OU fit table ---
    lines.append("## 1. OU fit of ASH mid")
    lines.append("")
    lines.append("``ds = theta * (mu - s) * dt + sigma * dW`` per day. Theta reported per")
    lines.append("tick (dt=1). Half-life = ln(2) / theta. Degenerate = AR(1) coefficient")
    lines.append("outside (0, 1).")
    lines.append("")
    lines.append("| Day | θ (1/tick) | Half-life (ticks) | μ | σ (ticks) | RMSE | n | degenerate |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
    for d in report.days:
        ou = report.per_day_ou[d]
        hl = "inf" if math.isinf(ou.half_life) else f"{ou.half_life:.1f}"
        lines.append(
            f"| {d} | {ou.theta:.4f} | {hl} | {ou.mu:.2f} | "
            f"{ou.sigma:.3f} | {ou.residual_rmse:.3f} | {ou.n_samples} | "
            f"{'yes' if ou.degenerate else 'no'} |"
        )
    lines.append("")

    # --- Fill intensity ---
    lines.append("## 2. Fill-intensity curves")
    lines.append("")
    lines.append("Empirical rate of a maker quote filling given offset delta from fair")
    lines.append("(mid). Fit λ(δ) = A · exp(−k · δ). Units: fills per snapshot (dt=100).")
    lines.append("Both sides shown; bid/ask asymmetry surfaces any side-preferred flow.")
    lines.append("")
    for d in report.days:
        by_side = report.fill_intensity[d]
        lines.append(f"### Day {d}")
        lines.append("")
        lines.append("| side | A | k | R² | n | rates (offset: λ) |")
        lines.append("|---|---:|---:|---:|---:|---|")
        for side in ("bid", "ask"):
            f = by_side[side]
            rates_str = ", ".join(f"{off:.1f}:{rate:.3f}" for off, rate in f.fit_points)
            lines.append(
                f"| {side} | {f.a:.4f} | {f.k:.3f} | {f.r_squared:.3f} | "
                f"{f.n_points} | {rates_str} |"
            )
        lines.append("")

    # --- OFI fits ---
    lines.append("## 3. OFI → next-H-tick Δmid regression")
    lines.append("")
    lines.append("Cont-Stoikov-Talreja top-of-book OFI increment. Horizons in units of")
    lines.append("snapshot-steps (= 100 raw timestamps). R² quantifies the fraction of")
    lines.append("forward-move variance the OFI signal explains.")
    lines.append("")
    for d in report.days:
        lines.append(f"### Day {d}")
        lines.append("")
        lines.append("| horizon | slope | intercept | R² | residual σ | n |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for h in sorted(report.ofi_fits[d]):
            ofi_fit = report.ofi_fits[d][h]
            lines.append(
                f"| {h} | {ofi_fit.slope:.4f} | {ofi_fit.intercept:.4f} | "
                f"{ofi_fit.r_squared:.4f} | {ofi_fit.residual_sigma:.3f} | "
                f"{ofi_fit.n_samples} |"
            )
        lines.append("")

    # --- Markout curves ---
    lines.append("## 4. Residual → forward-return markouts")
    lines.append("")
    lines.append("For each fair-value method, bucket residuals (fv − mid) into deciles")
    lines.append("and measure the mean forward-mid move at each horizon. Correlation")
    lines.append("reported is raw Pearson (residual, forward-return) at each horizon;")
    lines.append("the Phase-1 dossier quotes roughly −0.6 for wall_mid / microprice /")
    lines.append("depth_mid at h=1 on day 0, so expect similar magnitudes here.")
    lines.append("")
    for d in report.days:
        lines.append(f"### Day {d}")
        lines.append("")
        for fv, curve in report.markout_curves[d].items():
            lines.append(f"**{fv}** — residual σ = {curve.residual_sigma:.3f}, "
                         f"n = {curve.n_samples}")
            corr_bits = ", ".join(
                f"h={h}:{curve.correlation_by_horizon[h]:+.3f}"
                for h in curve.horizons
            )
            lines.append(f"- corr: {corr_bits}")
            header = "| residual_mid | " + " | ".join(f"h={h}" for h in curve.horizons) + " |"
            sep = "|---:| " + " | ".join(["---:" for _ in curve.horizons]) + " |"
            lines.append(header)
            lines.append(sep)
            for r, per_h in curve.deciles:
                row = f"| {r:+.3f} | " + " | ".join(
                    f"{per_h[h]:+.3f}" for h in curve.horizons
                ) + " |"
                lines.append(row)
            lines.append("")

    # --- Fill reality ---
    lines.append("## 5. Fill-model reality check")
    lines.append("")
    if report.fill_reality is None:
        lines.append("_Not run. Re-run with `--measure-fill-reality` to populate._")
    else:
        fr = report.fill_reality
        lines.append("Ran C_h1_alt (ASH leg = h1) + buy_and_hold PEPPER over the 3 local days.")
        lines.append("Compared to the official day-0 Alt (= C_h1_alt) ASH fill mix.")
        lines.append("")
        lines.append("| | Local total (3-day) | Local per-day | Official (day 0) | Scale per-day/official |")
        lines.append("|---|---:|---:|---:|---:|")
        lines.append(
            f"| Maker fills | {fr.local_maker_count} | "
            f"{fr.local_maker_count/3:.1f} | {fr.official_maker_count} | "
            f"{fr.maker_scale:.3f}× |"
        )
        lines.append(
            f"| Taker fills | {fr.local_taker_count} | "
            f"{fr.local_taker_count/3:.1f} | {fr.official_taker_count} | "
            f"{fr.taker_scale:.3f}× |"
        )
        lines.append(
            f"| ASH PnL | {fr.local_total_pnl:+.2f} | "
            f"{fr.local_total_pnl/3:+.2f} | {fr.official_total_pnl:+.2f} | "
            f"{fr.pnl_scale:.3f}× |"
        )
        lines.append("")
        lines.append("Interpretation (per Phase-10 prior): a local/official ratio much")
        lines.append("greater than 1 on takers and much less than 1 on makers would")
        lines.append("confirm the simulator over-fires takers and under-fires makers.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------- CLI


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, nargs="+", default=list(DEFAULT_DAYS))
    p.add_argument("--fv-methods", nargs="+", default=list(DEFAULT_FV_METHODS))
    p.add_argument("--data-dir", type=Path,
                   default=Path("data/raw/round_1"))
    p.add_argument("--out", type=Path,
                   default=Path("outputs/round_1/ash_deep_dive/phase_a"))
    p.add_argument("--measure-fill-reality", action="store_true",
                   help="Run C_h1_alt on 3-day local to measure fill-model reality.")
    return p.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])
    args.out.mkdir(parents=True, exist_ok=True)

    fill_reality: FillReality | None = None
    if args.measure_fill_reality:
        print("[phase-a] running fill-reality sim (C_h1_alt, 3 days) …", file=sys.stderr)
        fill_reality = measure_fill_reality(data_dir=args.data_dir, days=args.days)

    print(f"[phase-a] loading {len(args.days)} day(s) from {args.data_dir}", file=sys.stderr)
    report = run_calibration(
        days=args.days,
        data_dir=args.data_dir,
        fv_methods=args.fv_methods,
        fill_reality=fill_reality,
    )
    fits_path = args.out / "fits.json"
    md_path = args.out / "calibration_report.md"
    fits_path.write_text(render_fits_json(report) + "\n")
    md_path.write_text(render_report_markdown(report))
    print(f"[phase-a] wrote {fits_path}", file=sys.stderr)
    print(f"[phase-a] wrote {md_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

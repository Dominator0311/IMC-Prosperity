"""Per-tick IV smile cache for R3 options.

Wraps SmileFitter + BSM to provide:
  - Per-tick update from observed voucher mid-prices
  - fair(K)  → BSM fair price for strike K
  - delta(K) → BSM delta for strike K
  - iv(K)    → fitted IV for strike K
  - is_corrupt(K) → True if book mid diverges > 2σ from model

Fit-all quadratic on core strikes {5000, 5100, 5200, 5300, 5400, 5500}.
VEV_4000 delta is always 1.0 (see EXECUTION_GUIDE pitfall #8).
Does NOT use leave-one-out residuals in production.
"""

from __future__ import annotations

import math

from src.core.r3_products import STRIKE_TO_PRODUCT, VOUCHER_STRIKES, tte_live
from src.options.bsm import BSMInputs, call_greeks, call_price, implied_vol
from src.options.smile import SmileConfig, SmileFitter

# Core strikes used for smile fitting (skip illiquid extremes)
_FIT_STRIKES: tuple[int, ...] = (5000, 5100, 5200, 5300, 5400, 5500)

# Default IV used before warmup (approx ATM IV from EDA: ~1% daily ≈ sqrt(252)*0.01)
_DEFAULT_IV: float = 0.16  # annualized; adjusted for daily vol at ~1% / day

# Corruption threshold: |book_mid - fair| > _CORRUPT_SIGMA × sigma_IV × vega
_CORRUPT_SIGMA: float = 2.0


class SmileCache:
    """Per-tick smile state. Stateful; one instance per R3 session."""

    def __init__(self, config: SmileConfig | None = None) -> None:
        self._fitter = SmileFitter(
            config=config
            or SmileConfig(
                warmup_threshold=20,
                rolling_window=200,
                ewma_halflife=100.0,
            )
        )
        # Most-recent results (None until first update).
        self._spot: float | None = None
        self._tte: float | None = None
        self._fair: dict[int, float] = {}
        self._delta: dict[int, float] = {4000: 1.0}  # VEV_4000 always 1.0
        self._iv: dict[int, float] = {}
        self._vega: dict[int, float] = {}

    def update(
        self,
        timestamp: int,
        spot: float,
        strike_mids: dict[int, float],
    ) -> None:
        """Feed current tick's mid-prices. Fit smile. Recompute cache.

        ``strike_mids`` maps strike → observed voucher mid-price.
        Missing strikes are skipped (no fill on that tick).
        """
        if spot <= 0:
            return

        tte = tte_live(timestamp)
        self._spot = spot
        self._tte = tte

        # 1. Convert mid-prices to IV and feed the fitter (fit-all only).
        for k in _FIT_STRIKES:
            mid = strike_mids.get(k)
            if mid is None or mid <= 0:
                continue
            intrinsic = max(spot - k, 0.0)
            extrinsic = mid - intrinsic
            if extrinsic <= 0.01:
                continue  # effectively at intrinsic; IV solver unstable
            try:
                iv = implied_vol(
                    mid,
                    spot=spot,
                    strike=float(k),
                    time_to_expiry=tte,
                )
            except (ValueError, RuntimeError, ZeroDivisionError):
                continue
            if iv is not None:
                self._fitter.observe(float(k), iv)

        # 2. Recompute fair / delta / vega for every strike.
        for k in VOUCHER_STRIKES:
            if k == 4000:
                # delta=1.0 always; price tracks intrinsic
                self._delta[k] = 1.0
                self._fair[k] = max(spot - k, 0.0)
                self._iv[k] = float("nan")
                continue

            iv = self._fitter.fair_iv(
                strike=float(k), spot=spot, time_to_expiry=tte
            )
            if iv is None or iv <= 0:
                # Warmup: fall back to default IV
                iv = _DEFAULT_IV

            try:
                inputs = BSMInputs(
                    spot=spot,
                    strike=float(k),
                    time_to_expiry=tte,
                    volatility=iv,
                )
                fair = call_price(inputs)
                greeks = call_greeks(inputs)
            except (ValueError, ZeroDivisionError):
                continue

            self._iv[k] = iv
            self._fair[k] = max(fair, max(spot - k, 0.0))  # floor at intrinsic
            self._delta[k] = max(0.0, min(1.0, greeks.delta))
            self._vega[k] = greeks.vega

    def fair(self, strike: int) -> float | None:
        return self._fair.get(strike)

    def delta(self, strike: int) -> float | None:
        return self._delta.get(strike)

    def iv(self, strike: int) -> float | None:
        return self._iv.get(strike)

    def is_corrupt(self, strike: int, book_mid: float | None) -> bool:
        """Return True if book mid diverges > 2σ from model fair.

        Used as a quoting guard: do not quote if model and book disagree
        strongly (possible microstructure breakdown or expiry).
        """
        if book_mid is None:
            return False
        fair = self._fair.get(strike)
        if fair is None:
            return False
        iv = self._iv.get(strike)
        vega = self._vega.get(strike)
        if iv is None or vega is None or vega == 0:
            return False
        sigma_iv = iv * _CORRUPT_SIGMA
        threshold = sigma_iv * vega
        return abs(book_mid - fair) > max(threshold, 2.0)  # min 2-tick band

    def snapshot(self) -> dict:
        return {
            "fitter": self._fitter.snapshot(),
            "spot": self._spot,
            "tte": self._tte,
        }

    def restore(self, blob: dict) -> None:
        if not blob:
            return
        fitter_blob = blob.get("fitter")
        if fitter_blob:
            self._fitter = SmileFitter.restore(fitter_blob)
        self._spot = blob.get("spot")
        self._tte = blob.get("tte")

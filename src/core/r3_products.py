"""R3 product constants, position limits, and time-to-expiry helper.

These are the only product-specific constants that belong in the live
submission bundle. Everything else (EDA notes, calibration results,
replay utilities) lives outside the live path.
"""

from __future__ import annotations

# ----------------------------------------------------------------- symbols

HYDROGEL_PACK: str = "HYDROGEL_PACK"
VELVETFRUIT_EXTRACT: str = "VELVETFRUIT_EXTRACT"

VOUCHER_STRIKES: tuple[int, ...] = (
    4000, 4500, 5000, 5100, 5200, 5300, 5400, 5500, 6000, 6500,
)

VOUCHER_PRODUCTS: tuple[str, ...] = tuple(
    f"VELVET_VOUCHER_{k}" for k in VOUCHER_STRIKES
)

# R3 data/position reference names (as they appear in the CSV and
# Prosperity TradingState). Vouchers are named VEV_<strike>.
VEV_PRODUCTS: tuple[str, ...] = tuple(f"VEV_{k}" for k in VOUCHER_STRIKES)

# Convenience map: strike → product symbol
STRIKE_TO_PRODUCT: dict[int, str] = {k: f"VEV_{k}" for k in VOUCHER_STRIKES}
PRODUCT_TO_STRIKE: dict[str, int] = {v: k for k, v in STRIKE_TO_PRODUCT.items()}

# ---------------------------------------------------------------- limits

POS_LIMITS: dict[str, int] = {
    HYDROGEL_PACK: 200,
    VELVETFRUIT_EXTRACT: 200,
    **{f"VEV_{k}": 300 for k in VOUCHER_STRIKES},
}

ALL_R3_PRODUCTS: frozenset[str] = frozenset(POS_LIMITS)

# ---------------------------------------------------------------- TTE

# TTE at R3 *final simulation* start = 5 days.
# Timestamps run 0 → 999_900 in steps of 100.
# Each 1_000_000 ticks = 1 calendar day of simulation.
TTE_DAYS_AT_R3_START: float = 5.0
TICKS_PER_DAY: int = 1_000_000


def tte_live(timestamp: int) -> float:
    """Time to expiry in days at ``timestamp`` within R3.

    The live sim starts with TTE = 5.0 at ts = 0. Each 1_000_000
    ticks consume 1 day. Returns a positive value throughout the round;
    clipped to 1e-6 to avoid BSM singularity at expiry.
    """
    remaining = TTE_DAYS_AT_R3_START - timestamp / TICKS_PER_DAY
    return max(remaining, 1e-6)

"""R3Engine — top-level PersistableEngine for the Round 3 submission.

Owns all R3 products and orchestrates:
  A. HYDROGEL_PACK MM (Plan A)
  B. VEV_4000 synthetic MM + sub-intrinsic guard (Plans B + F)
  C. Voucher tiny-liquidity K=5400 / K=5500 (Plan C)
  D. VELVET hedge infrastructure (Plan D)
  E. Zero-bid lottery VEV_6000 / VEV_6500 (Plan E)
  H. Aggregate delta/gamma budget (Plan H)
  G. Terminal risk ramp (Plan G)
  SmileCache: per-tick IV smile fit for delta estimates + corruption guard

Signal-bus Tier-2 exploits (Plans I-L) are wired in separately and
enabled only after leave-one-day-out validation passes.

This engine is self-contained. The Trader just constructs one instance
and passes it to EngineOrchestrator.
"""

from __future__ import annotations

from src.core.primitives.engine_orchestrator import EngineStepResult
from src.core.primitives.portfolio_context import PortfolioSnapshot
from src.core.primitives.r3_delta_budget import R3DeltaBudget
from src.core.primitives.smile_cache import SmileCache
from src.core.primitives.terminal_ramp import RAMP_EXEMPT_PRODUCTS
from src.core.r3_products import (
    ALL_R3_PRODUCTS,
    HYDROGEL_PACK,
    PRODUCT_TO_STRIKE,
    VELVETFRUIT_EXTRACT,
    VOUCHER_STRIKES,
)
from src.datamodel import Order

# Strategy helpers
from src.strategies.round_3.hydrogel_mm import hydrogel_orders
from src.strategies.round_3.vev_4000_mm import vev4000_orders
from src.strategies.round_3.velvet_hedge import velvet_hedge_orders
from src.strategies.round_3.voucher_liquidity import voucher_liquidity_orders
from src.strategies.round_3.voucher_short_premium import (
    voucher_short_premium_orders,
)
from src.strategies.round_3.zero_bid_lottery import (
    detect_acceptance,
    zero_bid_orders,
)

_R3_ENABLE_VEV4000: bool = False
_R3_ENABLE_VELVET_HEDGE: bool = False


class R3Engine:
    """Orchestrator engine for all R3 products.

    Implements the PersistableEngine protocol (engine_id, owned_products,
    step, to_state, from_state).
    """

    def __init__(self) -> None:
        self._delta_budget = R3DeltaBudget()
        self._smile_cache = SmileCache()
        self._tick_count: int = 0
        self._zero_bid_accepted: bool | None = None
        self._prev_positions: dict[str, int] = {}
        # EWMA of VELVET mid, used as mean-reversion fair for VELVET and VEV_4000.
        # Seed with the historical long-run mean (~5260); adapts to live drift.
        self._velvet_ewma: float = 5260.0
        # EWMA halflife (in ticks). 200 ticks = ~same as AR(1) half-life.
        # Small enough to adapt intra-round, large enough to smooth micro-noise.
        self._velvet_ewma_alpha: float = 1.0 - 0.5 ** (1.0 / 200.0)
        self._hydrogel_cycle_state: dict = {}

    # ========================================================= protocol

    @property
    def engine_id(self) -> str:
        return "r3_engine"

    @property
    def owned_products(self) -> frozenset[str]:
        return ALL_R3_PRODUCTS

    def to_state(self) -> dict:
        return {
            "tick_count": self._tick_count,
            "zero_bid_accepted": self._zero_bid_accepted,
            "delta_budget": self._delta_budget.to_state(),
            "smile_cache": self._smile_cache.snapshot(),
            "prev_positions": dict(self._prev_positions),
            "velvet_ewma": self._velvet_ewma,
            "hydrogel_cycle_state": dict(self._hydrogel_cycle_state),
        }

    def from_state(self, blob: dict) -> None:
        if not blob:
            return
        try:
            self._tick_count = int(blob.get("tick_count", 0))
            accepted = blob.get("zero_bid_accepted")
            self._zero_bid_accepted = (
                bool(accepted) if accepted is not None else None
            )
            db_blob = blob.get("delta_budget", {})
            if db_blob:
                self._delta_budget.from_state(db_blob)
            sc_blob = blob.get("smile_cache", {})
            if sc_blob:
                self._smile_cache.restore(sc_blob)
            prev = blob.get("prev_positions", {})
            if isinstance(prev, dict):
                self._prev_positions = {str(k): int(v) for k, v in prev.items()}
            velvet_ewma = blob.get("velvet_ewma")
            if velvet_ewma is not None:
                self._velvet_ewma = float(velvet_ewma)
            hydrogel_cycle_state = blob.get("hydrogel_cycle_state", {})
            if isinstance(hydrogel_cycle_state, dict):
                self._hydrogel_cycle_state = dict(hydrogel_cycle_state)
        except (TypeError, ValueError, KeyError):
            pass  # cold-start on corruption

    # ========================================================= step

    def step(
        self,
        portfolio: PortfolioSnapshot,
        *,
        current_tick: int,
    ) -> EngineStepResult:
        """Emit orders for all R3 products for this tick."""
        ts = current_tick

        # ---- 0. Read snapshots and positions ----
        hydrogel_snap = portfolio.for_product(HYDROGEL_PACK)
        velvet_snap = portfolio.for_product(VELVETFRUIT_EXTRACT)
        vev4000_snap = portfolio.for_product("VEV_4000")

        positions: dict[str, int] = {
            p: portfolio.position_of(p) for p in ALL_R3_PRODUCTS
        }

        # ---- 1. Update smile cache + VELVET EWMA ----
        if velvet_snap is not None and velvet_snap.mid is not None:
            spot = float(velvet_snap.mid)
            strike_mids: dict[int, float] = {}
            for k in VOUCHER_STRIKES:
                vs = portfolio.for_product(f"VEV_{k}")
                if vs is not None and vs.mid is not None:
                    strike_mids[k] = float(vs.mid)
            self._smile_cache.update(ts, spot, strike_mids)

            # Push smile deltas into delta budget
            for k in VOUCHER_STRIKES:
                d = self._smile_cache.delta(k)
                if d is not None:
                    self._delta_budget.set_strike_delta(k, d)

            # Update rolling VELVET EWMA (used as mean-reversion fair for
            # VELVET and VEV_4000).
            a = self._velvet_ewma_alpha
            self._velvet_ewma = a * spot + (1.0 - a) * self._velvet_ewma
        else:
            spot = None

        # ---- 2. Collect intended orders from each strategy ----
        intended: list[Order] = []

        # A. HYDROGEL MM
        if hydrogel_snap is not None:
            hydrogel_pos = positions.get(HYDROGEL_PACK, 0)
            intended.extend(
                hydrogel_orders(
                    hydrogel_snap,
                    hydrogel_pos,
                    ts,
                    cycle_state=self._hydrogel_cycle_state,
                )
            )

        # B. VEV_4000 mean-reversion MM (fair = VELVET_ewma − 4000 + buffer)
        # Disabled for the HYDROGEL isolation candidate. Official 413315 had
        # VEV_4000 at -1.64k while HYDROGEL carried the run.
        if _R3_ENABLE_VEV4000 and vev4000_snap is not None and velvet_snap is not None:
            vev4000_pos = positions.get("VEV_4000", 0)
            delta_remaining = self._delta_budget.remaining_capacity(
                ts, positions, spot
            )
            intended.extend(
                vev4000_orders(
                    vev4000_snap,
                    velvet_snap,
                    vev4000_pos,
                    ts,
                    delta_remaining=delta_remaining,
                    velvet_mean=self._velvet_ewma,
                )
            )

        # C. Voucher passive liquidity — DISABLED.
        # Submission 381248 showed voucher_liquidity BIDS on K=5300/5400/5500
        # were filling and COVERING our short-premium shorts, destroying the
        # edge. These two strategies can't coexist on the same strikes.
        # Short-premium wins (higher EV per dollar of risk) — keep it alone.
        # Code retained below for potential re-enablement on orthogonal strikes.
        pass  # voucher_liquidity not called

        # C2. Voucher SHORT-PREMIUM — DISABLED.
        # Submission 381639 confirmed Prosperity marks positions at CLOSE_MID
        # (not intrinsic). OTM vouchers barely decay over 1K ticks, so the
        # short-hold-to-end strategy earns <$200 total. Not worth the
        # directional risk. Code retained in file for historical reference.

        # D. VELVET mean-reversion + hedge (fair = VELVET_ewma with delta skew)
        # Disabled with VEV_4000 so the next upload measures HYDROGEL alone.
        if _R3_ENABLE_VELVET_HEDGE and velvet_snap is not None:
            velvet_pos = positions.get(VELVETFRUIT_EXTRACT, 0)
            net_delta = self._delta_budget.net_delta(positions, spot)
            intended.extend(
                velvet_hedge_orders(
                    velvet_snap,
                    velvet_pos,
                    net_delta,
                    ts,
                    rolling_mean=self._velvet_ewma,
                )
            )

        # E. Zero-bid lottery (exempt from delta budget — no delta)
        lottery_orders = zero_bid_orders(
            self._tick_count,
            positions,
            self._zero_bid_accepted,
        )
        # We add lottery orders directly (bypass delta budget — 0-cost, no delta)
        lottery_set = {o.symbol for o in lottery_orders}

        # ---- 3. Enforce aggregate delta budget ----
        # Delta budget only applies to non-lottery orders
        non_lottery = [o for o in intended if o.symbol not in lottery_set]
        safe_orders = self._delta_budget.enforce(
            non_lottery, ts, positions, spot
        )
        all_orders = safe_orders + lottery_orders

        # ---- 4. Update acceptance probe ----
        if self._zero_bid_accepted is None and self._tick_count >= 1:
            self._zero_bid_accepted = detect_acceptance(
                self._tick_count,
                {},  # order results not directly available here
                self._prev_positions,
                positions,
            )

        self._prev_positions = dict(positions)
        self._tick_count += 1

        return EngineStepResult(orders=all_orders)

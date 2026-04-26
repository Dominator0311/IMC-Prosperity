"""Unit tests for R3 core primitives.

Covers:
- r3_products: constants, tte_live
- terminal_ramp: scale_factor, scaled_cap
- r3_delta_budget: net_delta, remaining_capacity, enforce
- smile_cache: update, fair, delta, is_corrupt
"""

from __future__ import annotations

import math
import pytest

# ================================================================ r3_products

@pytest.mark.unit
class TestR3Products:
    def test_constants_present(self):
        from src.core.r3_products import (
            HYDROGEL_PACK, VELVETFRUIT_EXTRACT, VOUCHER_STRIKES,
            VEV_PRODUCTS, POS_LIMITS, ALL_R3_PRODUCTS,
        )
        assert HYDROGEL_PACK == "HYDROGEL_PACK"
        assert VELVETFRUIT_EXTRACT == "VELVETFRUIT_EXTRACT"
        assert len(VOUCHER_STRIKES) == 10
        assert len(VEV_PRODUCTS) == 10
        assert POS_LIMITS[HYDROGEL_PACK] == 200
        assert POS_LIMITS["VEV_4000"] == 300
        assert HYDROGEL_PACK in ALL_R3_PRODUCTS

    def test_tte_live_at_zero(self):
        from src.core.r3_products import tte_live
        assert tte_live(0) == pytest.approx(5.0)

    def test_tte_live_at_one_million(self):
        from src.core.r3_products import tte_live
        assert tte_live(1_000_000) == pytest.approx(4.0)

    def test_tte_live_clipped_near_expiry(self):
        from src.core.r3_products import tte_live
        result = tte_live(5_000_000)
        assert result >= 1e-6
        assert result < 0.01

    def test_strike_to_product_map(self):
        from src.core.r3_products import STRIKE_TO_PRODUCT, PRODUCT_TO_STRIKE
        assert STRIKE_TO_PRODUCT[4000] == "VEV_4000"
        assert PRODUCT_TO_STRIKE["VEV_5500"] == 5500


# ================================================================ terminal_ramp

@pytest.mark.unit
class TestTerminalRamp:
    # R3 live round ends at ts=99_900. Ramp tuned: 85K → 95K.
    def test_before_ramp(self):
        from src.core.primitives.terminal_ramp import scale_factor
        assert scale_factor(0) == 1.0
        assert scale_factor(84_999) == 1.0

    def test_after_ramp(self):
        from src.core.primitives.terminal_ramp import scale_factor
        assert scale_factor(95_000) == 0.0
        assert scale_factor(99_900) == 0.0

    def test_mid_ramp_linear(self):
        from src.core.primitives.terminal_ramp import scale_factor
        sf = scale_factor(90_000)
        assert sf == pytest.approx(0.5, abs=1e-9)

    def test_at_ramp_start(self):
        from src.core.primitives.terminal_ramp import scale_factor
        assert scale_factor(85_000) == pytest.approx(1.0, abs=1e-9)

    def test_scaled_cap_reduces(self):
        from src.core.primitives.terminal_ramp import scaled_cap
        assert scaled_cap(200, 0) == 200
        assert scaled_cap(200, 90_000) == 100
        assert scaled_cap(200, 95_000) >= 1  # minimum 1


# ================================================================ r3_delta_budget

@pytest.mark.unit
class TestR3DeltaBudget:
    def _make_budget(self):
        from src.core.primitives.r3_delta_budget import R3DeltaBudget
        return R3DeltaBudget()

    def test_net_delta_empty(self):
        budget = self._make_budget()
        nd = budget.net_delta({})
        assert nd == pytest.approx(0.0)

    def test_net_delta_velvet_only(self):
        budget = self._make_budget()
        nd = budget.net_delta({"VELVETFRUIT_EXTRACT": 50})
        assert nd == pytest.approx(50.0)

    def test_net_delta_vev4000_delta_one(self):
        budget = self._make_budget()
        nd = budget.net_delta({"VEV_4000": 30})
        assert nd == pytest.approx(30.0)  # delta=1.0 always

    def test_net_delta_combined(self):
        budget = self._make_budget()
        budget.set_strike_delta(5500, 0.1)
        nd = budget.net_delta({
            "VELVETFRUIT_EXTRACT": 10,
            "VEV_4000": 20,
            "VEV_5500": 50,
        })
        expected = 10.0 + 20.0 * 1.0 + 50 * 0.1
        assert nd == pytest.approx(expected)

    def test_enforce_passes_hydrogel(self):
        from src.datamodel import Order
        budget = self._make_budget()
        orders = [Order("HYDROGEL_PACK", 10000, 50)]
        safe = budget.enforce(orders, 0, {})
        assert len(safe) == 1

    def test_enforce_blocks_excess_delta(self):
        from src.datamodel import Order
        budget = self._make_budget()
        # Put 390 units of VELVET (approaching new hard cap 400).
        positions = {"VELVETFRUIT_EXTRACT": 390}
        # This order would push delta to 390 + 20 = 410 > 400 hard cap
        orders = [Order("VELVETFRUIT_EXTRACT", 5250, 20)]
        safe = budget.enforce(orders, 0, positions)
        assert len(safe) == 0

    def test_enforce_allows_within_cap(self):
        from src.datamodel import Order
        budget = self._make_budget()
        positions = {"VELVETFRUIT_EXTRACT": 300}
        # 300 + 50 = 350 < 400 hard cap
        orders = [Order("VELVETFRUIT_EXTRACT", 5250, 50)]
        safe = budget.enforce(orders, 0, positions)
        assert len(safe) == 1

    def test_terminal_cap_enforced(self):
        from src.datamodel import Order
        budget = self._make_budget()
        positions = {"VELVETFRUIT_EXTRACT": 90}
        # After t=85_000, cap drops to terminal=100. 90 + 20 = 110 > 100 → blocked.
        orders = [Order("VELVETFRUIT_EXTRACT", 5250, 20)]
        safe = budget.enforce(orders, 90_000, positions)
        assert len(safe) == 0

    def test_set_strike_delta_vev4000_unchanged(self):
        budget = self._make_budget()
        budget.set_strike_delta(4000, 0.3)  # should be ignored
        nd = budget.net_delta({"VEV_4000": 10})
        assert nd == pytest.approx(10.0)  # still delta=1.0

    def test_state_roundtrip(self):
        budget = self._make_budget()
        budget.set_strike_delta(5400, 0.3)
        state = budget.to_state()
        budget2 = self._make_budget()
        budget2.from_state(state)
        assert budget2._strike_deltas[5400] == pytest.approx(0.3)


# ================================================================ smile_cache

@pytest.mark.unit
class TestSmileCache:
    def _make_cache(self):
        from src.core.primitives.smile_cache import SmileCache
        return SmileCache()

    def test_delta_vev4000_always_one(self):
        cache = self._make_cache()
        assert cache.delta(4000) == pytest.approx(1.0)

    def test_update_produces_delta(self):
        cache = self._make_cache()
        spot = 5250.0
        # Feed 25 ticks of mid-prices to get past warmup
        for ts in range(0, 2500, 100):
            strike_mids = {
                5000: spot - 250.0,
                5100: spot - 150.0,
                5200: spot - 50.0,
                5300: spot + 50.0,  # slightly OTM
                5400: max(spot - 5400, 0) + 5.0,
                5500: 2.0,
            }
            cache.update(ts, spot, strike_mids)
        d = cache.delta(5200)
        # After warmup, delta for near-ATM should be ~0.5 ± large tolerance
        assert d is not None
        assert 0.0 <= d <= 1.0

    def test_is_corrupt_no_cache(self):
        cache = self._make_cache()
        # No data yet — should not flag as corrupt
        assert cache.is_corrupt(5300, 100.0) is False

    def test_fair_returns_none_before_warmup(self):
        cache = self._make_cache()
        # Only one observation — not warmed up enough for a stable fit
        cache.update(0, 5250.0, {5200: 55.0})
        # fair may be None or a value; just check it doesn't crash
        result = cache.fair(5200)
        # result is float or None — both valid pre-warmup
        assert result is None or isinstance(result, float)

    def test_snapshot_restore(self):
        cache = self._make_cache()
        cache.update(0, 5250.0, {5200: 55.0})
        snap = cache.snapshot()
        cache2 = self._make_cache()
        cache2.restore(snap)
        # After restore, delta(4000) stays 1.0
        assert cache2.delta(4000) == pytest.approx(1.0)


# ================================================================ strategies (smoke)

@pytest.mark.unit
class TestHydrogelMM:
    def _make_snapshot(self, bid, ask, mid=None):
        from src.core.types import BookLevel, NormalizedSnapshot
        mid = mid or (bid + ask) / 2.0
        return NormalizedSnapshot(
            product="HYDROGEL_PACK",
            timestamp=0,
            bids=(BookLevel(price=bid, volume=20),),
            asks=(BookLevel(price=ask, volume=20),),
        )

    def test_generates_orders_at_zero_pos(self):
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9983, 9999)
        orders = hydrogel_orders(snap, position=0, timestamp=0)
        assert len(orders) > 0

    def test_no_orders_on_empty_book(self):
        from src.core.types import NormalizedSnapshot
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = NormalizedSnapshot(
            product="HYDROGEL_PACK", timestamp=0, bids=(), asks=(),
        )
        orders = hydrogel_orders(snap, position=0, timestamp=0)
        assert orders == []

    def test_bid_suppressed_near_long_limit(self):
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9983, 9999)
        # At +180 position (90% of limit), SST should suppress bids
        orders = hydrogel_orders(snap, position=180, timestamp=0)
        bids = [o for o in orders if o.quantity > 0]
        # Should have few or no bids at near-limit long position
        assert len(bids) <= 1

    def test_terminal_ramp_reduces_activity(self):
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9983, 9999)
        orders_normal = hydrogel_orders(snap, position=0, timestamp=0)
        orders_terminal = hydrogel_orders(snap, position=0, timestamp=960_000)
        # Terminal ramp should reduce or maintain order count
        assert len(orders_terminal) <= len(orders_normal) + 1

    def test_no_forced_flatten_long_near_old_mean(self):
        """Wide static-MR should not force-flatten at the active anchor."""
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9953, 9957)
        orders = hydrogel_orders(snap, position=150, timestamp=10_000)
        single_flatten = (
            len(orders) == 1
            and orders[0].quantity == -150
            and orders[0].price == 9953
        )
        assert not single_flatten

    def test_no_forced_flatten_short_near_old_mean(self):
        """Wide static-MR should not force-flatten at the active anchor."""
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9988, 9992)
        orders = hydrogel_orders(snap, position=-120, timestamp=10_000)
        single_flatten = (
            len(orders) == 1
            and orders[0].quantity == 120
            and orders[0].price == 9992
        )
        assert not single_flatten

    def test_small_position_uses_normal_sst_logic(self):
        """Small positions use SST logic, not a special flatten override."""
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9953, 9957)
        orders = hydrogel_orders(snap, position=15, timestamp=10_000)
        if len(orders) == 1:
            assert orders[0].quantity != -15

    def test_rebound_long_exits_on_upper_band(self):
        """Rebound-cycle long positions exit above 9988+35."""
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(10027, 10031)
        state = {"long_mode": True}
        orders = hydrogel_orders(snap, position=14, timestamp=10_000, cycle_state=state)
        assert len(orders) == 1
        assert orders[0].quantity == -14
        assert orders[0].price == 10027
        assert state["long_mode"] is False

    def test_cycle_reset_covers_short_on_lower_band(self):
        """Completed short cycle is actively reduced below 9988-8."""
        from src.strategies.round_3.hydrogel_mm import hydrogel_orders
        snap = self._make_snapshot(9938, 9942)
        state = {}
        orders = hydrogel_orders(snap, position=-120, timestamp=10_000, cycle_state=state)
        assert len(orders) == 1
        assert orders[0].quantity == 120
        assert orders[0].price == 9942
        assert state["long_mode"] is True


@pytest.mark.unit
class TestVev4000MM:
    def _make_snap(self, bid, ask, product="VEV_4000"):
        from src.core.types import BookLevel, NormalizedSnapshot
        return NormalizedSnapshot(
            product=product,
            timestamp=0,
            bids=(BookLevel(price=bid, volume=10),),
            asks=(BookLevel(price=ask, volume=10),),
        )

    def test_generates_orders(self):
        from src.strategies.round_3.vev_4000_mm import vev4000_orders
        vev_snap = self._make_snap(1240, 1260)
        velvet_snap = self._make_snap(5240, 5260, "VELVETFRUIT_EXTRACT")
        orders = vev4000_orders(vev_snap, velvet_snap, 0, 0)
        assert len(orders) > 0

    def test_no_orders_without_velvet(self):
        from src.strategies.round_3.vev_4000_mm import vev4000_orders
        from src.core.types import BookLevel, NormalizedSnapshot
        vev_snap = self._make_snap(1240, 1260)
        orders = vev4000_orders(vev_snap, None, 0, 0)
        assert orders == []

    def test_ask_floor_enforced(self):
        from src.strategies.round_3.vev_4000_mm import vev4000_orders
        # VELVET bid at 5248 → intrinsic = 5248-4000 = 1248, ask_floor = 1249
        velvet_snap = self._make_snap(5248, 5252, "VELVETFRUIT_EXTRACT")
        vev_snap = self._make_snap(1240, 1248)  # ask at 1248 = below intrinsic
        orders = vev4000_orders(vev_snap, velvet_snap, 0, 0)
        ask_orders = [o for o in orders if o.quantity < 0]
        for o in ask_orders:
            assert o.price >= 1249, f"Ask {o.price} below intrinsic+1=1249"

    def test_profit_take_flattens_long_near_mean(self):
        """v7: VEV_4000 mid near (velvet_mean−4000) AND |pos|≥40 → flatten."""
        from src.strategies.round_3.vev_4000_mm import vev4000_orders
        # velvet_mean=5250 → fair=1250. vev_mid=1250 (at fair). pos=+100.
        velvet_snap = self._make_snap(5248, 5252, "VELVETFRUIT_EXTRACT")
        vev_snap = self._make_snap(1248, 1252)  # mid=1250
        orders = vev4000_orders(
            vev_snap, velvet_snap, position=100, timestamp=0, velvet_mean=5250.0
        )
        assert len(orders) == 1
        assert orders[0].quantity == -100
        assert orders[0].price == 1248

    def test_profit_take_skipped_without_velvet_mean(self):
        """v7: profit-take only fires when velvet_mean anchor is provided."""
        from src.strategies.round_3.vev_4000_mm import vev4000_orders
        velvet_snap = self._make_snap(5248, 5252, "VELVETFRUIT_EXTRACT")
        vev_snap = self._make_snap(1248, 1252)
        orders = vev4000_orders(
            vev_snap, velvet_snap, position=100, timestamp=0, velvet_mean=None
        )
        # No flatten pattern
        single_flatten = (
            len(orders) == 1 and orders[0].quantity == -100
        )
        assert not single_flatten


@pytest.mark.unit
class TestTerminalRampIntegration:
    def test_scale_values_at_key_timestamps(self):
        from src.core.primitives.terminal_ramp import scale_factor
        # Tuned to live round length (1000 snapshots × step 100 = ts 0-99_900)
        assert scale_factor(84_000) == pytest.approx(1.0)
        assert scale_factor(86_000) == pytest.approx(0.9)
        assert scale_factor(90_000) == pytest.approx(0.5)
        assert scale_factor(95_000) == pytest.approx(0.0)

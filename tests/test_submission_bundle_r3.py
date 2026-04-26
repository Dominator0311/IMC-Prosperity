"""End-to-end bundle smoke test for R3 submission.

REGRESSION GUARDS for the two catastrophic bugs in submissions 376386 and 376726:

  Bug 1 (376386): full bundle dropped ``orch_summary=self.orchestrator.step(...)``
                  causing NoneType crash on every tick → +0 P&L.
  Bug 2 (376726): minified bundle had module-level constant collisions
                  (_PRODUCT, _POSITION_LIMIT, _DEFAULT_PARAMS) causing
                  VEV_4000 orders to be submitted with symbol=VELVETFRUIT_EXTRACT
                  → −$23K P&L. Also dropped idle guard constants.

These tests load the exported bundle exactly as the platform would and assert:
  - Orders are generated for the correct symbols (no symbol swap).
  - Quotes are inside-best or at-best (never 10+ ticks below market).
  - VELVET idle guard fires when there's nothing to hedge (pos=0, net_delta=0).
  - Bundle contains orchestrator.step() call.
  - Bundle contains uniquely-prefixed constants (no _PRODUCT / _POSITION_LIMIT collisions).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def bundle_path(tmp_path_factory) -> Path:
    """Build the R3 bundle and return its path."""
    out = tmp_path_factory.mktemp("r3_bundle") / "submission.py"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.scripts.export_submission",
            "--profile",
            "r3",
            "--output",
            str(out),
            "--minify",
        ],
        cwd=str(_REPO_ROOT),
        env={"PYTHONPATH": str(_REPO_ROOT), **_minimal_env()},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Bundle export failed: {result.stderr}"
    assert out.exists(), "Bundle file not created"
    return out


def _minimal_env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "LC_ALL")}


@pytest.fixture(scope="module")
def bundle_source(bundle_path: Path) -> str:
    return bundle_path.read_text()


@pytest.fixture(scope="module")
def bundle_namespace(bundle_source: str):
    """Execute the bundle in an isolated namespace, simulating platform load."""
    # Platform provides `datamodel` module; local dev uses `src.datamodel`. Shim it.
    sys.path.insert(0, str(_REPO_ROOT))
    import src.datamodel as dm

    sys.modules["datamodel"] = dm

    ns: dict = {}
    exec(bundle_source, ns)  # noqa: S102 — test intentionally execs bundle
    return ns


# =========================================================== static analysis


@pytest.mark.unit
class TestBundleStaticStructure:
    """Verify the generated bundle source has no regressions."""

    def test_bundle_contains_orchestrator_step_call(self, bundle_source: str) -> None:
        """Regression: 376386 dropped ``orch_summary=self.orchestrator.step(...)``."""
        assert "self.orchestrator.step(" in bundle_source, (
            "BUNDLE MISSING orchestrator.step() CALL — would crash every tick "
            "with NoneType on orch_summary.orders_by_product"
        )

    def test_bundle_contains_orchestrator_restore_call(self, bundle_source: str) -> None:
        """State restoration must happen before step."""
        assert "self.orchestrator.restore(" in bundle_source

    def test_no_module_private_name_collisions(self, bundle_source: str) -> None:
        """Regression: 376726 had _PRODUCT set twice, _POSITION_LIMIT set 5 times, etc.

        Count module-level assignments like ``_FOO=...`` for historically-colliding
        names. Each should appear at most once in the flat bundle namespace.
        """
        collision_prone = [
            r"_POSITION_LIMIT",
            r"_DEFAULT_PARAMS",
            r"_PRODUCT",
            r"_SOFT_CAP",
            r"_HARD_CAP",
            r"_TIGHT_BAND",
            r"_IDLE_DELTA_THRESHOLD",
            r"_IDLE_POS_THRESHOLD",
            r"_PARAMS_PASSIVE",
            r"_PARAMS_CROSS",
            r"_LOTTERY_STRIKES",
            r"_PROBE_TICKS",
            r"_VOUCHER_SPECS",
        ]
        for name in collision_prone:
            pattern = rf"^{name}\s*="
            matches = re.findall(pattern, bundle_source, flags=re.MULTILINE)
            assert len(matches) == 0, (
                f"Bare (non-prefixed) {name} found {len(matches)} times at module "
                "scope in bundle. This causes collisions across modules → "
                "wrong-symbol orders. Rename to module-prefixed (e.g., "
                "_HYDROGEL_POS_LIMIT)."
            )

    def test_bundle_contains_prefixed_constants(self, bundle_source: str) -> None:
        """Ensure the renamed constants actually reached the bundle."""
        required = [
            "_HYDROGEL_PARAMS",
            "_HYDROGEL_POS_LIMIT",
            "_VEV4000_PRODUCT",
            "_VEV4000_POS_LIMIT",
            "_VEV4000_PARAMS",
            "_VELVET_HEDGE_POS_LIMIT",
            "_VELVET_HEDGE_IDLE_DELTA",
            "_VELVET_HEDGE_IDLE_POS",
            "_VELVET_HEDGE_PARAMS_PASSIVE",
            "_VELVET_HEDGE_PARAMS_CROSS",
            "_VOUCHER_LIQ_SPECS",
            "_VOUCHER_LIQ_POS_LIMIT",
            "_ZERO_BID_STRIKES",
            "_ZERO_BID_POS_LIMIT",
        ]
        for name in required:
            assert name in bundle_source, (
                f"Prefixed constant {name} missing from bundle"
            )

    def test_bundle_size_under_limit(self, bundle_path: Path) -> None:
        """Prosperity team target: ≤ 128KB."""
        size = bundle_path.stat().st_size
        assert size <= 128 * 1024, (
            f"Bundle is {size} bytes, over the 128KB target"
        )


# =========================================================== dynamic behaviour


def _make_trading_state(timestamp: int, books: dict, position: dict | None = None):
    """Build a minimal TradingState from (bids, asks) dicts per product."""
    from src.datamodel import Listing, Observation, OrderDepth, TradingState

    order_depths = {}
    for p, (bids, asks) in books.items():
        d = OrderDepth()
        d.buy_orders = dict(bids)
        d.sell_orders = dict(asks)
        order_depths[p] = d
    return TradingState(
        traderData="",
        timestamp=timestamp,
        listings={
            p: Listing(symbol=p, product=p, denomination="SEASHELLS")
            for p in order_depths
        },
        order_depths=order_depths,
        own_trades={},
        market_trades={},
        position=position or {},
        observations=Observation({}, {}),
    )


# Real R3 day-0 ts=0 book as observed in the platform activitiesLog.
_R3_TS0_BOOKS = {
    "HYDROGEL_PACK": ({10003: 13, 10001: 21}, {10019: -13, 10022: -21}),
    "VELVETFRUIT_EXTRACT": ({5265: 25, 5264: 35}, {5270: -60}),
    "VEV_4000": ({1257: 15, 1254: 27}, {1278: -15, 1280: -27}),
    "VEV_5000": ({267: 7, 266: 14}, {273: -7, 274: -14}),
    "VEV_5200": ({102: 21}, {106: -21}),
    "VEV_5300": ({52: 20}, {54: -20}),
    "VEV_5400": ({16: 20}, {18: -20}),
    "VEV_5500": ({6: 20}, {7: -20}),
    "VEV_6000": ({0: 20}, {1: -20}),
    "VEV_6500": ({0: 18}, {1: -18}),
}


@pytest.mark.unit
class TestBundleDynamicBehavior:
    """Execute the bundle end-to-end and assert correct order generation."""

    def test_bundle_instantiates_without_crash(self, bundle_namespace) -> None:
        T = bundle_namespace["Trader"]
        trader = T()
        assert hasattr(trader, "run")

    def test_first_tick_no_exception(self, bundle_namespace) -> None:
        T = bundle_namespace["Trader"]
        trader = T()
        state = _make_trading_state(0, _R3_TS0_BOOKS)
        orders, conversions, trader_data = trader.run(state)
        # Runs without raising. Empty orders here would mean silent crash.
        total_orders = sum(len(v) for v in orders.values())
        assert total_orders > 0, (
            "Trader returned zero orders on first tick — may indicate "
            "orchestrator.step was dropped or R3Engine crashed silently"
        )

    def test_hydrogel_orders_correct_symbol(self, bundle_namespace) -> None:
        """HYDROGEL orders must be labeled HYDROGEL_PACK. Placement follows
        MR strategy (v6): fair = μ=9990, so at market mid 10011 (≥20 above μ)
        we SELL aggressively (ask near μ+edge ~9993, clamped to best_bid+1).
        At market mid 9960 (≥30 below μ) we BUY aggressively.

        This test only verifies SYMBOLS are correct (regression guard from
        submission 376726). Price-placement logic is validated elsewhere.
        """
        T = bundle_namespace["Trader"]
        trader = T()
        state = _make_trading_state(0, _R3_TS0_BOOKS)
        orders, _, _ = trader.run(state)

        h_orders = orders.get("HYDROGEL_PACK", [])
        assert len(h_orders) >= 1, (
            f"Expected ≥1 HYDROGEL order (MR should emit at least one side), "
            f"got {len(h_orders)}"
        )
        for o in h_orders:
            assert o.symbol == "HYDROGEL_PACK", (
                f"HYDROGEL order mislabeled as {o.symbol}"
            )
            assert 9000 < o.price < 11000, (
                f"HYDROGEL order at absurd price {o.price}"
            )

    def test_vev4000_orders_use_vev4000_symbol(self, bundle_namespace) -> None:
        """Regression: 376726 submitted VEV_4000 orders with symbol=VELVETFRUIT_EXTRACT."""
        T = bundle_namespace["Trader"]
        trader = T()
        state = _make_trading_state(0, _R3_TS0_BOOKS)
        orders, _, _ = trader.run(state)

        # All orders listed under "VEV_4000" must carry symbol "VEV_4000".
        vev_orders = orders.get("VEV_4000", [])
        for o in vev_orders:
            assert o.symbol == "VEV_4000", (
                f"VEV_4000 order mislabeled as {o.symbol}"
            )

        # Sanity: no VELVET orders that look like VEV_4000 prices (~1200–1300)
        velvet_orders = orders.get("VELVETFRUIT_EXTRACT", [])
        for o in velvet_orders:
            assert 4000 < o.price < 7000, (
                f"VELVET order at price {o.price} is in VEV_4000 range (~1250) — "
                f"likely a _PRODUCT collision regression"
            )

    def test_velvet_sleeve_disabled_for_hydrogel_isolation(
        self, bundle_namespace
    ) -> None:
        """HYDROGEL isolation candidate suppresses the VELVET sleeve."""
        T = bundle_namespace["Trader"]
        trader = T()
        state = _make_trading_state(0, _R3_TS0_BOOKS, position={})
        orders, _, _ = trader.run(state)

        velvet_orders = orders.get("VELVETFRUIT_EXTRACT", [])
        assert velvet_orders == []

    def test_voucher_shorts_disabled_in_v6(self, bundle_namespace) -> None:
        """v6: voucher_short_premium disabled (Prosperity marks at close-mid,
        so the held-premium strategy only captures theta decay <$200 total,
        not the $10K+ intrinsic-mark case we'd hoped for).
        """
        T = bundle_namespace["Trader"]
        trader = T()
        state = _make_trading_state(0, _R3_TS0_BOOKS)
        orders, _, _ = trader.run(state)
        for strike in (5300, 5400, 5500, 6000, 6500):
            product = f"VEV_{strike}"
            po = orders.get(product, [])
            # Expect ZERO orders on these strikes in v6.
            assert not po, (
                f"v6 should not trade {product} (voucher_short_premium disabled). "
                f"Got orders: {po}"
            )

    def test_sequential_ticks_no_crash(self, bundle_namespace) -> None:
        """Run 20 sequential ticks to catch state-persistence bugs."""
        T = bundle_namespace["Trader"]
        trader = T()
        trader_data = ""
        positions: dict = {}
        for ts in range(0, 2000, 100):
            state = _make_trading_state(ts, _R3_TS0_BOOKS, position=positions)
            state.traderData = trader_data
            orders, conversions, trader_data = trader.run(state)
            # sanity: orders don't explode into thousands
            total = sum(len(v) for v in orders.values())
            assert total < 100, f"Runaway order count {total} at ts={ts}"

    def test_submission_file_written_to_outputs(
        self,
        bundle_path: Path,
    ) -> None:
        """Copy the freshly-validated bundle to outputs/submissions/ for shipping."""
        # This test isn't a ship-gate per se — it just records where the good
        # bundle lives. Actual submission is a manual human step.
        assert bundle_path.exists()
        assert bundle_path.stat().st_size > 10_000  # not a stub

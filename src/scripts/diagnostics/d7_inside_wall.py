"""Diagnostic D7 — Full F2 pattern (wall-mid FV + quote-inside-wall).

Faithful reproduction of the convergent mechanism observed across 8
top-team P1/P2/P3 repos on stable products: wall-mid fair value PLUS
quote-INSIDE-the-wall placement (max_amt_bid + 1 / max_amt_ask - 1).

D6 showed swapping the FV alone gives only +80 shells. This diagnostic
tests the F2 hypothesis that BOTH FV and PLACEMENT are required.

Usage:
    PYTHONPATH=. .venv/bin/python -m src.scripts.diagnostics.d7_inside_wall
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.backtest.simulator import BacktestSimulator
from src.scripts.round_2._runtime import (
    L1_ASH_LADDER_PARAMS,
    V5_MICRO_PEPPER_PARAMS,
    baseline_engine,
    load_round_2_replay,
    wrap_trader_with_v5micro_l1,
)
from src.strategies.ash_inside_wall import AshInsideWallStrategy, InsideWallParams
from src.strategies.pepper_core_long import PepperCoreLongStrategy
from src.strategies.base import BaseStrategy
from src.trader import Trader

_OUTPUT = Path("outputs/diagnostics/d7_inside_wall.md")

ASH = "ASH_COATED_OSMIUM"
PEPPER = "INTARIAN_PEPPER_ROOT"


class PerProductStrategy(BaseStrategy):
    """Route each product through a different underlying strategy."""

    def __init__(self, routes: dict[str, BaseStrategy]) -> None:
        self._routes = routes

    def generate_intent(self, context):
        strat = self._routes.get(context.product)
        if strat is None:
            from src.core.types import SignalIntent, FairValueEstimate

            return SignalIntent(
                product=context.product,
                fair_value=FairValueEstimate(price=0.0, method="none"),
                mode="idle",
            )
        return strat.generate_intent(context)


def _run_inside_wall(params: InsideWallParams) -> dict:
    replay = load_round_2_replay()
    config = baseline_engine(flush_pepper=True)
    trader = Trader(config=config)
    fve = trader.fair_value_engine
    sig = trader.signal_engine
    # ASH uses inside-wall strategy; PEPPER keeps v5_micro.
    trader.strategies["market_making"] = PerProductStrategy(
        {
            ASH: AshInsideWallStrategy(fve, sig, params),
            PEPPER: PepperCoreLongStrategy(fve, sig, V5_MICRO_PEPPER_PARAMS),
        }
    )
    result = BacktestSimulator(trader=trader).run(replay)
    per_product = {name: r.pnl for name, r in result.per_product.items()}
    return {
        "total_pnl": result.total_pnl,
        "ash_pnl": per_product.get(ASH, 0.0),
        "pep_pnl": per_product.get(PEPPER, 0.0),
        "ash_trades": result.per_product.get(ASH).trade_count if ASH in result.per_product else 0,
    }


def _run_baseline() -> dict:
    """Current shipped config (wide_w113 ladder + v5micro PEPPER)."""
    replay = load_round_2_replay()
    config = baseline_engine(flush_pepper=True)
    trader = Trader(config=config)
    wrap_trader_with_v5micro_l1(
        trader,
        pepper_params=V5_MICRO_PEPPER_PARAMS,
        ash_params=L1_ASH_LADDER_PARAMS,
    )
    result = BacktestSimulator(trader=trader).run(replay)
    per_product = {name: r.pnl for name, r in result.per_product.items()}
    return {
        "total_pnl": result.total_pnl,
        "ash_pnl": per_product.get(ASH, 0.0),
        "pep_pnl": per_product.get(PEPPER, 0.0),
        "ash_trades": result.per_product.get(ASH).trade_count if ASH in result.per_product else 0,
    }


def main() -> None:
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    print("running: baseline (wide_w113 ladder)")
    base = _run_baseline()

    # Sweep inside-wall params to find regime.
    configs = [
        ("size=10/clear=0.5/minvol=10", InsideWallParams(bid_size=10, ask_size=10, clear_threshold=0.5, min_wall_volume=10)),
        ("size=20/clear=0.5/minvol=10", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.5, min_wall_volume=10)),
        ("size=20/clear=0.7/minvol=10", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.7, min_wall_volume=10)),
        ("size=30/clear=0.7/minvol=10", InsideWallParams(bid_size=30, ask_size=30, clear_threshold=0.7, min_wall_volume=10)),
        ("size=20/clear=0.5/minvol=20", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.5, min_wall_volume=20)),
        ("size=20/clear=0.5/minvol=5", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.5, min_wall_volume=5)),
        ("size=40/clear=0.7/minvol=10", InsideWallParams(bid_size=40, ask_size=40, clear_threshold=0.7, min_wall_volume=10)),
        # Offset=0: quote AT the wall rather than inside — tests whether
        # "inside" is the critical part or just the wall anchor.
        ("offset=0/size=20/clear=0.5", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.5, inside_wall_offset=0, min_wall_volume=10)),
        ("offset=2/size=20/clear=0.5", InsideWallParams(bid_size=20, ask_size=20, clear_threshold=0.5, inside_wall_offset=2, min_wall_volume=10)),
    ]

    out: list[str] = [
        "# D7 — Full F2 Pattern: Wall-Mid + Quote-Inside-Wall",
        "",
        "Tests the convergent F2 finding: wall-mid FV + placement at "
        "`max_amt_bid + 1 / max_amt_ask - 1`, with take/clear/make flow.",
        "",
        "**Baseline (current shipped):**",
        "",
        f"- Total: {base['total_pnl']:,.0f}",
        f"- ASH: {base['ash_pnl']:,.0f}",
        f"- PEPPER: {base['pep_pnl']:,.0f}",
        f"- ASH trades: {base['ash_trades']}",
        "",
        "**Inside-wall variants:**",
        "",
        "| Variant | Total | ASH | ΔASH vs base | PEPPER | ASH trades |",
        "|---|---|---|---|---|---|",
    ]

    for label, params in configs:
        print(f"running: {label}")
        r = _run_inside_wall(params)
        d_ash = r["ash_pnl"] - base["ash_pnl"]
        out.append(
            f"| {label} | {r['total_pnl']:,.0f} | {r['ash_pnl']:,.0f} | "
            f"{d_ash:+,.0f} | {r['pep_pnl']:,.0f} | {r['ash_trades']} |"
        )

    out += [
        "",
        "## Interpretation",
        "",
        "- **Best ΔASH > 1,000:** F2 pattern is correct mechanism. Build "
        "IMC test-upload bundle from the winning params.",
        "- **Best ΔASH in [0, 500]:** marginally right direction; may need "
        "further tuning (min_wall_volume, clear_threshold, bid/ask size).",
        "- **Best ΔASH < 0:** F2 pattern doesn't translate to our setup. "
        "Re-audit: are we really using max_amt levels correctly? Is "
        "position-limit different (80 vs top-team assumption)?",
        "",
        "## Caveats",
        "",
        "- Local backtest ≠ IMC simulator (F7). A positive local ΔASH is "
        "necessary but not sufficient — must upload to IMC for truth.",
        "- We held PEPPER constant; any ΔPEPPER is incidental measurement noise.",
        "- Position-limit interactions may differ between symmetric ladder "
        "and inside-wall patterns — watch `near_limit` steps.",
    ]

    _OUTPUT.write_text("\n".join(out) + "\n")
    print(f"wrote {_OUTPUT}")


if __name__ == "__main__":
    main()

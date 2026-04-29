"""Scenario helpers for round-day sensitivity analysis.

Every crowding, hybrid, and portfolio run is scored under four
canonical scenarios instead of a single point estimate:

- ``base``        — the nominal inputs as received from the operator.
- ``optimistic``  — conditions that favour the operator's answer.
- ``pessimistic`` — conditions that work against the operator's answer.
- ``robust``      — the answer whose worst-case value across the three
                    above is largest.

This mirrors the validation protocol in
``docs/tutorial/manual_strategy_plan.md`` and the parameter-plateau
discipline the top Prosperity teams describe in their postmortems. The
point is never to ship the single "best" answer — it is to ship the
answer that still works when the assumptions miss.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.manual_rounds.nash_crowd import Bundle, CrowdCell, CrowdPayoff, solve
from src.manual_rounds.news_portfolio import NewsPayoff, PortfolioSolution, Product
from src.manual_rounds.news_portfolio import solve as solve_news
from src.manual_rounds.priors import (
    mix_priors,
    proportional_to_ratio,
    uniform_prior,
)

SCENARIO_LABELS: tuple[str, ...] = ("base", "optimistic", "pessimistic")


@dataclass(frozen=True)
class CrowdScenarioResult:
    label: str
    shares: Mapping[str, float]
    ev_per_cell: Mapping[str, float]
    best_bundle: Bundle


@dataclass(frozen=True)
class CrowdSensitivity:
    scenarios: Mapping[str, CrowdScenarioResult]
    robust_bundle: Bundle
    robust_worst_case_net_ev: float

    def to_json(self) -> dict[str, Any]:
        return {
            "scenarios": {
                label: {
                    "shares": dict(result.shares),
                    "ev_per_cell": dict(result.ev_per_cell),
                    "best_bundle": {
                        "cells": list(result.best_bundle.cells),
                        "gross_ev": result.best_bundle.gross_ev,
                        "fee": result.best_bundle.fee,
                        "net_ev": result.best_bundle.net_ev,
                    },
                }
                for label, result in self.scenarios.items()
            },
            "robust": {
                "cells": list(self.robust_bundle.cells),
                "gross_ev": self.robust_bundle.gross_ev,
                "fee": self.robust_bundle.fee,
                "net_ev": self.robust_bundle.net_ev,
                "worst_case_net_ev": self.robust_worst_case_net_ev,
            },
        }


def run_crowd_sensitivity(
    cells: Sequence[CrowdCell],
    payoff: CrowdPayoff,
    pick_fees: Sequence[float],
    max_picks: int,
    optimistic_exponent: float = 0.5,
    pessimistic_exponent: float = 3.0,
) -> CrowdSensitivity:
    """Score the crowding problem under three crowd-behaviour regimes.

    - **base** uses the logit quantal equilibrium (smart crowd).
    - **optimistic** assumes the crowd is only weakly attracted to high
      ratios (``proportional_to_ratio`` with a low exponent + uniform
      mix) — i.e. the field is diffuse and you get less dilution on
      the strong cells.
    - **pessimistic** assumes the crowd concentrates aggressively on the
      strongest multiplier-to-inhabitants ratio (high exponent).

    Robust = the bundle whose worst-case net EV across the three
    scenarios is highest. If more than one bundle ties, the one that
    is also best in the base case wins.
    """
    base_solution = solve(
        cells=cells,
        payoff=payoff,
        pick_fees=pick_fees,
        max_picks=max_picks,
        top_k=len(cells) ** max_picks,
    )
    base_shares = dict(base_solution.shares)

    uniform = uniform_prior(cells)
    optimistic_shares = mix_priors(
        [
            (0.5, proportional_to_ratio(cells, exponent=optimistic_exponent)),
            (0.5, uniform),
        ]
    )
    pessimistic_shares = proportional_to_ratio(cells, exponent=pessimistic_exponent)

    scenario_inputs = {
        "base": base_shares,
        "optimistic": optimistic_shares,
        "pessimistic": pessimistic_shares,
    }
    scenario_solutions = {
        label: solve(
            cells=cells,
            payoff=payoff,
            pick_fees=pick_fees,
            max_picks=max_picks,
            shares_override=shares,
            top_k=len(cells) ** max_picks,
        )
        for label, shares in scenario_inputs.items()
    }
    scenarios = {
        label: CrowdScenarioResult(
            label=label,
            shares=dict(sol.shares),
            ev_per_cell=dict(sol.ev_per_cell),
            best_bundle=sol.top_bundles[0],
        )
        for label, sol in scenario_solutions.items()
    }

    # Robust search: rescore every unique bundle from the base scenario's
    # top_bundles against all three crowd distributions and pick the one
    # with the best min net EV.
    candidate_bundles = scenario_solutions["base"].top_bundles
    best_worst = float("-inf")
    best_bundle: Bundle | None = None
    for bundle in candidate_bundles:
        worst = float("inf")
        for label in SCENARIO_LABELS:
            scen_shares = scenario_inputs[label]
            gross = sum(
                payoff.ev(
                    next(c for c in cells if c.name == name),
                    scen_shares[name],
                )
                for name in bundle.cells
            )
            net = gross - bundle.fee
            worst = min(worst, net)
        if worst > best_worst:
            best_worst = worst
            best_bundle = bundle
    assert best_bundle is not None  # candidate_bundles is non-empty
    return CrowdSensitivity(
        scenarios=scenarios,
        robust_bundle=best_bundle,
        robust_worst_case_net_ev=best_worst,
    )


@dataclass(frozen=True)
class NewsScenarioResult:
    label: str
    positions: Mapping[str, int]
    total_pnl: float
    binding: bool


@dataclass(frozen=True)
class NewsSensitivity:
    scenarios: Mapping[str, NewsScenarioResult]
    robust_positions: Mapping[str, int]
    robust_total_pnl: float

    def to_json(self) -> dict[str, Any]:
        return {
            "scenarios": {
                label: {
                    "positions": dict(result.positions),
                    "total_pnl": result.total_pnl,
                    "binding": result.binding,
                }
                for label, result in self.scenarios.items()
            },
            "robust": {
                "positions": dict(self.robust_positions),
                "total_pnl_at_base": self.robust_total_pnl,
            },
        }


def _shrink_returns(products: Sequence[Product], factor: float) -> list[Product]:
    return [
        Product(
            name=p.name,
            expected_return=p.expected_return * factor,
            rationale=p.rationale,
        )
        for p in products
    ]


def run_news_sensitivity(
    products: Sequence[Product],
    payoff: NewsPayoff,
    shift: float = 0.02,
    shrink_factor: float = 0.7,
) -> NewsSensitivity:
    """Score the news portfolio under three sentiment regimes.

    - **base**: use the operator's expected returns as-is.
    - **optimistic**: shift every expected return by ``+shift * sign(r)``
      so each bet is *bigger* in the direction the operator already
      wants — tests whether positions would stay stable if conviction
      was stronger.
    - **pessimistic**: shift every expected return by ``-shift * sign(r)``
      so each bet is smaller and some may flip.
    - **robust**: solve with returns shrunk by ``shrink_factor`` (< 1).
      This dampens every bet equally; the result is always a subset of
      the base positions and is the natural "hedged" answer.
    """
    if not 0 < shrink_factor <= 1:
        raise ValueError("shrink_factor must be in (0, 1]")
    base_sol = solve_news(products, payoff)
    optimistic_products = [
        Product(
            name=p.name,
            expected_return=p.expected_return + shift * (1 if p.expected_return >= 0 else -1),
            rationale=p.rationale,
        )
        for p in products
    ]
    pessimistic_products = [
        Product(
            name=p.name,
            expected_return=p.expected_return - shift * (1 if p.expected_return >= 0 else -1),
            rationale=p.rationale,
        )
        for p in products
    ]
    optimistic_sol = solve_news(optimistic_products, payoff)
    pessimistic_sol = solve_news(pessimistic_products, payoff)
    robust_sol = solve_news(_shrink_returns(products, shrink_factor), payoff)

    def _as_result(label: str, sol: PortfolioSolution) -> NewsScenarioResult:
        return NewsScenarioResult(
            label=label,
            positions=dict(sol.positions),
            total_pnl=sol.total_pnl,
            binding=sol.binding,
        )

    scenarios = {
        "base": _as_result("base", base_sol),
        "optimistic": _as_result("optimistic", optimistic_sol),
        "pessimistic": _as_result("pessimistic", pessimistic_sol),
    }
    return NewsSensitivity(
        scenarios=scenarios,
        robust_positions=dict(robust_sol.positions),
        robust_total_pnl=robust_sol.total_pnl,
    )


# Hybrid sensitivity is handled inline inside the hybrid runner because
# ``optimize_hybrid`` already returns a worst-case-robust answer natively.
# There is no value in wrapping it a second time.

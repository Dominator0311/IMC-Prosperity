"""Round-1 PEPPER candidate registry for the 5 new strategy classes.

Exposes:

- ``CANDIDATE_PARAMS``: mapping from candidate name → tuned params
  dataclass. Params are chosen from first-principles microstructure
  observations (see ``docs/round_1/pepper_new_families_rationale.md``)
  and are explicitly NOT fitted to any single day.

- ``CANDIDATE_FACTORIES``: mapping from candidate name → zero-arg
  factory returning (Strategy, params) for the PEPPER leg. Matches
  the constructor signature required by ``STRATEGY_REGISTRY`` entries
  that take ``(FairValueEngine, SignalEngine, params)``.

- ``pepper_product_config()``: shared ``ProductConfig`` for PEPPER
  that all five candidates use. ``strategy_name`` is set to
  ``"market_making"`` as a placeholder because the strategies are
  research-only (not registered in ``STRATEGY_REGISTRY``). The
  export bundle is responsible for rewiring the runtime to the
  actual strategy instance, following the ``pepper_core_long``
  inlining pattern.

- ``build_candidate_strategy()``: one-call builder used by research
  harnesses and the export pipeline. Returns
  ``(PepperStrategyInstance, params_dict_for_logging)``.

All five candidates share a consistent "no-overfit discipline":

1. Edges / windows expressed in microstructure units that transfer
   across tapes with similar spread and drift magnitudes.
2. All new knobs default to safe / inert values; every candidate is
   a small superset of the simple baseline it comes from.
3. Core position target kept ≤ 60 (not 80). Always-full-long collapses
   to buy-and-hold; leaving ≥ 20 units of headroom is what makes the
   new decision surface useful at all.
4. Reversal / safety guards use loose r² gates (≥ 0.30) — tight gates
   (≥ 0.7) made the guard inert on the real tape.
5. No parameter has a value that looks like it was micro-tuned
   (e.g. 3.17, 0.042) — all values are round, derived from observed
   structure.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from types import MappingProxyType

from src.core.config import ProductConfig
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.strategies.base import BaseStrategy
from src.strategies.pepper_drift_asymmetric import (
    DriftAsymmetricParams,
    PepperDriftAsymmetricStrategy,
)
from src.strategies.pepper_flow_overlay import (
    FlowOverlayParams,
    PepperFlowOverlayStrategy,
)
from src.strategies.pepper_imbalance_timer import (
    ImbalanceTimerParams,
    PepperImbalanceTimerStrategy,
)
from src.strategies.pepper_passive_maker import (
    PassiveMakerParams,
    PepperPassiveMakerStrategy,
)
from src.strategies.pepper_passive_opener import (
    PassiveOpenerParams,
    PepperPassiveOpenerStrategy,
)

PEPPER = "INTARIAN_PEPPER_ROOT"


def pepper_product_config() -> ProductConfig:
    """Shared PEPPER ProductConfig used by all 5 candidates.

    ``history_length=32`` matches the empirical ``linear_drift`` warm-up
    documented in the Phase-3 fair-value note. ``max_aggressive_size=20``
    allows the opening seed to fill in ~2-4 ticks; ``quote_size=5``
    matches the default maker quote size.
    """
    return ProductConfig(
        position_limit=80,
        strategy_name="market_making",  # placeholder; overridden by export bundle
        fair_value_method="linear_drift",
        fair_value_fallbacks=("depth_mid", "hybrid_wall_micro", "mid"),
        taker_edge=1.0,
        maker_edge=1.0,
        quote_size=5,
        max_aggressive_size=20,
        inventory_skew=2.0,
        flatten_threshold=0.8,
        history_length=32,
    )


# --------------------------------------------------------------------------- #
# Shipping params per candidate                                               #
# --------------------------------------------------------------------------- #

# Candidate 1 — PassiveMaker. Core: 40 long + pure inside-spread maker.
PASSIVE_MAKER_PARAMS: PassiveMakerParams = PassiveMakerParams(
    bid_edge=3.0,        # inside modal spread (13-16) by ~4 ticks
    ask_edge=5.0,        # asymmetric for + drift (long bias)
    quote_size=5,
    inventory_skew_coef=0.04,
    core_target=40,      # half the limit; leaves 40 units for cycling
    floor=0,
    ceiling=80,
    seed_mode="passive",
    seed_size=40,
    seed_window=500,
    seed_taker_fallback_after=3,
    min_spread_for_maker=4,
)


# Candidate 2 — DriftAsymmetric. Slope-scaled asymmetric maker.
DRIFT_ASYMMETRIC_PARAMS: DriftAsymmetricParams = DriftAsymmetricParams(
    base_edge=3.0,
    quote_size=5,
    slope_skew_factor=10.0,    # +0.1/tick slope → +1-tick asymmetry
    max_asymmetry=3.0,         # cap: never fully one-sided
    slope_window=32,           # matches linear_drift default
    slope_r2_min=0.30,         # loose gate — tight r² gates made guards inert
    inventory_skew_coef=0.05,
    core_target=50,
    floor=0,
    ceiling=80,
    seed_size=40,
    seed_window=500,
    reversal_slope_threshold=0.02,  # 20% of observed drift magnitude
    reversal_r2_min=0.30,
    reversal_target=0,
    min_spread_for_maker=4,
)


# Candidate 3 — ImbalanceTimer. OFI-gated adds/trims on carry core.
IMBALANCE_TIMER_PARAMS: ImbalanceTimerParams = ImbalanceTimerParams(
    add_imbalance_threshold=0.30,   # ~2:1 bid-heavy
    trim_imbalance_threshold=0.30,
    add_size=4,
    trim_size=4,
    max_add_mid_above_fair=2.0,     # only chase if price reasonable
    min_trim_mid_above_fair=2.0,    # only trim if price rich
    core_target=60,
    floor=0,
    ceiling=80,
    background_bid_edge=3.0,
    background_ask_edge=5.0,
    background_quote_size=3,
    seed_size=50,
    seed_window=500,
    min_top_depth=8,                # reject ultra-thin signal
)


# Candidate 4 — FlowOverlay. EWMA-of-aggressor-flow bias on target.
FLOW_OVERLAY_PARAMS: FlowOverlayParams = FlowOverlayParams(
    core_long=50,
    floor=0,
    ceiling=80,
    step=8,
    flow_decay=0.85,          # EWMA half-life ≈ 4.3 ticks
    flow_scale=0.5,
    flow_bias_size=20,        # 25% of position limit
    flow_min_magnitude=2.0,
    taker_edge=1.5,
    maker_bid_edge=3.0,
    maker_ask_edge=5.0,
    maker_quote_size=3,
    seed_size=40,
    seed_window=500,
    min_spread_for_maker=4,
)


# Candidate 5 — PassiveOpener. Passive-first open; drift-maker after.
PASSIVE_OPENER_PARAMS: PassiveOpenerParams = PassiveOpenerParams(
    opening_passive_window=3,         # 3 ticks passive before fallback
    opening_taker_fallback_tick=3,
    passive_bid_improve=1,            # minimum improvement
    opening_max_size_per_tick=20,
    seed_size=40,
    steady_core_target=40,
    maker_bid_edge=3.0,
    maker_ask_edge=5.0,
    maker_quote_size=5,
    inventory_skew_coef=0.04,
    floor=0,
    ceiling=80,
    min_spread_for_maker=4,
)


# --------------------------------------------------------------------------- #
# Canonical candidate registry                                                #
# --------------------------------------------------------------------------- #

CANDIDATE_PARAMS: Mapping[str, object] = MappingProxyType(
    {
        "pepper_passive_maker": PASSIVE_MAKER_PARAMS,
        "pepper_drift_asymmetric": DRIFT_ASYMMETRIC_PARAMS,
        "pepper_imbalance_timer": IMBALANCE_TIMER_PARAMS,
        "pepper_flow_overlay": FLOW_OVERLAY_PARAMS,
        "pepper_passive_opener": PASSIVE_OPENER_PARAMS,
    }
)

CandidateFactory = Callable[
    [FairValueEngine, SignalEngine], BaseStrategy
]

CANDIDATE_FACTORIES: Mapping[str, CandidateFactory] = MappingProxyType(
    {
        "pepper_passive_maker": lambda fv, sg: PepperPassiveMakerStrategy(
            fv, sg, PASSIVE_MAKER_PARAMS
        ),
        "pepper_drift_asymmetric": lambda fv, sg: PepperDriftAsymmetricStrategy(
            fv, sg, DRIFT_ASYMMETRIC_PARAMS
        ),
        "pepper_imbalance_timer": lambda fv, sg: PepperImbalanceTimerStrategy(
            fv, sg, IMBALANCE_TIMER_PARAMS
        ),
        "pepper_flow_overlay": lambda fv, sg: PepperFlowOverlayStrategy(
            fv, sg, FLOW_OVERLAY_PARAMS
        ),
        "pepper_passive_opener": lambda fv, sg: PepperPassiveOpenerStrategy(
            fv, sg, PASSIVE_OPENER_PARAMS
        ),
    }
)


def build_candidate_strategy(
    name: str,
    fair_value_engine: FairValueEngine,
    signal_engine: SignalEngine,
    overrides: Mapping[str, object] | None = None,
) -> tuple[BaseStrategy, dict[str, object]]:
    """Build a candidate strategy with optional per-run overrides.

    ``overrides`` lets a sweep harness vary one parameter without
    redefining the whole dataclass, following the ``dataclasses.replace``
    pattern used elsewhere in the repo.
    """
    if name not in CANDIDATE_PARAMS:
        raise ValueError(
            f"Unknown PEPPER candidate {name!r}; known: "
            f"{sorted(CANDIDATE_PARAMS)}"
        )
    params = CANDIDATE_PARAMS[name]
    if overrides:
        params = replace(params, **overrides)
    factories: Mapping[str, Callable[[FairValueEngine, SignalEngine, object], BaseStrategy]] = {
        "pepper_passive_maker": PepperPassiveMakerStrategy,
        "pepper_drift_asymmetric": PepperDriftAsymmetricStrategy,
        "pepper_imbalance_timer": PepperImbalanceTimerStrategy,
        "pepper_flow_overlay": PepperFlowOverlayStrategy,
        "pepper_passive_opener": PepperPassiveOpenerStrategy,
    }
    strategy = factories[name](fair_value_engine, signal_engine, params)
    return strategy, asdict(params)


__all__ = [
    "CANDIDATE_FACTORIES",
    "CANDIDATE_PARAMS",
    "DRIFT_ASYMMETRIC_PARAMS",
    "FLOW_OVERLAY_PARAMS",
    "IMBALANCE_TIMER_PARAMS",
    "PASSIVE_MAKER_PARAMS",
    "PASSIVE_OPENER_PARAMS",
    "PEPPER",
    "build_candidate_strategy",
    "pepper_product_config",
]

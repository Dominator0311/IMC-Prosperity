# How to Add a New Product

> **Scope**: Product onboarding workflow — what files to change and in
> what order. Not a tuning guide; see the phase notes for that.

Last verified against commit `d48ec48`.

Step-by-step guide for onboarding a product from a new round. Start
with the decision tree, then follow the matching path.

---

## Decision tree

```
New product arrives in the round spec
  |
  +-- Does the existing market_making strategy fit?
  |   |
  |   +-- YES, and an existing estimator works
  |   |     -> Path A: Config-only (1 file)
  |   |
  |   +-- YES, but the product needs a custom fair value estimator
  |         -> Path B: New estimator (2 files)
  |
  +-- NO, the product needs fundamentally different logic
        -> Path C: New strategy (4 files + exporter update)
```

Most new products take **Path A**. EMERALDS and TOMATOES both use the
same `market_making` strategy; they differ only by fair value method and
parameter values.

---

## Path A: Config-only (1 file)

**File to change**: `src/core/config.py`, inside `default_engine_config()`.

Add a `ProductConfig` entry to the `products` dict. Example for a
hypothetical GOLD product using the existing `mid` estimator:

```python
"GOLD": ProductConfig(
    position_limit=10,
    strategy_name="market_making",
    fair_value_method="mid",
    fair_value_fallbacks=("microprice",),
    tick_size=1,
    taker_edge=1.0,
    maker_edge=1.5,
    quote_size=3,
    max_aggressive_size=5,
    inventory_skew=2.0,
    flatten_threshold=0.75,
    history_length=32,
),
```

`ProductConfig.__post_init__()` validates at construction time:

- `strategy_name` must be in `KNOWN_STRATEGY_NAMES`
- `fair_value_method` and every entry in `fair_value_fallbacks` must be
  in `KNOWN_ESTIMATOR_NAMES`
- `anchor_price` must be set if the method or any fallback is `"anchor"`
- `ewma_alpha` must be in (0, 1] if set
- All numeric fields are range-checked

A typo in the strategy or estimator name raises `ValueError`
immediately.

**Available estimators** (defined in `src/core/fair_value.py`):
`anchor`, `mid`, `microprice`, `rolling_mid`, `weighted_mid`,
`ewma_mid`, `depth_mid`.

**Available strategies** (registered in `src/strategies/__init__.py`):
`market_making`.

---

## Path B: New estimator + existing strategy (2 files)

Use this path when the existing `market_making` strategy works but none
of the 7 built-in estimators capture the product's fair value well.

### Step 1: Create the estimator (`src/core/fair_value.py`)

Implement the `Estimator` protocol. The class needs a `name` attribute
and an `estimate` method:

```python
class VwapEstimator:
    name = "vwap"

    def estimate(
        self,
        snapshot: NormalizedSnapshot,
        memory: ProductMemory,
        config: ProductConfig,
    ) -> FairValueEstimate | None:
        # Return None if insufficient data (triggers fallback chain).
        if not snapshot.bids or not snapshot.asks:
            return None
        price = ...  # your computation
        return FairValueEstimate(price=price, method=self.name, confidence=0.7)
```

Register the instance in the `ESTIMATORS` dict at the bottom of the
same file:

```python
ESTIMATORS: Mapping[str, Estimator] = MappingProxyType(
    {
        # ...existing estimators...
        "vwap": VwapEstimator(),
    }
)
```

### Step 2: Register the name (`src/core/config.py`)

Add the estimator name to `KNOWN_ESTIMATOR_NAMES`:

```python
KNOWN_ESTIMATOR_NAMES: tuple[str, ...] = (
    "anchor",
    "depth_mid",
    "ewma_mid",
    "microprice",
    "mid",
    "rolling_mid",
    "vwap",           # <- add here (keep sorted)
    "weighted_mid",
)
```

Then add a `ProductConfig` entry using the new estimator (same as
Path A).

---

## Path C: New strategy (4 files + exporter update)

Use this path when the product requires fundamentally different logic
(e.g. arbitrage, conversion, or option pricing) that does not fit the
market-making intent model.

### Step 1: Create the strategy module (`src/strategies/<name>.py`)

Subclass `BaseStrategy` from `src/strategies/base.py`. The constructor
must accept `(fair_value_engine, signal_engine)` — this is the
`StrategyFactory` signature used by `Trader._build_strategies()`.

```python
from src.core.fair_value import FairValueEngine
from src.core.signals import SignalEngine
from src.core.types import SignalIntent
from src.strategies.base import BaseStrategy, StrategyContext


class ConversionStrategy(BaseStrategy):
    def __init__(
        self,
        fair_value_engine: FairValueEngine,
        signal_engine: SignalEngine,
    ) -> None:
        self.fair_value_engine = fair_value_engine
        self.signal_engine = signal_engine

    def generate_intent(self, context: StrategyContext) -> SignalIntent:
        fair_value = self.fair_value_engine.estimate(
            context.product, context.snapshot, context.memory, context.config,
        )
        # Custom intent logic here...
        return SignalIntent(
            product=context.product,
            fair_value=fair_value,
            mode="idle",
            rationale="conversion_strategy",
        )
```

### Step 2: Register in `STRATEGY_REGISTRY` (`src/strategies/__init__.py`)

```python
from src.strategies.conversion import ConversionStrategy

STRATEGY_REGISTRY: Mapping[str, StrategyFactory] = MappingProxyType(
    {
        "market_making": MarketMakingStrategy,
        "conversion": ConversionStrategy,       # <- add here
    }
)
```

### Step 3: Register the name (`src/core/config.py`)

Add to `KNOWN_STRATEGY_NAMES`:

```python
KNOWN_STRATEGY_NAMES: tuple[str, ...] = ("conversion", "market_making")
```

Then add a `ProductConfig` with `strategy_name="conversion"`.

### Step 4: Update `LIVE_MODULE_ORDER` (`src/scripts/export_submission.py`)

Add the new module in the correct topological position — after
`src/strategies/base.py` and before `src/strategies/__init__.py`:

```python
LIVE_MODULE_ORDER: tuple[str, ...] = (
    # ...existing modules...
    "src/strategies/base.py",
    "src/strategies/conversion.py",        # <- add here
    "src/strategies/market_making.py",
    "src/strategies/__init__.py",
    "src/trader.py",
)
```

The exporter's `verify_live_module_order()` will fail the build if this
step is skipped.

---

## Worked example: EMERALDS vs TOMATOES

Both use the same `market_making` strategy. They differ by fair value
method and parameters. From `default_engine_config()` in
`src/core/config.py`:

**EMERALDS** (stable anchor):
```python
"EMERALDS": ProductConfig(
    position_limit=20,
    strategy_name="market_making",
    fair_value_method="anchor",
    fair_value_fallbacks=("microprice", "mid"),
    anchor_price=10_000.0,
    taker_edge=1.0,
    maker_edge=2.0,
    quote_size=5,
    max_aggressive_size=10,
    inventory_skew=2.0,
    flatten_threshold=0.75,
    history_length=32,
),
```

**TOMATOES** (dynamic fair value):
```python
"TOMATOES": ProductConfig(
    position_limit=20,
    strategy_name="market_making",
    fair_value_method="weighted_mid",
    fair_value_fallbacks=("mid", "microprice"),
    taker_edge=1.0,
    maker_edge=1.0,
    quote_size=4,
    max_aggressive_size=8,
    inventory_skew=3.0,
    flatten_threshold=0.7,
    history_length=48,
),
```

Key differences:

- EMERALDS uses `anchor` (constant 10,000); TOMATOES uses `weighted_mid`
  (recency-weighted rolling average).
- TOMATOES has stronger `inventory_skew` (3.0 vs 2.0) and tighter
  `flatten_threshold` (0.7 vs 0.75) because its fair value drifts.
- EMERALDS has a wider `maker_edge` (2 vs 1) because the anchor is
  highly confident and the spread is stable.

---

## Validation checklist

After any product change, run these from the repo root:

```bash
source .venv/bin/activate

# Unit + integration tests
PYTHONPATH=. python -m pytest tests/ -q

# Export inline bundle (catches missing LIVE_MODULE_ORDER entries)
PYTHONPATH=. python -m src.scripts.export_submission --datamodel=inline --quiet

# Validate the platform bundle
PYTHONPATH=. python -m src.scripts.export_submission
PYTHONPATH=. python -m src.scripts.validate_submission

# Full submission gate
./scripts/check.sh --submission
```

If Path C was used, also verify the new strategy module appears in the
bundled output:

```bash
grep "# src/strategies/<name>.py" outputs/submissions/trader_submission.py
```

---

## See also

- [docs/architecture.md](architecture.md) — full module map and data
  flow
- [docs/phase_3_fair_value_note.md](phase_3_fair_value_note.md) — how
  to evaluate which estimator fits a product
- [docs/phase_6_robustness_note.md](phase_6_robustness_note.md) — how
  to sweep parameters after onboarding

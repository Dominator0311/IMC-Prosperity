"""Unit tests for ``src.core.state_store``.

The state store is the single boundary between live ``EngineState`` and
the ``traderData`` blob we hand Prosperity. Its job is to never crash
``Trader.run()`` and to always respect the platform's size budget.
"""

from __future__ import annotations

import json

import pytest

from src.core.state_store import StateStore
from src.core.types import EngineState


@pytest.mark.unit
def test_round_trip_preserves_all_memory_fields() -> None:
    store = StateStore(version=3, max_chars=50_000)
    state = EngineState(version=3)
    memory = state.for_product("EMERALDS")
    memory.recent_mids = [10_000.0, 10_001.5]
    memory.recent_spreads = [2.0, 4.0]
    memory.counters["ticks"] = 2
    memory.flags["initialized"] = True
    memory.values["last_fair_value"] = 10_000.25

    encoded = store.save(state)
    restored = store.load(encoded)

    emeralds = restored.products["EMERALDS"]
    assert restored.version == 3
    assert emeralds.recent_mids == [10_000.0, 10_001.5]
    assert emeralds.recent_spreads == [2.0, 4.0]
    assert emeralds.counters["ticks"] == 2
    assert emeralds.flags["initialized"] is True
    assert emeralds.values["last_fair_value"] == pytest.approx(10_000.25)


@pytest.mark.unit
@pytest.mark.parametrize("bad_input", ["", None, "   ", "not json", "[1, 2, 3]", "42"])
def test_load_recovers_from_malformed_input(bad_input: str | None) -> None:
    store = StateStore(version=2)
    state = store.load(bad_input)
    assert isinstance(state, EngineState)
    assert state.version == 2
    assert state.products == {}


@pytest.mark.unit
def test_load_ignores_bad_product_payloads() -> None:
    store = StateStore(version=1)
    payload = json.dumps(
        {
            "version": 1,
            "products": {
                "EMERALDS": {"recent_mids": [1, 2, "bad", None, 3]},
                "BROKEN": "this is not a dict",
                7: {"recent_mids": [1]},  # non-string key is dropped
            },
        }
    )

    restored = store.load(payload)

    assert "BROKEN" not in restored.products
    assert restored.products["EMERALDS"].recent_mids == [1.0, 2.0, 3.0]


@pytest.mark.unit
def test_load_ignores_bool_values_in_float_history_lists() -> None:
    store = StateStore(version=1)
    payload = json.dumps(
        {
            "version": 1,
            "products": {
                "P": {
                    "recent_mids": [True, 100, False, 101.5],
                    "recent_spreads": [False, 8, True],
                }
            },
        }
    )

    restored = store.load(payload)

    assert restored.products["P"].recent_mids == [100.0, 101.5]
    assert restored.products["P"].recent_spreads == [8.0]


@pytest.mark.unit
def test_save_always_fits_in_max_chars() -> None:
    store = StateStore(version=1, max_chars=120, truncated_history_keep=2, max_history=8)
    state = EngineState(version=1)
    memory = state.for_product("P")
    memory.recent_mids = [float(i) for i in range(200)]
    memory.recent_spreads = [float(i) for i in range(200)]

    encoded = store.save(state)

    assert len(encoded) <= 120
    payload = json.loads(encoded)
    assert payload["version"] == 1
    # We expect at most the truncated tail to survive inside the budget.
    if payload["products"]:
        persisted = payload["products"]["P"]["recent_mids"]
        assert persisted == [198.0, 199.0]


@pytest.mark.unit
def test_load_clamps_oversized_history_lists() -> None:
    store = StateStore(version=1, max_history=4, truncated_history_keep=4)
    raw = json.dumps(
        {
            "version": 1,
            "products": {
                "P": {
                    "recent_mids": [1, 2, 3, 4, 5, 6, 7, 8],
                    "recent_spreads": [1, 2, 3, 4, 5, 6, 7, 8],
                }
            },
        }
    )
    restored = store.load(raw)
    assert restored.products["P"].recent_mids == [5.0, 6.0, 7.0, 8.0]
    assert restored.products["P"].recent_spreads == [5.0, 6.0, 7.0, 8.0]


@pytest.mark.unit
def test_for_product_returns_same_memory_instance() -> None:
    state = EngineState()
    first = state.for_product("EMERALDS")
    second = state.for_product("EMERALDS")
    assert first is second
    first.counters["ticks"] = 5
    assert state.products["EMERALDS"].counters["ticks"] == 5


@pytest.mark.unit
def test_load_runs_migration_hook_for_old_versions() -> None:
    calls: dict[str, int] = {}

    class SpyStore(StateStore):
        def _migrate(self, raw: dict[str, object], *, from_version: int) -> dict[str, object]:
            calls["from_version"] = from_version
            return raw

    store = SpyStore(version=3)
    raw = json.dumps({"version": 1, "products": {}})
    store.load(raw)
    assert calls["from_version"] == 1


@pytest.mark.unit
def test_state_store_rejects_bad_constructor_args() -> None:
    with pytest.raises(ValueError):
        StateStore(version=0)
    with pytest.raises(ValueError):
        StateStore(max_chars=0)
    with pytest.raises(ValueError):
        StateStore(max_history=-1)
    with pytest.raises(ValueError):
        StateStore(max_history=4, truncated_history_keep=5)


@pytest.mark.unit
def test_save_rejects_nan_and_drops_memory_gracefully() -> None:
    """NaN/Infinity in ProductMemory.values must not produce spec-violating JSON."""
    store = StateStore(version=1)
    state = EngineState()
    memory = state.for_product("P")
    memory.values["bad"] = float("nan")

    with pytest.warns(RuntimeWarning, match="non-finite"):
        encoded = store.save(state)

    # The emitted blob must still be standards-compliant JSON.
    payload = json.loads(encoded)
    assert payload["version"] == 1
    # And it must not contain the bad product memory.
    assert payload["products"] == {}


@pytest.mark.unit
def test_save_rejects_infinity_too() -> None:
    store = StateStore(version=1)
    state = EngineState()
    memory = state.for_product("P")
    memory.recent_mids.append(float("inf"))

    with pytest.warns(RuntimeWarning):
        encoded = store.save(state)
    payload = json.loads(encoded)
    assert payload["products"] == {}


@pytest.mark.unit
def test_save_preserves_counters_values_flags_round_trip() -> None:
    store = StateStore(version=1)
    state = EngineState()
    memory = state.for_product("P")
    memory.counters = {"a": 1, "b": 2}
    memory.values = {"fv": 100.5}
    memory.flags = {"ready": True, "stale": False}

    restored = store.load(store.save(state))
    persisted = restored.products["P"]
    assert persisted.counters == {"a": 1, "b": 2}
    assert persisted.values == {"fv": 100.5}
    assert persisted.flags == {"ready": True, "stale": False}

from src.core.state_store import StateStore
from src.core.types import EngineState


def test_state_store_round_trip() -> None:
    store = StateStore(version=3, max_chars=50_000)
    state = EngineState(version=3)
    memory = state.for_product("EMERALDS")
    memory.recent_mids = [10_000.0, 10_001.0]
    memory.counters["ticks"] = 2

    encoded = store.save(state)
    restored = store.load(encoded)

    assert restored.version == 3
    assert restored.products["EMERALDS"].recent_mids == [10_000.0, 10_001.0]
    assert restored.products["EMERALDS"].counters["ticks"] == 2


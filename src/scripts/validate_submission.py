from __future__ import annotations

from src.datamodel import Observation, TradingState
from src.trader import Trader


def main() -> None:
    trader = Trader()
    if not hasattr(trader, "run"):
        raise SystemExit("Trader is missing run()")

    state = TradingState(
        traderData="",
        timestamp=0,
        listings={},
        order_depths={},
        own_trades={},
        market_trades={},
        position={},
        observations=Observation(),
    )
    result = trader.run(state)
    if not isinstance(result, tuple) or len(result) != 3:
        raise SystemExit("Trader.run() must return (orders, conversions, traderData)")

    print("Submission scaffold validation passed.")


if __name__ == "__main__":
    main()

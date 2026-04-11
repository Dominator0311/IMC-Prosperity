from __future__ import annotations

from pathlib import Path

from src.backtest.metrics import RunMetrics
from src.backtest.replay_engine import ReplayEngine


def main() -> None:
    price_files = sorted(Path("data/raw/tutorial_round_1").glob("prices_*.csv"))
    if not price_files:
        raise SystemExit("No tutorial price files found in data/raw/tutorial_round_1")

    engine = ReplayEngine.from_price_files(price_files)
    metrics = RunMetrics()

    for step in engine.iter_steps():
        for product in step.rows_by_product:
            metrics.orders_by_product[product] = metrics.orders_by_product.get(product, 0) + 1

    print(f"Loaded {len(engine.steps)} replay steps from {len(price_files)} files.")
    print(f"Products seen: {sorted(metrics.orders_by_product)}")


if __name__ == "__main__":
    main()

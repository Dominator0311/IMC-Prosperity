from __future__ import annotations

from src.backtest.metrics import RunMetrics
from src.backtest.reporting import build_review_pack


def main() -> None:
    metrics = RunMetrics(order_count=0, buy_order_count=0, sell_order_count=0)
    review_pack = build_review_pack(metrics)
    print("Review pack scaffold:")
    print(review_pack)


if __name__ == "__main__":
    main()

"""Review exact L1 oracle paths for the simulator-equivalent 100k slice."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from src.scripts.round_3.run_velvet_new_family_research import (
    POS_LIMITS,
    UNDERLYING,
    WINDOW,
    discover_data_dir,
    load_prices,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = REPO_ROOT / "outputs" / "round_3" / "velvet_oracle_path_review"

PRODUCTS = (
    UNDERLYING,
    "VEV_5000",
    "VEV_5100",
    "VEV_5200",
    "VEV_5300",
    "VEV_5400",
    "VEV_5500",
    "VEV_4000",
    "VEV_4500",
)


@dataclass(frozen=True)
class OracleResult:
    product: str
    pnl: float
    final_position: int
    trade_count: int
    abs_quantity: int
    buy_count: int
    sell_count: int
    first_trade_ts: int | None
    last_trade_ts: int | None


def solve_oracle(data: pd.DataFrame, product: str) -> tuple[OracleResult, pd.DataFrame]:
    product_data = data[data["product"] == product].sort_values("timestamp").reset_index(drop=True)
    limit = POS_LIMITS[product]
    states = np.arange(-limit, limit + 1, dtype=np.int16)
    n_states = len(states)
    offset = limit
    n = len(product_data)
    neg = -1e18
    dp = np.full(n_states, neg, dtype=np.float64)
    dp[offset] = 0.0
    prev_state = np.zeros((n, n_states), dtype=np.int16)
    action_qty = np.zeros((n, n_states), dtype=np.int16)
    action_price = np.zeros((n, n_states), dtype=np.int32)

    for i, row in enumerate(product_data.itertuples(index=False)):
        bid = int(row.bid_price_1)
        ask = int(row.ask_price_1)
        bid_vol = int(abs(row.bid_volume_1))
        ask_vol = int(abs(row.ask_volume_1))
        new = dp.copy()
        prev_state[i, :] = states

        for idx, pos in enumerate(states):
            base = dp[idx]
            if base <= neg / 2:
                continue
            max_buy = min(ask_vol, limit - int(pos))
            for qty in range(1, max_buy + 1):
                ni = idx + qty
                value = base - qty * ask
                if value > new[ni]:
                    new[ni] = value
                    prev_state[i, ni] = pos
                    action_qty[i, ni] = qty
                    action_price[i, ni] = ask
            max_sell = min(bid_vol, limit + int(pos))
            for qty in range(1, max_sell + 1):
                ni = idx - qty
                value = base + qty * bid
                if value > new[ni]:
                    new[ni] = value
                    prev_state[i, ni] = pos
                    action_qty[i, ni] = -qty
                    action_price[i, ni] = bid
        dp = new

    final_mid = float(product_data.iloc[-1]["mid_price"])
    terminal = dp + states.astype(np.float64) * final_mid
    best_idx = int(np.argmax(terminal))
    pnl = float(terminal[best_idx])
    final_pos = int(states[best_idx])

    actions = []
    idx = best_idx
    for i in range(n - 1, -1, -1):
        qty = int(action_qty[i, idx])
        if qty != 0:
            row = product_data.iloc[i]
            actions.append(
                {
                    "product": product,
                    "timestamp": int(row["timestamp"]),
                    "side": "BUY" if qty > 0 else "SELL",
                    "price": int(action_price[i, idx]),
                    "quantity": abs(qty),
                    "position_after": int(states[idx]),
                    "mid": float(row["mid_price"]),
                    "bid": int(row["bid_price_1"]),
                    "ask": int(row["ask_price_1"]),
                }
            )
        prev_pos = int(prev_state[i, idx])
        idx = prev_pos + offset
    actions.reverse()
    actions_df = pd.DataFrame(actions)

    result = OracleResult(
        product=product,
        pnl=pnl,
        final_position=final_pos,
        trade_count=len(actions_df),
        abs_quantity=int(actions_df["quantity"].sum()) if not actions_df.empty else 0,
        buy_count=int((actions_df["side"] == "BUY").sum()) if not actions_df.empty else 0,
        sell_count=int((actions_df["side"] == "SELL").sum()) if not actions_df.empty else 0,
        first_trade_ts=int(actions_df["timestamp"].min()) if not actions_df.empty else None,
        last_trade_ts=int(actions_df["timestamp"].max()) if not actions_df.empty else None,
    )
    return result, actions_df


def bucket_actions(actions: pd.DataFrame) -> pd.DataFrame:
    if actions.empty:
        return pd.DataFrame()
    df = actions.copy()
    df["bucket"] = (df["timestamp"] // 5000) * 5000
    return (
        df.groupby(["product", "bucket", "side"], as_index=False)
        .agg(trades=("quantity", "count"), quantity=("quantity", "sum"), avg_price=("price", "mean"))
        .sort_values(["product", "bucket", "side"])
    )


def run(data_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = load_prices(data_dir)
    data = prices[(prices["day"] == 2) & (prices["timestamp"] < WINDOW)].copy()
    results = []
    all_actions = []
    for product in PRODUCTS:
        result, actions = solve_oracle(data, product)
        results.append(result)
        if not actions.empty:
            all_actions.append(actions)
    summary = pd.DataFrame([result.__dict__ for result in results])
    actions_df = pd.concat(all_actions, ignore_index=True) if all_actions else pd.DataFrame()
    buckets = bucket_actions(actions_df)
    summary.to_csv(output_dir / "summary.csv", index=False)
    actions_df.to_csv(output_dir / "actions.csv", index=False)
    buckets.to_csv(output_dir / "action_buckets.csv", index=False)
    print(summary.to_string(index=False))
    print()
    print(buckets.head(120).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR))
    args = parser.parse_args()
    run(discover_data_dir(args.data_dir), Path(args.output_dir))


if __name__ == "__main__":
    main()

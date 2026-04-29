"""HYDROGEL-only broad strategy-family research harness.

This is intentionally not a live-path module. It is a discovery tool for
answering a higher-level question before tuning: which class of HYDROGEL
strategy is worth implementing?

It evaluates families on:
  - Historical R3 CSV days 0/1/2 from data/raw/round_3/
  - Official live result logs when present (especially v7.zip extraction)

Families are deliberately broad:
  - static / rolling mean reversion
  - trend following
  - channel breakout and channel fade
  - passive maker around static / rolling fair
  - hybrid directional-with-passive quoting

The simulator is approximate. It should be used to rank ideas and identify
failure modes, not as a literal official PnL predictor.
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data/raw/round_3"
RESULTS_DIR = REPO_ROOT / "outputs" / "round_3" / "Results"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_family_sweep"

PRODUCT = "HYDROGEL_PACK"
LIMIT = 200


@dataclass(frozen=True)
class Dataset:
    name: str
    prices: pd.DataFrame
    trades: pd.DataFrame
    kind: str


@dataclass(frozen=True)
class SimResult:
    dataset: str
    kind: str
    family: str
    params: str
    pnl: float
    final_pos: int
    trades: int
    abs_qty: int
    max_pos: int
    min_pos: int
    max_drawdown: float
    peak_pnl: float
    min_pnl: float


@dataclass(frozen=True)
class OrderIntent:
    bid: int | None = None
    bid_qty: int = 0
    ask: int | None = None
    ask_qty: int = 0
    target_pos: int | None = None


def _num(value: object, default: float = 0.0) -> float:
    try:
        if value == "" or value is None:
            return default
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except (TypeError, ValueError):
        return default


def _load_historical_day(day: int) -> Dataset:
    price_path = DATA_DIR / f"prices_round_3_day_{day}.csv"
    trade_path = DATA_DIR / f"trades_round_3_day_{day}.csv"
    prices = pd.read_csv(price_path, sep=";")
    prices = prices[prices["product"] == PRODUCT].copy()
    trades = pd.read_csv(trade_path, sep=";")
    trades = trades[trades["symbol"] == PRODUCT].copy()
    return _prepare_dataset(
        Dataset(name=f"hist_day_{day}", prices=prices, trades=trades, kind="historical")
    )


def _load_official_result(name: str, log_path: Path) -> Dataset | None:
    if not log_path.exists():
        return None
    payload = json.loads(log_path.read_text())
    prices = pd.read_csv(io.StringIO(payload["activitiesLog"]), sep=";")
    prices = prices[prices["product"] == PRODUCT].copy()
    trades = pd.DataFrame(payload.get("tradeHistory", []))
    if trades.empty:
        trades = pd.DataFrame(
            columns=["timestamp", "buyer", "seller", "symbol", "price", "quantity"]
        )
    trades = trades[trades["symbol"] == PRODUCT].copy()
    # Remove our own historical fills so passive-fill simulation sees only
    # bot flow. Our own fills differ by submitted strategy and would leak.
    if "buyer" in trades.columns and "seller" in trades.columns:
        trades = trades[
            (trades["buyer"] != "SUBMISSION") & (trades["seller"] != "SUBMISSION")
        ].copy()
    return _prepare_dataset(
        Dataset(name=name, prices=prices, trades=trades, kind="official")
    )


def _prepare_dataset(dataset: Dataset) -> Dataset:
    prices = dataset.prices.copy()
    for col in prices.columns:
        if col != "product":
            prices[col] = pd.to_numeric(prices[col], errors="coerce")
    prices = prices.sort_values("timestamp").reset_index(drop=True)
    prices["spread"] = prices["ask_price_1"] - prices["bid_price_1"]
    prices["bid_volume_1"] = prices["bid_volume_1"].fillna(0).astype(int)
    prices["ask_volume_1"] = prices["ask_volume_1"].fillna(0).abs().astype(int)
    prices["anchor_mid"] = prices.apply(_anchor_mid, axis=1)
    prices["micro_mid"] = (
        prices["bid_price_1"] * prices["ask_volume_1"]
        + prices["ask_price_1"] * prices["bid_volume_1"]
    ) / (prices["bid_volume_1"] + prices["ask_volume_1"]).replace(0, 1)
    prices["ret1"] = prices["mid_price"].diff().fillna(0.0)

    trades = dataset.trades.copy()
    if not trades.empty:
        for col in ("timestamp", "price", "quantity"):
            trades[col] = pd.to_numeric(trades[col], errors="coerce")
        trades = trades.dropna(subset=["timestamp", "price", "quantity"])
        trades["timestamp"] = trades["timestamp"].astype(int)
        trades["quantity"] = trades["quantity"].astype(int)
        book = prices[["timestamp", "bid_price_1", "ask_price_1", "mid_price"]]
        trades = trades.merge(book, on="timestamp", how="left")
        trades["side"] = "inside"
        trades.loc[trades["price"] >= trades["ask_price_1"], "side"] = "buy"
        trades.loc[trades["price"] <= trades["bid_price_1"], "side"] = "sell"
        trades["signed_qty"] = 0
        trades.loc[trades["side"] == "buy", "signed_qty"] = trades["quantity"]
        trades.loc[trades["side"] == "sell", "signed_qty"] = -trades["quantity"]
        trades = trades.sort_values("timestamp").reset_index(drop=True)

    return Dataset(dataset.name, prices, trades, dataset.kind)


def _anchor_mid(row: pd.Series) -> float:
    bid = _wall_price(row, "bid")
    ask = _wall_price(row, "ask")
    if bid is None or ask is None:
        return float(row["mid_price"])
    return (bid + ask) / 2.0


def _wall_price(row: pd.Series, side: str) -> float | None:
    best_price = None
    best_volume = -1
    for level in (1, 2, 3):
        price = row.get(f"{side}_price_{level}")
        volume = row.get(f"{side}_volume_{level}")
        if pd.isna(price) or pd.isna(volume):
            continue
        volume = abs(float(volume))
        if volume > best_volume:
            best_price = float(price)
            best_volume = volume
    return best_price


def _datasets() -> list[Dataset]:
    datasets = [_load_historical_day(day) for day in (0, 1, 2)]
    official_candidates = {
        "official_v6_381639": RESULTS_DIR / "extracted_6" / "381639.log",
        "official_pre_v7_383464": RESULTS_DIR / "extracted_7" / "383464.log",
        "official_v7_384279": RESULTS_DIR / "extracted_v7" / "384279.log",
    }
    for name, path in official_candidates.items():
        loaded = _load_official_result(name, path)
        if loaded is not None:
            datasets.append(loaded)
    return datasets


def _trade_map(trades: pd.DataFrame) -> dict[int, list[dict]]:
    by_ts: dict[int, list[dict]] = {}
    for row in trades.to_dict("records"):
        by_ts.setdefault(int(row["timestamp"]), []).append(row)
    return by_ts


def _clip_target(target: float) -> int:
    return int(max(-LIMIT, min(LIMIT, round(target))))


def _max_drawdown(values: list[float]) -> float:
    peak = -1e18
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        worst = min(worst, value - peak)
    return worst


def simulate(
    dataset: Dataset,
    family: str,
    params: str,
    policy: Callable[[pd.Series, int], OrderIntent],
) -> tuple[SimResult, pd.DataFrame]:
    prices = dataset.prices
    trades_by_ts = _trade_map(dataset.trades)

    pos = 0
    cash = 0.0
    trade_count = 0
    abs_qty = 0
    rows: list[dict] = []

    for row in prices.itertuples(index=False):
        r = pd.Series(row._asdict())
        ts = int(r["timestamp"])
        intent = policy(r, pos)

        tick_qty = 0
        tick_cash = 0.0

        # 1. Directional taker move toward target, using displayed L1.
        if intent.target_pos is not None:
            target = max(-LIMIT, min(LIMIT, int(intent.target_pos)))
            desired = target - pos
            if desired > 0:
                qty = min(desired, int(r["ask_volume_1"]), LIMIT - pos)
                if qty > 0:
                    tick_qty += qty
                    tick_cash -= qty * float(r["ask_price_1"])
            elif desired < 0:
                qty = min(-desired, int(r["bid_volume_1"]), LIMIT + pos)
                if qty > 0:
                    tick_qty -= qty
                    tick_cash += qty * float(r["bid_price_1"])

        # Apply taker leg before passive fills. This approximates platform order
        # order: our submitted aggressive orders can fill immediately, while
        # passive quotes compete with bot tape at the same tick.
        if tick_qty:
            pos += tick_qty
            cash += tick_cash
            trade_count += 1
            abs_qty += abs(tick_qty)

        # 2. Passive quote fills against bot tape. We cap fill quantity by quote
        # size and remaining position capacity.
        passive_qty = 0
        passive_cash = 0.0
        bid_left = max(0, intent.bid_qty)
        ask_left = max(0, intent.ask_qty)
        for trade in trades_by_ts.get(ts, []):
            qty = int(trade.get("quantity", 0))
            price = float(trade.get("price", 0.0))
            side = trade.get("side")
            if side == "sell" and intent.bid is not None and price <= intent.bid:
                fill = min(qty, bid_left, LIMIT - pos)
                if fill > 0:
                    passive_qty += fill
                    passive_cash -= fill * intent.bid
                    bid_left -= fill
                    pos += fill
            elif side == "buy" and intent.ask is not None and price >= intent.ask:
                fill = min(qty, ask_left, LIMIT + pos)
                if fill > 0:
                    passive_qty -= fill
                    passive_cash += fill * intent.ask
                    ask_left -= fill
                    pos -= fill

        if passive_qty:
            cash += passive_cash
            trade_count += 1
            abs_qty += abs(passive_qty)

        pnl = cash + pos * float(r["mid_price"])
        rows.append(
            {
                "timestamp": ts,
                "mid": float(r["mid_price"]),
                "position": pos,
                "cash": cash,
                "pnl": pnl,
                "tick_qty": tick_qty + passive_qty,
                "target": intent.target_pos,
                "bid": intent.bid,
                "ask": intent.ask,
            }
        )

    path = pd.DataFrame(rows)
    final_pnl = float(path["pnl"].iloc[-1]) if not path.empty else 0.0
    result = SimResult(
        dataset=dataset.name,
        kind=dataset.kind,
        family=family,
        params=params,
        pnl=final_pnl,
        final_pos=int(pos),
        trades=int(trade_count),
        abs_qty=int(abs_qty),
        max_pos=int(path["position"].max()) if not path.empty else 0,
        min_pos=int(path["position"].min()) if not path.empty else 0,
        max_drawdown=float(_max_drawdown(path["pnl"].tolist())) if not path.empty else 0.0,
        peak_pnl=float(path["pnl"].max()) if not path.empty else 0.0,
        min_pnl=float(path["pnl"].min()) if not path.empty else 0.0,
    )
    return result, path


def _static_mr(mu: float, entry: float, exit_band: float) -> Callable[[pd.Series, int], OrderIntent]:
    def policy(row: pd.Series, pos: int) -> OrderIntent:
        gap = mu - float(row["mid_price"])
        if abs(gap) <= exit_band:
            target = 0
        elif gap >= entry:
            target = LIMIT
        elif gap <= -entry:
            target = -LIMIT
        else:
            target = pos
        return OrderIntent(target_pos=target)

    return policy


def _rolling_mr(window: int, entry: float, exit_band: float) -> Callable[[pd.Series, int], OrderIntent]:
    mids: list[float] = []

    def policy(row: pd.Series, pos: int) -> OrderIntent:
        mid = float(row["mid_price"])
        mids.append(mid)
        fair = sum(mids[-window:]) / min(len(mids), window)
        gap = fair - mid
        if len(mids) < max(5, window // 4):
            target = 0
        elif abs(gap) <= exit_band:
            target = 0
        elif gap >= entry:
            target = LIMIT
        elif gap <= -entry:
            target = -LIMIT
        else:
            target = pos
        return OrderIntent(target_pos=target)

    return policy


def _linear_mr(mu: float, scale: float) -> Callable[[pd.Series, int], OrderIntent]:
    def policy(row: pd.Series, pos: int) -> OrderIntent:
        return OrderIntent(target_pos=_clip_target((mu - float(row["mid_price"])) / scale * LIMIT))

    return policy


def _trend_ma(fast: int, slow: int, threshold: float) -> Callable[[pd.Series, int], OrderIntent]:
    mids: list[float] = []

    def policy(row: pd.Series, pos: int) -> OrderIntent:
        mid = float(row["mid_price"])
        mids.append(mid)
        if len(mids) < slow:
            return OrderIntent(target_pos=0)
        fast_ma = sum(mids[-fast:]) / fast
        slow_ma = sum(mids[-slow:]) / slow
        signal = fast_ma - slow_ma
        if signal > threshold:
            return OrderIntent(target_pos=LIMIT)
        if signal < -threshold:
            return OrderIntent(target_pos=-LIMIT)
        return OrderIntent(target_pos=pos)

    return policy


def _channel(lookback: int, buffer: float, mode: str) -> Callable[[pd.Series, int], OrderIntent]:
    mids: list[float] = []

    def policy(row: pd.Series, pos: int) -> OrderIntent:
        mid = float(row["mid_price"])
        if len(mids) < lookback:
            mids.append(mid)
            return OrderIntent(target_pos=0)
        high = max(mids[-lookback:])
        low = min(mids[-lookback:])
        mids.append(mid)
        if mode == "breakout":
            if mid > high + buffer:
                return OrderIntent(target_pos=LIMIT)
            if mid < low - buffer:
                return OrderIntent(target_pos=-LIMIT)
        else:
            if mid > high + buffer:
                return OrderIntent(target_pos=-LIMIT)
            if mid < low - buffer:
                return OrderIntent(target_pos=LIMIT)
        return OrderIntent(target_pos=pos)

    return policy


def _passive_static(mu: float, edge: int, size: int) -> Callable[[pd.Series, int], OrderIntent]:
    def policy(row: pd.Series, pos: int) -> OrderIntent:
        bid = min(int(row["bid_price_1"]), math.floor(mu - edge))
        ask = max(int(row["ask_price_1"]), math.ceil(mu + edge))
        # Skew size away from inventory.
        bid_qty = min(size, LIMIT - pos) if pos < LIMIT else 0
        ask_qty = min(size, LIMIT + pos) if pos > -LIMIT else 0
        if pos > LIMIT * 0.5:
            bid_qty = 0
        if pos < -LIMIT * 0.5:
            ask_qty = 0
        return OrderIntent(bid=bid, bid_qty=bid_qty, ask=ask, ask_qty=ask_qty)

    return policy


def _hybrid_static(mu: float, entry: float, exit_band: float, edge: int, size: int) -> Callable[[pd.Series, int], OrderIntent]:
    mr = _static_mr(mu, entry, exit_band)

    def policy(row: pd.Series, pos: int) -> OrderIntent:
        base = mr(row, pos)
        mid = float(row["mid_price"])
        # Passive quotes are directional: bid when below fair, ask when above fair.
        bid = ask = None
        bid_qty = ask_qty = 0
        if mid < mu - exit_band and pos < LIMIT:
            bid = min(int(row["bid_price_1"]), math.floor(mu - edge))
            bid_qty = min(size, LIMIT - pos)
        if mid > mu + exit_band and pos > -LIMIT:
            ask = max(int(row["ask_price_1"]), math.ceil(mu + edge))
            ask_qty = min(size, LIMIT + pos)
        return OrderIntent(
            bid=bid,
            bid_qty=bid_qty,
            ask=ask,
            ask_qty=ask_qty,
            target_pos=base.target_pos,
        )

    return policy


def _policies() -> Iterable[tuple[str, str, Callable[[pd.Series, int], OrderIntent]]]:
    # Coarse first-pass grid: intentionally broad and sparse. Once a family
    # survives this scan, run a denser follow-up only around that shape.
    for mu in (9960, 9980, 9990, 10000):
        for entry in (15, 30, 45):
            for exit_band in (0, 8):
                if exit_band >= entry:
                    continue
                yield "static_mr", f"mu={mu},entry={entry},exit={exit_band}", _static_mr(mu, entry, exit_band)

    for mu in (9970, 9990, 10000):
        for scale in (40, 80):
            yield "linear_mr", f"mu={mu},scale={scale}", _linear_mr(mu, scale)

    for window in (50, 100, 200):
        for entry in (8, 21):
            for exit_band in (0, 5):
                if exit_band >= entry:
                    continue
                yield "rolling_mr", f"w={window},entry={entry},exit={exit_band}", _rolling_mr(window, entry, exit_band)

    for fast in (5, 20):
        for slow in (50, 200):
            if slow <= fast:
                continue
            for threshold in (2, 5):
                yield "trend_ma", f"fast={fast},slow={slow},th={threshold}", _trend_ma(fast, slow, threshold)

    for lookback in (50, 200):
        for buffer in (0, 5):
            yield "channel_breakout", f"lookback={lookback},buffer={buffer}", _channel(lookback, buffer, "breakout")
            yield "channel_fade", f"lookback={lookback},buffer={buffer}", _channel(lookback, buffer, "fade")

    for mu in (9980, 9990, 10000):
        for edge in (1, 3, 5):
            for size in (10, 40):
                yield "passive_static", f"mu={mu},edge={edge},size={size}", _passive_static(mu, edge, size)

    for mu in (9980, 9990):
        for entry in (25, 45):
            for edge in (2, 5):
                yield "hybrid_static", f"mu={mu},entry={entry},exit=5,edge={edge},size=10", _hybrid_static(mu, entry, 5, edge, 10)


def run_sweep() -> pd.DataFrame:
    datasets = _datasets()
    results: list[SimResult] = []
    best_paths: dict[tuple[str, str], pd.DataFrame] = {}

    policies = list(_policies())
    print(f"Loaded {len(datasets)} datasets and {len(policies)} policies.")

    for dataset in datasets:
        print(f"  sweeping {dataset.name} ({len(dataset.prices)} ticks)")
        best_for_dataset: tuple[float, str, pd.DataFrame] | None = None
        for family, params, policy_factory in policies:
            # Each policy may hold rolling state, so use the callable instance
            # provided by _policies only once per dataset/policy. Recreate by
            # rebuilding _policies would be expensive; instead policies are
            # already factories in closure form. To avoid state leakage across
            # datasets, _policies is regenerated per dataset below.
            result, path = simulate(dataset, family, params, policy_factory)
            results.append(result)
            if best_for_dataset is None or result.pnl > best_for_dataset[0]:
                best_for_dataset = (result.pnl, f"{family}:{params}", path)
        if best_for_dataset is not None:
            best_paths[(dataset.name, best_for_dataset[1])] = best_for_dataset[2]
        # Recreate policies for next dataset to reset rolling closures.
        policies = list(_policies())

    df = pd.DataFrame([asdict(r) for r in results])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "all_results.csv", index=False)

    for (dataset, label), path in best_paths.items():
        safe = label.replace(":", "_").replace(",", "_").replace("=", "-")
        path.to_csv(OUT_DIR / f"best_path_{dataset}_{safe}.csv", index=False)

    return df


def summarize(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    pivot = df.pivot_table(
        index=["family", "params"],
        columns="dataset",
        values="pnl",
        aggfunc="first",
    ).reset_index()

    hist_cols = [c for c in pivot.columns if str(c).startswith("hist_day_")]
    official_cols = [c for c in pivot.columns if str(c).startswith("official_")]
    pivot["hist_mean"] = pivot[hist_cols].mean(axis=1)
    pivot["hist_min"] = pivot[hist_cols].min(axis=1)
    pivot["hist_positive_days"] = (pivot[hist_cols] > 0).sum(axis=1)
    pivot["official_mean"] = pivot[official_cols].mean(axis=1) if official_cols else 0.0
    pivot["score"] = (
        pivot["hist_mean"]
        + 0.5 * pivot["hist_min"]
        + 0.5 * pivot["official_mean"]
        + 500.0 * pivot["hist_positive_days"]
    )
    ranked = pivot.sort_values("score", ascending=False)

    family_summary = df.groupby("family").agg(
        runs=("pnl", "count"),
        mean_pnl=("pnl", "mean"),
        median_pnl=("pnl", "median"),
        max_pnl=("pnl", "max"),
        min_pnl=("pnl", "min"),
        positive_rate=("pnl", lambda s: float((s > 0).mean())),
        mean_abs_qty=("abs_qty", "mean"),
    ).reset_index().sort_values("mean_pnl", ascending=False)

    ranked.to_csv(OUT_DIR / "ranked_by_policy.csv", index=False)
    family_summary.to_csv(OUT_DIR / "family_summary.csv", index=False)
    return ranked, family_summary


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _md_table(df: pd.DataFrame, columns: list[str], limit: int = 20) -> str:
    data = df.head(limit)[columns]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in data.iterrows():
        lines.append("| " + " | ".join(_fmt(row[c]) for c in columns) + " |")
    return "\n".join(lines)


def write_report(df: pd.DataFrame, ranked: pd.DataFrame, family_summary: pd.DataFrame) -> None:
    timestamp = datetime.utcnow().isoformat()
    lines = [
        "# HYDROGEL Strategy-Family Sweep",
        "",
        f"Generated: {timestamp}",
        "",
        "This is a discovery harness, not the live simulator. Use it to choose a broad family, then implement that family in the real engine and verify on official logs.",
        "",
        "## Family Summary",
        "",
        _md_table(
            family_summary,
            ["family", "runs", "mean_pnl", "median_pnl", "max_pnl", "min_pnl", "positive_rate", "mean_abs_qty"],
            limit=20,
        ),
        "",
        "## Top Policies",
        "",
        _md_table(
            ranked,
            ["family", "params", "hist_mean", "hist_min", "hist_positive_days", "official_mean", "score"],
            limit=25,
        ),
        "",
        "## Files",
        "",
        "- `all_results.csv`: every dataset/policy simulation",
        "- `ranked_by_policy.csv`: cross-dataset policy ranking",
        "- `family_summary.csv`: aggregate by broad family",
        "- `family_boxplot.png`: PnL distribution by family",
        "- `top_policy_by_dataset.png`: best policy per dataset",
    ]
    (OUT_DIR / "report.md").write_text("\n".join(lines))


def write_charts(df: pd.DataFrame, ranked: pd.DataFrame) -> None:
    plt.figure(figsize=(14, 7))
    order = (
        df.groupby("family")["pnl"].median().sort_values(ascending=False).index.tolist()
    )
    data = [df[df["family"] == family]["pnl"] for family in order]
    plt.boxplot(data, labels=order, showfliers=False)
    plt.xticks(rotation=35, ha="right")
    plt.axhline(0, color="black", linewidth=0.8)
    plt.ylabel("simulated PnL")
    plt.title("HYDROGEL broad strategy family PnL distribution")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "family_boxplot.png", dpi=160)
    plt.close()

    best = df.sort_values("pnl", ascending=False).groupby("dataset").head(1)
    labels = best["dataset"].tolist()
    values = best["pnl"].tolist()
    text = (best["family"] + "\n" + best["params"]).tolist()
    plt.figure(figsize=(14, 7))
    bars = plt.bar(labels, values)
    plt.axhline(0, color="black", linewidth=0.8)
    plt.xticks(rotation=20, ha="right")
    plt.ylabel("best simulated PnL")
    plt.title("Best HYDROGEL policy per dataset")
    for bar, label in zip(bars, text):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            label[:55],
            ha="center",
            va="bottom",
            fontsize=7,
            rotation=90,
        )
    plt.tight_layout()
    plt.savefig(OUT_DIR / "top_policy_by_dataset.png", dpi=160)
    plt.close()

    top = ranked.head(12)
    plt.figure(figsize=(14, 7))
    plt.scatter(top["hist_mean"], top["official_mean"], s=80)
    for _, row in top.iterrows():
        plt.text(row["hist_mean"], row["official_mean"], row["family"], fontsize=8)
    plt.axhline(0, color="black", linewidth=0.8)
    plt.axvline(0, color="black", linewidth=0.8)
    plt.xlabel("historical mean PnL")
    plt.ylabel("official mean PnL")
    plt.title("Top policies: historical vs official behavior")
    plt.tight_layout()
    plt.savefig(OUT_DIR / "top_policy_hist_vs_official.png", dpi=160)
    plt.close()


def main() -> None:
    df = run_sweep()
    ranked, family_summary = summarize(df)
    write_charts(df, ranked)
    write_report(df, ranked, family_summary)

    print(f"\nWrote HYDROGEL sweep outputs to {OUT_DIR}")
    print("\nFamily summary:")
    print(family_summary.head(20).to_string(index=False))
    print("\nTop policies:")
    print(
        ranked[
            ["family", "params", "hist_mean", "hist_min", "hist_positive_days", "official_mean", "score"]
        ].head(20).to_string(index=False)
    )


if __name__ == "__main__":
    main()

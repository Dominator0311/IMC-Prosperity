"""HYDROGEL strategy-class research for the 1M final horizon.

This is a fast L1 taker-only research harness. It is deliberately separate
from the upload engine: the purpose is to compare broad strategy ideas before
spending slower full-engine simulation time.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data/raw/round_3"
OUT_DIR = REPO_ROOT / "outputs" / "round_3" / "hydrogel_regime_research"
PRODUCT = "HYDROGEL_PACK"
LIMIT = 200
RAMP_START = 850_000
RAMP_END = 950_000


@dataclass(frozen=True)
class Candidate:
    name: str
    family: str
    mu: float = 9988.0
    entry: float = 30.0
    reset: float = 8.0
    exit_gap: float = 35.0
    step: int = 200
    slope_window: int = 10
    slope_gate: float = 0.0
    confirm: str = "none"  # none, turn, trend
    rolling_window: int = 500
    rolling_offset: float = 0.0
    vol_window: int = 100
    vol_mult: float = 1.5
    flat_gap: float = 0.0


@dataclass(frozen=True)
class Row:
    candidate: str
    family: str
    day: int
    pnl: float
    peak: float
    max_dd: float
    final_pos: int
    trades: int
    abs_qty: int


def _load_day(day: int) -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR / f"prices_round_3_day_{day}.csv", sep=";")
    h = df[df["product"] == PRODUCT].sort_values("timestamp").reset_index(drop=True)
    cols = [
        "timestamp",
        "bid_price_1",
        "bid_volume_1",
        "ask_price_1",
        "ask_volume_1",
        "mid_price",
    ]
    return h[cols].copy()


def _cap(ts: int) -> int:
    if ts < RAMP_START:
        return LIMIT
    if ts >= RAMP_END:
        return 1
    return max(1, int(LIMIT * (RAMP_END - ts) / (RAMP_END - RAMP_START)))


def _trade_to_target(row: pd.Series, pos: int, target: int, max_step: int) -> tuple[int, float, int]:
    delta = max(-max_step, min(max_step, target - pos))
    if delta == 0:
        return pos, 0.0, 0
    if delta > 0:
        qty = min(delta, abs(int(row["ask_volume_1"])))
        if qty <= 0:
            return pos, 0.0, 0
        return pos + qty, -qty * float(row["ask_price_1"]), qty
    qty = min(-delta, abs(int(row["bid_volume_1"])))
    if qty <= 0:
        return pos, 0.0, 0
    return pos - qty, qty * float(row["bid_price_1"]), qty


def simulate(h: pd.DataFrame, c: Candidate) -> Row:
    mids = h["mid_price"].astype(float)
    slopes = mids - mids.shift(c.slope_window)
    rolling = mids.rolling(c.rolling_window, min_periods=1).mean()
    vol = mids.diff().abs().rolling(c.vol_window, min_periods=1).mean().fillna(0.0)

    pos = 0
    cash = 0.0
    trades = 0
    abs_qty = 0
    long_mode = False
    pnl_path: list[float] = []

    for i, row in h.iterrows():
        ts = int(row["timestamp"])
        mid = float(row["mid_price"])
        cap = _cap(ts)
        slope = 0.0 if pd.isna(slopes.iloc[i]) else float(slopes.iloc[i])
        fair = c.mu
        if c.family == "rolling":
            fair = float(rolling.iloc[i]) + c.rolling_offset
        elif c.family == "vol_band":
            fair = c.mu
        pos_cap = cap

        target = pos
        deviation = mid - fair
        entry = c.entry
        if c.family == "vol_band":
            entry = max(c.entry, c.vol_mult * float(vol.iloc[i]))

        if c.family in {"cycle", "reversal", "rolling", "vol_band"}:
            if long_mode and pos > 0 and mid >= c.mu + c.exit_gap:
                target = 0
                long_mode = False
            elif pos < 0 and mid <= c.mu - c.reset:
                target = 40
                long_mode = True
            elif long_mode:
                target = max(pos, 40)
            else:
                sell_ok = deviation >= entry
                buy_ok = deviation <= -entry
                if c.confirm == "turn":
                    sell_ok = sell_ok and slope <= -c.slope_gate
                    buy_ok = buy_ok and slope >= c.slope_gate
                elif c.confirm == "trend":
                    sell_ok = sell_ok and slope >= c.slope_gate
                    buy_ok = buy_ok and slope <= -c.slope_gate
                if sell_ok:
                    target = -pos_cap
                elif buy_ok:
                    target = pos_cap
                elif abs(deviation) <= c.flat_gap:
                    target = 0

        pos, cash_delta, qty = _trade_to_target(row, pos, target, c.step)
        cash += cash_delta
        if qty:
            trades += 1
            abs_qty += qty
        pnl_path.append(cash + pos * mid)

    path = pd.Series(pnl_path)
    dd = path - path.cummax()
    return Row(
        candidate=c.name,
        family=c.family,
        day=int(h.attrs.get("day", 0)),
        pnl=float(path.iloc[-1]),
        peak=float(path.max()),
        max_dd=float(dd.min()),
        final_pos=pos,
        trades=trades,
        abs_qty=abs_qty,
    )


def _candidates() -> list[Candidate]:
    out: list[Candidate] = []
    for mu in (9986, 9988, 9990, 9992):
        for entry in (26, 28, 30, 32, 35):
            for reset in (6, 8, 10, 12):
                out.append(Candidate(f"cycle_mu{mu}_e{entry}_r{reset}", "cycle", mu=mu, entry=entry, reset=reset))
    for mu in (9986, 9988, 9990):
        for entry in (24, 28, 32):
            for w in (5, 10, 20, 50):
                for gate in (0, 1, 2, 4):
                    out.append(
                        Candidate(
                            f"turn_mu{mu}_e{entry}_w{w}_g{gate}",
                            "reversal",
                            mu=mu,
                            entry=entry,
                            reset=8,
                            confirm="turn",
                            slope_window=w,
                            slope_gate=gate,
                        )
                    )
    for mu in (9986, 9988, 9990):
        for entry in (24, 28, 32):
            for w in (5, 10, 20, 50):
                for gate in (0, 1, 2, 4):
                    out.append(
                        Candidate(
                            f"trend_mu{mu}_e{entry}_w{w}_g{gate}",
                            "reversal",
                            mu=mu,
                            entry=entry,
                            reset=8,
                            confirm="trend",
                            slope_window=w,
                            slope_gate=gate,
                        )
                    )
    for window in (100, 250, 500, 1000, 2000):
        for offset in (-20, -10, 0, 10, 20):
            for entry in (20, 25, 30, 35):
                out.append(
                    Candidate(
                        f"roll_w{window}_off{offset}_e{entry}",
                        "rolling",
                        entry=entry,
                        reset=8,
                        rolling_window=window,
                        rolling_offset=offset,
                    )
                )
    for mu in (9986, 9988, 9990):
        for entry in (18, 22, 26):
            for vm in (1.0, 1.5, 2.0, 3.0):
                out.append(Candidate(f"vol_mu{mu}_e{entry}_vm{vm}", "vol_band", mu=mu, entry=entry, reset=8, vol_mult=vm))
    return out


def run() -> pd.DataFrame:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    days = []
    for day in (0, 1, 2):
        h = _load_day(day)
        h.attrs["day"] = day
        days.append(h)

    rows: list[Row] = []
    for c in _candidates():
        for h in days:
            rows.append(simulate(h, c))
    df = pd.DataFrame([asdict(row) for row in rows])
    df.to_csv(OUT_DIR / "all_results.csv", index=False)
    _summarize(df)
    return df


def _summarize(df: pd.DataFrame) -> None:
    pnl = df.pivot_table(index=["candidate", "family"], columns="day", values="pnl")
    dd = df.pivot_table(index=["candidate", "family"], columns="day", values="max_dd")
    out = pnl.reset_index()
    out["mean"] = pnl.mean(axis=1).to_numpy()
    out["min"] = pnl.min(axis=1).to_numpy()
    out["max"] = pnl.max(axis=1).to_numpy()
    out["worst_dd"] = dd.min(axis=1).to_numpy()
    out["score"] = out["mean"] + 0.8 * out["min"] + 0.15 * out["worst_dd"]
    out = out.sort_values("score", ascending=False)
    out.to_csv(OUT_DIR / "ranked_summary.csv", index=False)


def main() -> None:
    df = run()
    ranked = pd.read_csv(OUT_DIR / "ranked_summary.csv")
    print(f"Wrote {len(df)} rows to {OUT_DIR}")
    print(ranked.head(60).to_string(index=False))
    print("\nBest by family:")
    print(ranked.groupby("family").head(5).sort_values(["family", "score"], ascending=[True, False]).to_string(index=False))


if __name__ == "__main__":
    main()

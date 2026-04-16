"""Recover server-side fair value from a hold-1 submission's activity log.

IMC Prosperity marks every position to a server-side continuous fair
value each tick. A trader holding exactly one unit of product P with
known entry price ``buy_price`` therefore has:

    pnl_P(t)  =  1 * (server_fv_P(t) - buy_price)
    server_fv_P(t)  =  pnl_P(t) + buy_price

The hold-one trader (``outputs/submissions/calibration/trader_hold_one.py``)
guarantees this contract for every product visible at t=0. This module
parses the activity log JSON, identifies the entry price per product,
and emits per-tick fact tables joining recovered fair value with the
order book snapshot.

Format compatibility:
    IMC's activity log JSON has evolved across rounds. This module
    handles two known shapes:
      1. ``activityLogs`` = list[dict], one record per (day, ts, product)
      2. ``activityLogs`` = str (semicolon-separated CSV with header)
    Trade history is similarly parsed from either dict-list or CSV str.

If the file shape doesn't match either, a clear error names what was
found vs expected so the format can be adjusted.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from src.analysis.calibration.types import BookLevel, FactRow, TradeRow

LOGGER = logging.getLogger(__name__)


# ----------------------------------------------------------- public API


def load_activity_log(path: Path) -> dict[str, Any]:
    """Load the raw IMC activity-log JSON file.

    Returns the parsed dict so callers can inspect non-standard fields
    if needed.
    """
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse {path} as JSON. Is this an IMC activity log? "
            f"First 200 chars: {text[:200]!r}"
        ) from exc


def extract_book_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pull per-(day, timestamp, product) book snapshots from the log.

    Returns a list of dicts with normalized field names. The IMC log
    may store activity logs as either a list of dicts or as a
    semicolon-delimited CSV string; both are handled here.
    """
    raw = _find_activity_logs(payload)
    if isinstance(raw, list):
        records = [_normalize_book_dict(row) for row in raw]
    elif isinstance(raw, str):
        records = list(_parse_csv_records(raw))
    else:
        raise ValueError(
            f"activityLogs has unexpected type {type(raw).__name__}; "
            "expected list[dict] or str."
        )
    if not records:
        raise ValueError("Activity log contains zero book records.")
    return records


def extract_trade_records(payload: Mapping[str, Any]) -> list[TradeRow]:
    """Pull market-trade events from the log."""
    raw = _find_trade_history(payload)
    if raw is None:
        return []
    if isinstance(raw, list):
        return [_normalize_trade_dict(row) for row in raw]
    if isinstance(raw, str):
        return list(_parse_trade_csv(raw))
    raise ValueError(
        f"tradeHistory has unexpected type {type(raw).__name__}; "
        "expected list[dict] or str."
    )


def build_fact_table(
    records: Sequence[Mapping[str, Any]],
    *,
    own_trade_records: Sequence[TradeRow] | None = None,
    bot_seat: str = "SUBMISSION",
    mode: str = "auto",
) -> dict[str, list[FactRow]]:
    """Join book snapshots with recovered server fair value per product.

    Two recovery modes:

    ``hold_one`` — fast path for the dedicated hold-1 trader. Assumes
        the trader bought 1 unit at t=0 and held forever.
        ``server_fv(t) = pnl(t) + buy_price``.

    ``general`` — works for any submission with own trades. Reconstructs
        cash and position per product from the trade history, then
        recovers ``server_fv(t) = (pnl(t) - cash(t)) / position(t)`` at
        every tick where position != 0. Ticks with position == 0 are
        dropped (FV unrecoverable).

    ``auto`` (default) — picks ``hold_one`` if every own trade is a
        single buy of qty 1 at t=0 with no further trades, otherwise
        ``general``.
    """
    by_product: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        product = row["product"]
        by_product.setdefault(product, []).append(row)

    own_trades = list(own_trade_records or [])
    resolved_mode = _resolve_mode(mode, own_trades=own_trades, bot_seat=bot_seat)
    LOGGER.info("FV recovery mode: %s", resolved_mode)

    facts: dict[str, list[FactRow]] = {}
    for product, rows in by_product.items():
        rows_sorted = sorted(rows, key=lambda r: (r["day"], r["timestamp"]))
        if resolved_mode == "hold_one":
            product_facts = _build_hold_one_facts(
                rows_sorted, product=product,
                own_trades=own_trades, bot_seat=bot_seat,
            )
        else:
            product_facts = _build_general_facts(
                rows_sorted, product=product,
                own_trades=own_trades, bot_seat=bot_seat,
            )
        facts[product] = product_facts
        if product_facts:
            LOGGER.info(
                "Built fact table for %s: %d/%d ticks recoverable, "
                "fv range=[%.4f, %.4f]",
                product,
                len(product_facts),
                len(rows_sorted),
                min(f.server_fv for f in product_facts),
                max(f.server_fv for f in product_facts),
            )
        else:
            LOGGER.warning(
                "No usable fact rows for %s — trader had position == 0 "
                "for every tick, or own-trade detection failed (no trade "
                "matched bot_seat=%r).",
                product,
                bot_seat,
            )
    return facts


def _resolve_mode(
    mode: str,
    *,
    own_trades: Sequence[TradeRow],
    bot_seat: str,
) -> str:
    """Pick a recovery mode automatically when ``mode='auto'``."""
    if mode == "hold_one":
        return "hold_one"
    if mode == "general":
        return "general"
    if mode != "auto":
        raise ValueError(f"Unknown mode {mode!r}; expected hold_one/general/auto.")
    own = [t for t in own_trades if _is_own_trade(t, bot_seat=bot_seat)]
    if not own:
        # No own trades detected — fall through to hold_one fallback path
        # (which uses t=0 best_ask as a guess).
        return "hold_one"
    is_hold_one = (
        all(t.timestamp == 0 for t in own)
        and all(_signed_qty(t, bot_seat) == 1 for t in own)
    )
    return "hold_one" if is_hold_one else "general"


def _build_hold_one_facts(
    rows_sorted: Sequence[Mapping[str, Any]],
    *,
    product: str,
    own_trades: Sequence[TradeRow],
    bot_seat: str,
) -> list[FactRow]:
    """Hold-one fast path: server_fv(t) = pnl(t) + buy_price."""
    own_buy_prices = _recover_entry_prices(own_trades, expected_bot=bot_seat)
    buy_price = own_buy_prices.get(product)
    if buy_price is None:
        buy_price = _first_best_ask(rows_sorted, product)
    out: list[FactRow] = []
    for row in rows_sorted:
        pnl = row["profit_and_loss"]
        server_fv = pnl + buy_price
        out.append(FactRow(
            timestamp=row["timestamp"], product=product, server_fv=server_fv,
            bids=_levels(row, side="bid"), asks=_levels(row, side="ask"),
            mid_price=row.get("mid_price"), pnl=pnl,
        ))
    return out


def _build_general_facts(
    rows_sorted: Sequence[Mapping[str, Any]],
    *,
    product: str,
    own_trades: Sequence[TradeRow],
    bot_seat: str,
) -> list[FactRow]:
    """General path: server_fv(t) = (pnl(t) - cash(t)) / position(t).

    Reconstructs (cash, position) trajectories from the own-trade stream
    by replaying trades in timestamp order. Skips ticks where the
    reconstructed position is zero (FV unrecoverable on those ticks).

    Sign convention:
        - Own buy:  position += qty,  cash -= price * qty
        - Own sell: position -= qty,  cash += price * qty
    """
    product_trades = sorted(
        [t for t in own_trades if t.product == product
         and _is_own_trade(t, bot_seat=bot_seat)],
        key=lambda t: t.timestamp,
    )
    out: list[FactRow] = []
    trade_idx = 0
    cash = 0.0
    position = 0
    skipped_zero_pos = 0
    for row in rows_sorted:
        ts = row["timestamp"]
        # Apply every own trade with timestamp <= current row's timestamp.
        while trade_idx < len(product_trades) and product_trades[trade_idx].timestamp <= ts:
            tr = product_trades[trade_idx]
            qty_signed = _signed_qty(tr, bot_seat)
            cash -= qty_signed * tr.price  # buys reduce cash, sells increase
            position += qty_signed
            trade_idx += 1
        if position == 0:
            skipped_zero_pos += 1
            continue
        pnl = row["profit_and_loss"]
        server_fv = (pnl - cash) / position
        out.append(FactRow(
            timestamp=ts, product=product, server_fv=server_fv,
            bids=_levels(row, side="bid"), asks=_levels(row, side="ask"),
            mid_price=row.get("mid_price"), pnl=pnl,
        ))
    if skipped_zero_pos:
        LOGGER.info(
            "%s general-mode: skipped %d ticks with position==0 "
            "(FV unrecoverable). %d trades replayed, final position=%d, "
            "final cash=%.2f.",
            product, skipped_zero_pos, len(product_trades), position, cash,
        )
    return out


def _is_own_trade(trade: TradeRow, *, bot_seat: str) -> bool:
    """True iff the trader-of-interest is one side of this trade."""
    return trade.buyer == bot_seat or trade.seller == bot_seat


def _signed_qty(trade: TradeRow, bot_seat: str) -> int:
    """+qty if we bought, -qty if we sold."""
    if trade.buyer == bot_seat:
        return abs(trade.quantity)
    if trade.seller == bot_seat:
        return -abs(trade.quantity)
    raise ValueError(
        f"Trade at t={trade.timestamp} has neither buyer nor seller "
        f"matching bot_seat={bot_seat!r}: buyer={trade.buyer!r}, "
        f"seller={trade.seller!r}"
    )


def filter_trades_by_product(
    trades: Sequence[TradeRow],
) -> dict[str, list[TradeRow]]:
    """Group trades by product symbol, preserving order."""
    out: dict[str, list[TradeRow]] = {}
    for trade in trades:
        out.setdefault(trade.product, []).append(trade)
    return out


def load_trades_csv(path: Path) -> list[TradeRow]:
    """Parse an IMC ``trades_round_*_day_*.csv`` file into TradeRow records.

    The CSV header is:
        timestamp;buyer;seller;symbol;currency;price;quantity

    Buyer/seller fields are typically empty in market-trade CSVs (the
    book is anonymized — only the player's own trades carry the team
    seat in the buyer/seller fields). Downstream consumers must infer
    trade direction from price relative to fair value, not from the
    buyer/seller fields alone.
    """
    rows: list[TradeRow] = []
    with path.open() as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for raw in reader:
            try:
                rows.append(TradeRow(
                    timestamp=int(raw["timestamp"]),
                    product=raw["symbol"],
                    price=int(float(raw["price"])),
                    quantity=int(raw["quantity"]),
                    buyer=raw.get("buyer") or None,
                    seller=raw.get("seller") or None,
                ))
            except (KeyError, ValueError) as exc:
                LOGGER.warning(
                    "Skipping malformed trade row in %s: %r (%s)",
                    path, raw, exc,
                )
    LOGGER.info("Loaded %d trades from %s", len(rows), path)
    return rows


# ----------------------------------------------------------- internals


_BOOK_KEY_CANDIDATES = ("activityLogs", "activitiesLog", "activitiesLogs", "activityLog")
_TRADE_KEY_CANDIDATES = ("tradeHistory", "tradesHistory", "trades", "tradeLog")


def _find_activity_logs(payload: Mapping[str, Any]) -> Any:
    for key in _BOOK_KEY_CANDIDATES:
        if key in payload:
            return payload[key]
    raise ValueError(
        f"No activity-log field found. Looked for: {_BOOK_KEY_CANDIDATES}. "
        f"Top-level keys present: {sorted(payload.keys())}"
    )


def _find_trade_history(payload: Mapping[str, Any]) -> Any:
    for key in _TRADE_KEY_CANDIDATES:
        if key in payload:
            return payload[key]
    LOGGER.info(
        "No trade-history field found in payload (looked for %s). "
        "Returning empty trade list.",
        _TRADE_KEY_CANDIDATES,
    )
    return None


def _parse_csv_records(blob: str) -> Iterable[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(blob), delimiter=";")
    for raw_row in reader:
        yield _normalize_book_dict(raw_row)


def _parse_trade_csv(blob: str) -> Iterable[TradeRow]:
    reader = csv.DictReader(io.StringIO(blob), delimiter=";")
    for raw_row in reader:
        yield _normalize_trade_dict(raw_row)


def _normalize_book_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    """Coerce field names + numeric types from the IMC log shape."""
    out: dict[str, Any] = {
        "day": _as_int(row.get("day", 0)),
        "timestamp": _as_int(_first_present(row, ("timestamp", "ts"))),
        "product": str(_first_present(row, ("product", "symbol"))),
        "mid_price": _as_float_or_none(row.get("mid_price")),
        "profit_and_loss": _as_float(
            _first_present(row, ("profit_and_loss", "pnl", "pnL"))
        ),
    }
    for side in ("bid", "ask"):
        for level in (1, 2, 3):
            price_key = f"{side}_price_{level}"
            volume_key = f"{side}_volume_{level}"
            out[price_key] = _as_int_or_none(row.get(price_key))
            out[volume_key] = _as_int_or_none(row.get(volume_key))
    return out


def _normalize_trade_dict(row: Mapping[str, Any]) -> TradeRow:
    return TradeRow(
        timestamp=_as_int(_first_present(row, ("timestamp", "ts"))),
        product=str(_first_present(row, ("symbol", "product"))),
        price=_as_int(_first_present(row, ("price",))),
        quantity=_as_int(_first_present(row, ("quantity", "qty", "amount"))),
        buyer=_as_str_or_none(row.get("buyer")),
        seller=_as_str_or_none(row.get("seller")),
    )


def _first_present(row: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in ("", None):
            return row[key]
    raise KeyError(f"None of {keys} present in row {dict(row)}")


def _levels(row: Mapping[str, Any], *, side: str) -> tuple[BookLevel, ...]:
    out: list[BookLevel] = []
    for level in (1, 2, 3):
        price = row.get(f"{side}_price_{level}")
        volume = row.get(f"{side}_volume_{level}")
        if price is None or volume is None or volume == 0:
            continue
        out.append(BookLevel(price=int(price), volume=abs(int(volume))))
    return tuple(out)


def _recover_entry_prices(
    trades: Sequence[TradeRow], *, expected_bot: str
) -> dict[str, float]:
    """For each product, find the first own-buy and record its price.

    Identifies own trades by buyer or seller field equal to
    ``expected_bot`` (IMC labels them as e.g. 'SUBMISSION').
    """
    out: dict[str, float] = {}
    for trade in trades:
        if trade.product in out:
            continue
        if trade.buyer == expected_bot or trade.seller == expected_bot:
            # We bought (we are the buyer): entry price = trade.price.
            if trade.buyer == expected_bot and trade.quantity > 0:
                out[trade.product] = float(trade.price)
    return out


def _first_best_ask(
    rows: Sequence[Mapping[str, Any]], product: str
) -> float:
    for row in rows:
        ask = row.get("ask_price_1")
        if ask is not None:
            return float(ask)
    raise ValueError(
        f"Cannot infer entry price for {product}: no ask_price_1 found "
        "in any tick of the activity log."
    )


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError(f"unexpected boolean: {value!r}")
    return int(value)


def _as_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _as_float(value: Any) -> float:
    return float(value)


def _as_float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _as_str_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)

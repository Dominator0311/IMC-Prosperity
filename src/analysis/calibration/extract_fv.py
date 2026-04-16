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
) -> dict[str, list[FactRow]]:
    """Join book snapshots with recovered server fair value per product.

    ``own_trade_records`` (if provided) is scanned for the buy price
    of the hold-one entry per product. Falls back to using the best_ask
    at the first observed timestamp for that product.
    """
    by_product: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        product = row["product"]
        by_product.setdefault(product, []).append(row)

    own_buy_prices = _recover_entry_prices(
        own_trade_records or [], expected_bot=bot_seat
    )

    facts: dict[str, list[FactRow]] = {}
    for product, rows in by_product.items():
        rows_sorted = sorted(rows, key=lambda r: (r["day"], r["timestamp"]))
        buy_price = own_buy_prices.get(product)
        if buy_price is None:
            # Fall back to t0 best_ask (the hold-one trader buys there).
            buy_price = _first_best_ask(rows_sorted, product)
        product_facts: list[FactRow] = []
        for row in rows_sorted:
            pnl = row["profit_and_loss"]
            server_fv = pnl + buy_price
            product_facts.append(
                FactRow(
                    timestamp=row["timestamp"],
                    product=product,
                    server_fv=server_fv,
                    bids=_levels(row, side="bid"),
                    asks=_levels(row, side="ask"),
                    mid_price=row.get("mid_price"),
                    pnl=pnl,
                )
            )
        facts[product] = product_facts
        LOGGER.info(
            "Built fact table for %s: %d ticks, buy_price=%.2f, "
            "fv range=[%.4f, %.4f]",
            product,
            len(product_facts),
            buy_price,
            min(f.server_fv for f in product_facts),
            max(f.server_fv for f in product_facts),
        )
    return facts


def filter_trades_by_product(
    trades: Sequence[TradeRow],
) -> dict[str, list[TradeRow]]:
    """Group trades by product symbol, preserving order."""
    out: dict[str, list[TradeRow]] = {}
    for trade in trades:
        out.setdefault(trade.product, []).append(trade)
    return out


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

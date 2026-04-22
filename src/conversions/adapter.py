"""Adapter: ``TradingState.observations.conversionObservations`` → ``RemoteQuote``.

The Prosperity container exposes cross-exchange quotes via
``TradingState.observations.conversionObservations[product]`` as a
``ConversionObservation`` carrying:

    bidPrice, askPrice, transportFees, exportTariff, importTariff,
    sunlight, humidity

The engines work in terms of ``RemoteQuote(bid, ask)`` (a minimal view)
plus tariff/transport fees carried on ``ConversionSpec`` (tariffs vary
per tick in IMC scenarios). This adapter:

1. Extracts a ``RemoteQuote`` per product.
2. Extracts per-product tariff overrides so ``StatArbEngine`` sees the
   current tick's actual numbers (not a frozen config snapshot).
3. Extracts the raw external signal (sunlight / humidity / sugarPrice)
   for downstream ``SignalBus`` emission.

Design notes:

- **Pure functions.** No stored state — the adapter is called on every
  tick from ``Trader.run``.
- **Empty-input safe.** Products with no conversion observation are
  simply absent from the returned mapping (downstream engines check
  ``portfolio.remote_for(p) is None``).
- **Non-breaking.** If ``observations`` is None or has no
  ``conversionObservations`` attribute, returns empty mappings. This
  lets unit tests pass a bare ``TradingState`` without observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from src.conversions.layer import ConversionSpec, RemoteQuote
from src.datamodel import ConversionObservation, TradingState


@dataclass(frozen=True)
class ConversionTick:
    """Per-product tick-level conversion data extracted from observations.

    The engine pulls ``remote`` for the arb edge, ``tariff_overrides`` to
    clone its ``ConversionSpec`` with current values, and ``signals`` for
    regime detection.
    """

    remote: RemoteQuote
    tariff_overrides: ConversionSpec
    signals: dict[str, float]


def extract_conversion_ticks(
    state: TradingState,
    *,
    base_specs: Mapping[str, ConversionSpec] | None = None,
) -> dict[str, ConversionTick]:
    """Build per-product ``ConversionTick`` from the raw TradingState.

    ``base_specs`` provides the default ``ConversionSpec`` per product
    (mainly for ``conv_cap_per_tick`` + ``storage_cost`` which are NOT
    in the observation — they're static competition parameters). The
    adapter overrides ``transport_fee``, ``import_tariff``,
    ``export_tariff`` from the current tick's observation.

    Returns empty dict if observations are absent.
    """
    observations = getattr(state, "observations", None)
    if observations is None:
        return {}
    conv_map = getattr(observations, "conversionObservations", None)
    if not conv_map:
        return {}

    out: dict[str, ConversionTick] = {}
    for product, obs in conv_map.items():
        if not isinstance(obs, ConversionObservation):
            # Defensive: external code may mis-populate observations.
            continue
        base = (base_specs or {}).get(product) or ConversionSpec()
        try:
            remote = RemoteQuote(bid=float(obs.bidPrice), ask=float(obs.askPrice))
        except (TypeError, ValueError):
            continue
        try:
            tariff_overrides = ConversionSpec(
                transport_fee=float(obs.transportFees),
                import_tariff=float(obs.importTariff),
                export_tariff=float(obs.exportTariff),
                storage_cost=base.storage_cost,
                conv_cap_per_tick=base.conv_cap_per_tick,
            )
        except (TypeError, ValueError):
            # Malformed observation: fall back to the static base spec.
            tariff_overrides = base

        # Raw external signals — the engine decides which to consume via
        # its config.external_signal_name. Both sunlight & humidity are
        # published in case multiple engines consume them.
        signals: dict[str, float] = {}
        for attr in ("sunlight", "humidity"):
            val = getattr(obs, attr, None)
            if val is None:
                continue
            try:
                signals[attr] = float(val)
            except (TypeError, ValueError):
                continue

        out[product] = ConversionTick(
            remote=remote,
            tariff_overrides=tariff_overrides,
            signals=signals,
        )
    return out


def extract_remote_quotes(state: TradingState) -> dict[str, RemoteQuote]:
    """Convenience: just the ``RemoteQuote`` map.

    Callers who don't need tariff overrides or signals use this. The
    ``PortfolioSnapshot`` ``remote_quotes`` field is populated from here.
    """
    return {p: t.remote for p, t in extract_conversion_ticks(state).items()}

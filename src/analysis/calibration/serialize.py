"""Serialize calibration results to JSON and human-readable Markdown.

Two output formats:

    fits.json              — machine-readable, all fitted parameters
    calibration_report.md  — human-readable summary tables

Pure functions; both serializers take a frozen ProductCalibration and
return strings (the caller does the file I/O).
"""
from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence

from src.analysis.calibration.types import ProductCalibration


def calibration_to_json(
    calibrations: Sequence[ProductCalibration], *, indent: int = 2
) -> str:
    """Convert a sequence of ProductCalibration objects to JSON."""
    payload = {
        c.product: _calibration_to_dict(c) for c in calibrations
    }
    return json.dumps(payload, indent=indent, sort_keys=True)


def calibration_to_markdown(
    calibrations: Sequence[ProductCalibration]
) -> str:
    """Render a Markdown report summarizing fits per product."""
    lines: list[str] = ["# Calibration report", ""]
    for cal in calibrations:
        lines.extend(_product_section(cal))
        lines.append("")
    return "\n".join(lines)


# ----------------------------------------------------------- internals


def _calibration_to_dict(cal: ProductCalibration) -> dict:
    return {
        "product": cal.product,
        "n_ticks": cal.n_ticks,
        "fair_value": dataclasses.asdict(cal.fair_value),
        "depth_bands": [dataclasses.asdict(b) for b in cal.depth_bands],
        "quote_rules": [dataclasses.asdict(r) for r in cal.quote_rules],
        "volume_fits": [dataclasses.asdict(v) for v in cal.volume_fits],
        "trade_arrivals": dataclasses.asdict(cal.trade_arrivals),
        "trade_sizes_buy": dataclasses.asdict(cal.trade_sizes_buy),
        "trade_sizes_sell": dataclasses.asdict(cal.trade_sizes_sell),
        "trade_locations_buy": dataclasses.asdict(cal.trade_locations_buy),
        "trade_locations_sell": dataclasses.asdict(cal.trade_locations_sell),
        "metadata": dict(cal.metadata),
    }


def _product_section(cal: ProductCalibration) -> list[str]:
    lines = [f"## {cal.product}", ""]
    lines.append(f"- Ticks: **{cal.n_ticks}**")
    fair = cal.fair_value
    lines.append(
        f"- Fair value: sigma=**{fair.sigma:.4f}**, "
        f"mean_return=**{fair.mean_return:+.4f}**, "
        f"phi=**{fair.ar1_phi:+.3f}** "
        f"(SE {fair.ar1_phi_se:.3f}, n={fair.n_returns})"
    )
    if fair.quantization_grid is not None:
        lines.append(
            f"- Quantization grid: **{fair.quantization_grid:.6f}**"
        )
    lines.append(
        f"- FV range: [{fair.fv_min:.2f}, {fair.fv_max:.2f}]"
    )
    lines.append("")
    lines.append("### Variance ratio (target: 1.0 for random walk)")
    lines.append("")
    lines.append("| k | VR(k) |")
    lines.append("|---:|---:|")
    for k, vr in zip(fair.vr_horizons, fair.variance_ratio):
        lines.append(f"| {k} | {vr:.3f} |")
    lines.append("")
    lines.append("### Depth bands")
    lines.append("")
    lines.append("| name | side | offset_min | offset_max | presence |")
    lines.append("|---|---|---:|---:|---:|")
    for band in cal.depth_bands:
        lines.append(
            f"| {band.name} | {band.side} | "
            f"{band.offset_min:+.2f} | {band.offset_max:+.2f} | "
            f"{band.presence_rate:.1%} |"
        )
    lines.append("")
    lines.append("### Quote rules (best-match formula per band)")
    lines.append("")
    lines.append("| bot | side | formula | match | n |")
    lines.append("|---|---|---|---:|---:|")
    for rule in cal.quote_rules:
        formula = (
            f"{rule.round_fn}(fv {rule.shift:+.2f}) {rule.offset:+d}"
        )
        lines.append(
            f"| {rule.bot_name} | {rule.side} | `{formula}` | "
            f"{rule.match_rate:.1%} | {rule.n_samples} |"
        )
    lines.append("")
    lines.append("### Volume fits")
    lines.append("")
    lines.append("| bot | side | min | max | n | chi^2 | p_uniform |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for vol in cal.volume_fits:
        p_str = f"{vol.p_value_uniform:.3f}" if vol.p_value_uniform == vol.p_value_uniform else "n/a"
        lines.append(
            f"| {vol.bot_name} | {vol.side} | {vol.min_volume} | "
            f"{vol.max_volume} | {vol.n_samples} | "
            f"{vol.chi_squared:.2f} | {p_str} |"
        )
    lines.append("")
    arr = cal.trade_arrivals
    lines.append("### Trade arrivals")
    lines.append("")
    lines.append(
        f"- p_active per tick: **{arr.p_active:.4f}** "
        f"({arr.n_ticks_active}/{arr.n_ticks_total})"
    )
    lines.append(f"- p_buy | active: **{arr.p_buy_given_active:.4f}**")
    lines.append(f"- total trades: {arr.n_trades_total}")
    lines.append(f"- KS vs geometric (gap survival): {arr.geometric_ks_stat:.4f}")
    lines.append("")
    lines.append("### Trade sizes")
    lines.append("")
    for fit, label in (
        (cal.trade_sizes_buy, "buy"),
        (cal.trade_sizes_sell, "sell"),
    ):
        lines.append(f"**{label}** (n={fit.n_samples}):")
        if fit.n_samples == 0:
            lines.append("  - (no trades)")
        else:
            for size, prob in zip(fit.sizes, fit.probabilities):
                lines.append(f"  - size {size}: {prob:.3f}")
        lines.append("")
    return lines

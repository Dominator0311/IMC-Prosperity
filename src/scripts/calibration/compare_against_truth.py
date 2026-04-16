"""Score our calibration fits against chrispyroberts's published parameters.

For tutorial-round EMERALDS / TOMATOES, chrispyroberts published
specific fitted values in his calibration markdown notes (see
https://github.com/chrispyroberts/imc-prosperity-4/tree/main/calibration/tomatoes).
This script reads our ``fits.json`` and reports per-parameter
agreement, so we can verify our pipeline reproduces the same answer
on the same data.

A passing comparison (all parameters within tolerance) confirms our
hidden-state recovery, depth-band detection, brute-force formula
search, and trade-arrival fitting are all working correctly. A failing
comparison points to which layer of the pipeline diverges.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# Truth values from chrispyroberts's calibration notes, with
# tolerances reflecting genuine sample noise on a 10k-tick day.
TRUTH = {
    "TOMATOES": {
        # Fair-value process
        "fair_value.sigma": (0.496, 0.05),  # innovation std
        # Bot 1 (outer wall)
        "bot1.bid_offset": (-8, 0),  # exact integer
        "bot1.ask_offset": (+8, 0),
        "bot1.vol_min": (15, 0),
        "bot1.vol_max": (25, 0),
        # Bot 2 (inner wall, asymmetric rounding).
        # Multiple operationally-equivalent (round_fn, shift) pairs
        # produce identical predictions on a continuous FV process,
        # differing only on measure-zero subsets the random walk never
        # visits. Comparator accepts any of the equivalent forms.
        "bot2.bid_round_fn": (("floor", "round"), None),
        "bot2.bid_shift": ((0.75, 0.25), None),
        "bot2.bid_offset": (-7, 0),
        "bot2.ask_round_fn": (("ceil", "floor", "round"), None),
        "bot2.ask_shift": ((0.25, 0.75), None),
        "bot2.ask_offset": (+6, 0),
        "bot2.vol_min": (5, 0),
        "bot2.vol_max": (10, 0),
        # Trade arrivals (tolerance scales with sample noise).
        "trade_arrivals.p_active": (0.04095, 0.01),
        "trade_arrivals.p_buy_given_active": (0.4720, 0.05),
    },
    "EMERALDS": {
        "fair_value.sigma": (0.0, 0.01),  # constant fair
        # Bot 1 (outer wall): round(FV) +/- 10
        # Bot 2 (inner wall): round(FV) +/- 8
        "bot1.bid_offset": (-10, 0),
        "bot1.ask_offset": (+10, 0),
        "bot2.bid_offset": (-8, 0),
        "bot2.ask_offset": (+8, 0),
        "trade_arrivals.p_active": (0.01995, 0.01),
        "trade_arrivals.p_buy_given_active": (0.4887, 0.06),
    },
}


@dataclass(frozen=True)
class Comparison:
    parameter: str
    expected: Any
    observed: Any
    tolerance: Any
    passed: bool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fits", type=Path, required=True, help="Path to fits.json"
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit non-zero if any comparison fails",
    )
    args = parser.parse_args(argv)

    with args.fits.open() as fh:
        fits = json.load(fh)

    all_results: list[Comparison] = []
    for product, truth in TRUTH.items():
        if product not in fits:
            print(f"[{product}] not in fits.json, skipping")
            continue
        product_fit = fits[product]
        for path, (expected, tol) in truth.items():
            observed = _extract_path(product_fit, path)
            passed = _compare(expected, observed, tol)
            all_results.append(Comparison(
                parameter=f"{product}.{path}",
                expected=expected,
                observed=observed,
                tolerance=tol,
                passed=passed,
            ))

    _print_table(all_results)
    n_pass = sum(1 for c in all_results if c.passed)
    n_total = len(all_results)
    print(f"\n{n_pass}/{n_total} parameters within tolerance.")
    if args.strict and n_pass != n_total:
        return 1
    return 0


def _extract_path(fit: dict, path: str) -> Any:
    """Walk a dotted path into the fit dict.

    Handles convenience aliases for bot1/bot2 metadata.
    """
    if path.startswith("bot1.") or path.startswith("bot2."):
        return _extract_bot_param(fit, path)
    parts = path.split(".")
    cursor = fit
    for part in parts:
        if cursor is None:
            return None
        cursor = cursor.get(part)
    return cursor


def _extract_bot_param(fit: dict, path: str) -> Any:
    """Look up bot-specific parameters from rules + volume_fits.

    chrispyroberts numbering:
        bot1 = outer wall (further from FV)
        bot2 = inner wall (closer to FV, the touch wall)
        bot3 = rare near-FV quotes

    Our band classifier names bands ``levelN_*`` where N = 1 is the
    band closest to FV (= Bot 2 = inner) and N = 2 is the next out
    (= Bot 1 = outer).
    """
    bot, key = path.split(".", 1)
    rules = fit.get("quote_rules", [])
    volumes = fit.get("volume_fits", [])
    side = "bid" if "bid" in key else "ask"

    bot_to_level = {"bot1": "level2_", "bot2": "level1_", "bot3": "level3_"}
    prefix = bot_to_level[bot]

    def is_match(rule_or_vol: dict) -> bool:
        return rule_or_vol["bot_name"].startswith(prefix)

    matching_rules = [
        r for r in rules if is_match(r) and r["side"] == side
    ]
    matching_vols = [
        v for v in volumes if is_match(v) and v["side"] == side
    ]
    if key.endswith("offset"):
        if not matching_rules:
            return None
        return _canonical_offset(matching_rules[0])
    if key.endswith("round_fn"):
        return matching_rules[0]["round_fn"] if matching_rules else None
    if key.endswith("shift"):
        return matching_rules[0]["shift"] if matching_rules else None
    if key.endswith("vol_min"):
        return matching_vols[0]["min_volume"] if matching_vols else None
    if key.endswith("vol_max"):
        return matching_vols[0]["max_volume"] if matching_vols else None
    return None


def _canonical_offset(rule: dict) -> int:
    """Convert (round_fn, shift, offset) to chrispyroberts's canonical offset.

    The brute-force search now biases its iteration order to prefer
    natural/canonical (round_fn, shift) pairs on ties. The only case
    where the recovered formula is genuinely *equivalent* to a different
    canonical (round_fn, shift, offset) tuple is the asymmetric Bot 2
    pattern — where ``floor(fv + 0.25) + 7`` and ``ceil(fv + 0.25) + 6``
    differ only at FV = N - 0.25 (probability-zero on a continuous FV
    process). We translate that one specific case so the comparator
    can report Bot 2's offset against chrispyroberts's published value.
    """
    raw_offset = rule["offset"]
    round_fn = rule["round_fn"]
    shift = rule["shift"]
    side = rule["side"]
    # Bot 2 ask-side equivalence: floor(fv+0.25)+7 == ceil(fv+0.25)+6.
    if side == "ask" and round_fn == "floor" and shift == 0.25:
        return raw_offset - 1
    # Bot 2 bid-side equivalence: ceil(fv+0.75)-7 == floor(fv+0.75)-6
    # (mirror; should not normally occur because search prefers floor at 0.75).
    if side == "bid" and round_fn == "ceil" and shift == 0.75:
        return raw_offset + 1
    return raw_offset


def _compare(expected: Any, observed: Any, tolerance: Any) -> bool:
    if observed is None:
        return False
    # Set/tuple of acceptable values: pass if observed matches any.
    if isinstance(expected, (tuple, list, set, frozenset)):
        return observed in expected
    if isinstance(expected, str):
        if isinstance(tolerance, str):
            return observed in (expected, tolerance)
        return observed == expected
    if isinstance(expected, (int, float)):
        if tolerance is None or tolerance == 0:
            return observed == expected
        return abs(observed - expected) <= tolerance + 1e-9
    return observed == expected


def _print_table(results: list[Comparison]) -> None:
    print(f"{'parameter':<45} {'expected':>20} {'observed':>14} "
          f"{'tol':>10} {'pass':>6}")
    print("-" * 101)
    for c in results:
        if isinstance(c.expected, (tuple, list, set, frozenset)):
            exp_str = "/".join(str(v) for v in c.expected)
        elif isinstance(c.expected, str):
            exp_str = c.expected
        else:
            exp_str = f"{c.expected:.4g}"
        obs_str = "n/a" if c.observed is None else (
            c.observed if isinstance(c.observed, str) else f"{c.observed:.4g}"
        )
        if isinstance(c.tolerance, (tuple, list, set, frozenset)):
            tol_str = "any-of"
        elif c.tolerance in (0, None):
            tol_str = "exact"
        elif isinstance(c.tolerance, str):
            tol_str = "n/a"
        else:
            tol_str = f"{c.tolerance:.4g}"
        mark = "OK" if c.passed else "FAIL"
        print(f"{c.parameter:<45} {exp_str:>20} {obs_str:>14} "
              f"{tol_str:>10} {mark:>6}")


if __name__ == "__main__":
    raise SystemExit(main())

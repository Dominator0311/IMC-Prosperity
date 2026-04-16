"""End-to-end calibration runner.

Usage:

    PYTHONPATH=. .venv/bin/python -m src.scripts.calibration.run_calibration \
        --log /path/to/<submission_id>.json \
        --out outputs/calibration/tutorial_run

Reads the IMC activity-log JSON, recovers server fair value per
product, fits the FV process, identifies bot depth bands, brute-force
searches for quote-placement rules, fits trade arrival/size/location
distributions, and writes:

    <out>/fits.json
    <out>/calibration_report.md
    <out>/plots/<product>/*.png
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.analysis.calibration.bot_classifier import detect_depth_bands
from src.analysis.calibration.extract_fv import (
    build_fact_table,
    extract_book_records,
    extract_trade_records,
    filter_trades_by_product,
    load_activity_log,
)
from src.analysis.calibration.fair_value_fit import fit_fair_value_process
from src.analysis.calibration.rule_search import (
    fit_volume_distribution,
    search_quote_rule,
)
from src.analysis.calibration.serialize import (
    calibration_to_json,
    calibration_to_markdown,
)
from src.analysis.calibration.trade_fit import (
    fit_trade_arrivals,
    fit_trade_locations,
    fit_trade_sizes,
)
from src.analysis.calibration.types import ProductCalibration
from src.analysis.calibration.validate import render_all_plots

LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True, help="Activity log JSON path")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--bot-seat",
        default="SUBMISSION",
        help="String identifying our trader in the buyer/seller fields",
    )
    parser.add_argument(
        "--no-plots", action="store_true", help="Skip diagnostic plotting"
    )
    parser.add_argument(
        "-v", "--verbose", action="count", default=0, help="Logging verbosity"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    args.out.mkdir(parents=True, exist_ok=True)

    LOGGER.info("Loading activity log: %s", args.log)
    payload = load_activity_log(args.log)
    book_records = extract_book_records(payload)
    trade_records = extract_trade_records(payload)
    LOGGER.info(
        "Found %d book records, %d trade records",
        len(book_records),
        len(trade_records),
    )

    facts_by_product = build_fact_table(
        book_records, own_trade_records=trade_records, bot_seat=args.bot_seat
    )
    trades_by_product = filter_trades_by_product(trade_records)

    calibrations: list[ProductCalibration] = []
    for product, facts in facts_by_product.items():
        LOGGER.info("=== Calibrating %s (%d ticks) ===", product, len(facts))
        product_trades = trades_by_product.get(product, [])

        fair = fit_fair_value_process(facts)
        bands = detect_depth_bands(facts)
        rules = tuple(search_quote_rule(facts, b) for b in bands)
        volumes = tuple(fit_volume_distribution(facts, b) for b in bands)
        arrivals = fit_trade_arrivals(facts, product_trades)
        sizes_buy = fit_trade_sizes(product_trades, side="buy")
        sizes_sell = fit_trade_sizes(product_trades, side="sell")
        loc_buy = fit_trade_locations(facts, product_trades, side="buy")
        loc_sell = fit_trade_locations(facts, product_trades, side="sell")

        cal = ProductCalibration(
            product=product,
            n_ticks=len(facts),
            fair_value=fair,
            depth_bands=bands,
            quote_rules=rules,
            volume_fits=volumes,
            trade_arrivals=arrivals,
            trade_sizes_buy=sizes_buy,
            trade_sizes_sell=sizes_sell,
            trade_locations_buy=loc_buy,
            trade_locations_sell=loc_sell,
        )
        calibrations.append(cal)

        if not args.no_plots:
            plot_dir = args.out / "plots" / product.lower()
            LOGGER.info("Rendering plots to %s", plot_dir)
            render_all_plots(
                facts=facts,
                trades=product_trades,
                fair=fair,
                bands=bands,
                rules=rules,
                arrivals=arrivals,
                sizes_buy=sizes_buy,
                sizes_sell=sizes_sell,
                locations_buy=loc_buy,
                locations_sell=loc_sell,
                out_dir=plot_dir,
                product=product,
            )

    fits_path = args.out / "fits.json"
    fits_path.write_text(calibration_to_json(calibrations))
    LOGGER.info("Wrote %s", fits_path)

    report_path = args.out / "calibration_report.md"
    report_path.write_text(calibration_to_markdown(calibrations))
    LOGGER.info("Wrote %s", report_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

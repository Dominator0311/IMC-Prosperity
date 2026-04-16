"""Calibration tooling for IMC Prosperity products.

Reverse-engineers the hidden server-side fair value from a hold-1
diagnostic submission's PnL stream, then fits the bot quote-placement
rules and trade-arrival process from the recovered fair value plus the
recorded order-book snapshots and trade tape.

The entry point is ``src.scripts.calibration.run_calibration``. The
modules in this package are pure (no side effects beyond explicit
file I/O at the boundaries), and every fit returns a frozen dataclass
so downstream consumers cannot mutate fitted parameters.

Pipeline:

    activity log JSON  ──>  extract_fv  ──>  per-tick fact table
                                          │
                       ┌──────────────────┼─────────────────────┐
                       │                  │                     │
                  fair_value_fit    bot_classifier         trade_fit
                       │              + rule_search             │
                       └──────────────────┴─────────────────────┘
                                          │
                                       validate
                                          │
                                       artifacts
"""

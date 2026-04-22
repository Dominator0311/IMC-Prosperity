# D7 — Full F2 Pattern: Wall-Mid + Quote-Inside-Wall

Tests the convergent F2 finding: wall-mid FV + placement at `max_amt_bid + 1 / max_amt_ask - 1`, with take/clear/make flow.

**Baseline (current shipped):**

- Total: 249,375
- ASH: 9,847
- PEPPER: 239,528
- ASH trades: 681

**Inside-wall variants:**

| Variant | Total | ASH | ΔASH vs base | PEPPER | ASH trades |
|---|---|---|---|---|---|
| size=10/clear=0.5/minvol=10 | 248,731 | 9,203 | -644 | 239,528 | 646 |
| size=20/clear=0.5/minvol=10 | 248,731 | 9,203 | -644 | 239,528 | 646 |
| size=20/clear=0.7/minvol=10 | 248,747 | 9,219 | -628 | 239,528 | 645 |
| size=30/clear=0.7/minvol=10 | 248,747 | 9,219 | -628 | 239,528 | 645 |
| size=20/clear=0.5/minvol=20 | 248,731 | 9,203 | -644 | 239,528 | 646 |
| size=20/clear=0.5/minvol=5 | 248,731 | 9,203 | -644 | 239,528 | 646 |
| size=40/clear=0.7/minvol=10 | 248,747 | 9,219 | -628 | 239,528 | 645 |
| offset=0/size=20/clear=0.5 | 249,108 | 9,580 | -267 | 239,528 | 672 |
| offset=2/size=20/clear=0.5 | 249,456 | 9,928 | +81 | 239,528 | 705 |

## Interpretation

- **Best ΔASH > 1,000:** F2 pattern is correct mechanism. Build IMC test-upload bundle from the winning params.
- **Best ΔASH in [0, 500]:** marginally right direction; may need further tuning (min_wall_volume, clear_threshold, bid/ask size).
- **Best ΔASH < 0:** F2 pattern doesn't translate to our setup. Re-audit: are we really using max_amt levels correctly? Is position-limit different (80 vs top-team assumption)?

## Caveats

- Local backtest ≠ IMC simulator (F7). A positive local ΔASH is necessary but not sufficient — must upload to IMC for truth.
- We held PEPPER constant; any ΔPEPPER is incidental measurement noise.
- Position-limit interactions may differ between symmetric ladder and inside-wall patterns — watch `near_limit` steps.

# R3 Leave-One-Day-Out Validation Report

Generated: 2026-04-24T17:53:44.202556

## Gate summary

| Strategy | Gate | day0 PnL | day1 PnL | day2 PnL |
|---|---|---|---|---|
| hydrogel_mm | **PASS** | +2872 | +3488 | +2233 |
| vev_4000_mm | **PASS** | +731 | +1166 | +634 |
| velvet_hedge | **PASS** | +1217 | +1134 | +1421 |
| voucher_liquidity | **FAIL** | -66 | -64 | -78 |

## Submit gate decision

**FAILING strategies (must disable or investigate):** voucher_liquidity

These strategies are negative PnL in 2+ held-out days.
Disable them in the submission bundle OR document why the
validation failure is acceptable.

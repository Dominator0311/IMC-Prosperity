# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f3c | -237 | -31 | 696 | -1401 | +586 | 46.0% | +0.540 |

## f3c

- Sessions: **100**
- Win rate (PnL > 0): **46.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -237.469 | -31.048 | 695.826 | -1400.579 | -774.317 | +323.093 | +585.755 | -2333.635 | +795.632 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -0.256 | +0.023 | 0.822 | -1.765 | -0.763 | +0.369 | +0.660 | -2.871 | +0.851 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.540 | +0.661 | 0.325 | +0.003 | +0.200 | +0.834 | +0.931 | +0.000 | +0.978 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +15.344 | +15.113 | 5.881 | +6.764 | +10.400 | +20.572 | +24.407 | +3.336 | +26.419 |

- **Worst 5 seeds** (lowest PnL): 20260498, 20260434, 20260475, 20260417, 20260420
- **Best 5 seeds** (highest PnL): 20260507, 20260493, 20260483, 20260488, 20260469

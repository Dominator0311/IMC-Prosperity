# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f3d | -300 | -158 | 696 | -1494 | +497 | 45.0% | +0.549 |

## f3d

- Sessions: **100**
- Win rate (PnL > 0): **45.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -299.840 | -158.056 | 695.664 | -1493.986 | -777.595 | +274.629 | +497.335 | -2416.922 | +776.586 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -0.349 | -0.067 | 0.819 | -1.851 | -0.860 | +0.288 | +0.480 | -3.107 | +0.667 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.549 | +0.620 | 0.324 | +0.019 | +0.227 | +0.837 | +0.947 | +0.002 | +0.971 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +13.887 | +14.031 | 6.188 | +4.821 | +9.041 | +19.504 | +22.610 | +2.107 | +27.049 |

- **Worst 5 seeds** (lowest PnL): 20260498, 20260434, 20260430, 20260508, 20260428
- **Best 5 seeds** (highest PnL): 20260488, 20260469, 20260507, 20260514, 20260492

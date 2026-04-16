# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f2b | -393 | -188 | 828 | -1755 | +497 | 43.0% | +0.544 |

## f2b

- Sessions: **100**
- Win rate (PnL > 0): **43.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -393.338 | -187.792 | 827.677 | -1755.215 | -929.306 | +274.629 | +497.335 | -3251.031 | +776.586 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -0.444 | -0.068 | 0.991 | -2.258 | -0.969 | +0.288 | +0.480 | -4.281 | +0.667 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.544 | +0.619 | 0.326 | +0.009 | +0.227 | +0.836 | +0.936 | +0.000 | +0.971 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +15.199 | +14.304 | 7.492 | +4.821 | +9.041 | +21.068 | +26.828 | +2.107 | +32.340 |

- **Worst 5 seeds** (lowest PnL): 20260498, 20260434, 20260430, 20260508, 20260417
- **Best 5 seeds** (highest PnL): 20260488, 20260469, 20260507, 20260514, 20260492

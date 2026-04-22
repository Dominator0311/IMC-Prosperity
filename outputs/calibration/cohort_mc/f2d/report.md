# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f2d | -237 | -37 | 683 | -1268 | +539 | 48.0% | +0.542 |

## f2d

- Sessions: **100**
- Win rate (PnL > 0): **48.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -236.547 | -37.062 | 683.381 | -1267.752 | -772.404 | +308.476 | +538.642 | -2251.348 | +795.632 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | -0.262 | +0.026 | 0.804 | -1.685 | -0.782 | +0.341 | +0.609 | -2.806 | +0.748 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.542 | +0.621 | 0.321 | +0.008 | +0.257 | +0.823 | +0.938 | +0.000 | +0.978 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +15.013 | +14.842 | 5.989 | +6.334 | +9.665 | +20.404 | +24.279 | +3.336 | +26.457 |

- **Worst 5 seeds** (lowest PnL): 20260498, 20260434, 20260417, 20260430, 20260475
- **Best 5 seeds** (highest PnL): 20260507, 20260469, 20260483, 20260488, 20260493

# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f3a | +431 | +465 | 293 | -37 | +799 | 93.0% | +0.755 |

## f3a

- Sessions: **100**
- Win rate (PnL > 0): **93.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +431.221 | +465.293 | 292.867 | -36.620 | +297.932 | +597.874 | +799.302 | -894.574 | +1235.578 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.447 | +0.439 | 0.326 | -0.140 | +0.283 | +0.669 | +0.873 | -0.771 | +1.293 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.755 | +0.864 | 0.240 | +0.282 | +0.637 | +0.931 | +0.971 | +0.009 | +0.978 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +7.618 | +6.784 | 2.897 | +4.059 | +5.387 | +9.133 | +12.587 | +3.302 | +17.578 |

- **Worst 5 seeds** (lowest PnL): 20260417, 20260499, 20260498, 20260474, 20260511
- **Best 5 seeds** (highest PnL): 20260426, 20260513, 20260464, 20260419, 20260428

# Monte Carlo strategy comparison

Each strategy was run across **100 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| f2c | +394 | +408 | 239 | -45 | +717 | 93.0% | +0.787 |

## f2c

- Sessions: **100**
- Win rate (PnL > 0): **93.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +394.434 | +408.194 | 239.422 | -45.270 | +301.903 | +508.983 | +717.088 | -618.438 | +977.453 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.404 | +0.423 | 0.258 | -0.090 | +0.269 | +0.556 | +0.712 | -0.562 | +1.146 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +0.787 | +0.894 | 0.242 | +0.247 | +0.726 | +0.947 | +0.971 | +0.006 | +0.981 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | +6.038 | +5.669 | 1.965 | +3.620 | +4.785 | +7.019 | +9.568 | +3.297 | +13.896 |

- **Worst 5 seeds** (lowest PnL): 20260417, 20260499, 20260474, 20260498, 20260511
- **Best 5 seeds** (highest PnL): 20260426, 20260513, 20260449, 20260461, 20260428

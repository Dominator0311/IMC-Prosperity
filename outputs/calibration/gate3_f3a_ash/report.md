# Monte Carlo strategy comparison

Each strategy was run across **30 synthetic sessions**, each session = one full synthetic 1000-tick day with the same calibrated round-1 parameters.

## PnL distribution comparison

| strategy | mean | median | std | q05 | q95 | win_rate | mean_R^2 |
|---|---:|---:|---:|---:|---:|---:|---:|
| trader_round1_ash_deep_f3a | +360 | +390 | 372 | -25 | +899 | 90.0% | +0.739 |

## trader_round1_ash_deep_f3a

- Sessions: **30**
- Win rate (PnL > 0): **90.0%**

### PnL stats
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | +360.295 | +390.271 | 371.649 | -24.623 | +180.015 | +525.922 | +898.946 | -894.574 | +1235.578 |

### Alpha (slope of equity curve per tick)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | +0.379 | +0.392 | 0.376 | -0.235 | +0.222 | +0.607 | +0.879 | -0.771 | +1.188 |

### R^2 (consistency of equity slope; high = stable edge)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | +0.739 | +0.896 | 0.258 | +0.261 | +0.604 | +0.929 | +0.967 | +0.162 | +0.973 |

### Downside deviation (semi-std of negative returns)
| n | mean | median | std | q05 | q25 | q75 | q95 | min | max |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 30 | +7.455 | +6.511 | 3.423 | +3.987 | +5.357 | +8.450 | +15.811 | +3.302 | +17.578 |

- **Worst 5 seeds** (lowest PnL): 20260417, 20260418, 20260420, 20260435, 20260430
- **Best 5 seeds** (highest PnL): 20260426, 20260419, 20260428, 20260421, 20260439

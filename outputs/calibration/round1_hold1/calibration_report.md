# Calibration report

## ASH_COATED_OSMIUM

- Ticks: **1000**
- Fair value: sigma=**0.4074**, mean_return=**-0.0083**, phi=**+0.024** (SE 0.032, n=999)
- Quantization grid: **0.000977**
- FV range: [9993.76, 10011.00]

### Variance ratio (target: 1.0 for random walk)

| k | VR(k) |
|---:|---:|
| 2 | 1.057 |
| 5 | 1.025 |
| 10 | 1.049 |
| 20 | 1.048 |
| 50 | 1.388 |
| 100 | 0.907 |

### Depth bands

| name | side | offset_min | offset_max | presence |
|---|---|---:|---:|---:|
| level1_outer_bid_sub1 | bid | -12.00 | -6.50 | 91.1% |
| level1_near_bid_sub2 | bid | -3.99 | -1.01 | 2.0% |
| level1_near_bid_sub3 | bid | +0.19 | +2.95 | 1.9% |
| level2_outer_bid | bid | -12.00 | -1.58 | 61.6% |
| level3_outer_bid | bid | -11.99 | -6.58 | 2.5% |
| level1_near_ask_sub1 | ask | -4.00 | +2.96 | 3.8% |
| level1_outer_ask_sub2 | ask | +6.50 | +11.99 | 92.3% |
| level2_outer_ask | ask | +0.63 | +12.00 | 64.3% |
| level3_outer_ask | ask | +6.63 | +11.96 | 1.9% |

### Quote rules (best-match formula per band)

| bot | side | formula | match | n |
|---|---|---|---:|---:|
| level1_outer_bid_sub1 | bid | `round(fv +0.00) -8` | 80.0% | 911 |
| level1_near_bid_sub2 | bid | `round(fv +0.50) -3` | 100.0% | 20 |
| level1_near_bid_sub3 | bid | `round(fv +0.50) +1` | 100.0% | 19 |
| level2_outer_bid | bid | `round(fv +0.50) -11` | 95.0% | 616 |
| level3_outer_bid | bid | `round(fv +0.50) -11` | 96.0% | 25 |
| level1_near_ask_sub1 | ask | `round(fv +0.50) +1` | 63.2% | 38 |
| level1_outer_ask_sub2 | ask | `round(fv +0.00) +8` | 84.3% | 923 |
| level2_outer_ask | ask | `round(fv +0.50) +10` | 95.6% | 643 |
| level3_outer_ask | ask | `round(fv +0.50) +10` | 94.7% | 19 |

### Volume fits

| bot | side | min | max | n | chi^2 | p_uniform |
|---|---|---:|---:|---:|---:|---:|
| level1_outer_bid_sub1 | bid | 10 | 30 | 911 | 1212.49 | 0.000 |
| level1_near_bid_sub2 | bid | 1 | 5 | 20 | 3.00 | 0.558 |
| level1_near_bid_sub3 | bid | 4 | 10 | 19 | 9.37 | 0.154 |
| level2_outer_bid | bid | 5 | 30 | 616 | 742.92 | 0.000 |
| level3_outer_bid | bid | 14 | 30 | 25 | 24.64 | 0.076 |
| level1_near_ask_sub1 | ask | 2 | 13 | 38 | 47.26 | 0.000 |
| level1_outer_ask_sub2 | ask | 10 | 30 | 923 | 1424.88 | 0.000 |
| level2_outer_ask | ask | 3 | 30 | 643 | 869.39 | 0.000 |
| level3_outer_ask | ask | 14 | 30 | 19 | 24.84 | 0.073 |

### Trade arrivals

- p_active per tick: **0.0430** (43/1000)
- p_buy | active: **0.6512**
- total trades: 411
- KS vs geometric (gap survival): 0.7343

### Trade sizes

**buy** (n=28):
  - size 2: 0.071
  - size 3: 0.071
  - size 4: 0.143
  - size 5: 0.393
  - size 6: 0.071
  - size 7: 0.036
  - size 8: 0.071
  - size 9: 0.071
  - size 10: 0.071

**sell** (n=15):
  - size 2: 0.133
  - size 4: 0.067
  - size 5: 0.067
  - size 6: 0.333
  - size 7: 0.133
  - size 9: 0.067
  - size 10: 0.200


## INTARIAN_PEPPER_ROOT

- Ticks: **1000**
- Fair value: sigma=**0.1898**, mean_return=**+0.0940**, phi=**-0.000** (SE 0.032, n=999)
- Quantization grid: **0.099609**
- FV range: [12000.10, 12099.90]

### Variance ratio (target: 1.0 for random walk)

| k | VR(k) |
|---:|---:|
| 2 | 1.001 |
| 5 | 1.004 |
| 10 | 1.009 |
| 20 | 1.019 |
| 50 | 1.051 |
| 100 | 1.110 |

### Depth bands

| name | side | offset_min | offset_max | presence |
|---|---|---:|---:|---:|
| level1_inner_bid_sub1 | bid | -11.00 | -1.70 | 94.5% |
| level1_inner_bid_sub2 | bid | +1.70 | +4.60 | 1.3% |
| level2_outer_bid | bid | -11.00 | -5.10 | 66.1% |
| level3_outer_bid | bid | -11.00 | -8.10 | 1.3% |
| level1_inner_ask_sub1 | ask | -5.60 | -2.70 | 1.5% |
| level1_near_ask_sub2 | ask | -1.00 | +3.40 | 1.2% |
| level1_inner_ask_sub3 | ask | +5.00 | +11.00 | 92.3% |
| level2_outer_ask | ask | +2.00 | +11.00 | 63.2% |
| level3_outer_ask | ask | +8.10 | +10.80 | 1.5% |

### Quote rules (best-match formula per band)

| bot | side | formula | match | n |
|---|---|---|---:|---:|
| level1_inner_bid_sub1 | bid | `ceil(fv +0.00) -7` | 83.6% | 945 |
| level1_inner_bid_sub2 | bid | `round(fv +0.00) +3` | 84.6% | 13 |
| level2_outer_bid | bid | `ceil(fv +0.00) -10` | 97.4% | 661 |
| level3_outer_bid | bid | `round(fv +0.50) -10` | 100.0% | 13 |
| level1_inner_ask_sub1 | ask | `round(fv +0.00) -4` | 86.7% | 15 |
| level1_near_ask_sub2 | ask | `round(fv +0.00) +2` | 91.7% | 12 |
| level1_inner_ask_sub3 | ask | `floor(fv +0.00) +7` | 81.4% | 923 |
| level2_outer_ask | ask | `floor(fv +0.00) +10` | 96.4% | 632 |
| level3_outer_ask | ask | `round(fv +0.50) +9` | 100.0% | 15 |

### Volume fits

| bot | side | min | max | n | chi^2 | p_uniform |
|---|---|---:|---:|---:|---:|---:|
| level1_inner_bid_sub1 | bid | 5 | 25 | 945 | 1936.49 | 0.000 |
| level1_inner_bid_sub2 | bid | 3 | 8 | 13 | 5.92 | 0.314 |
| level2_outer_bid | bid | 8 | 25 | 661 | 383.14 | 0.000 |
| level3_outer_bid | bid | 15 | 25 | 13 | 6.46 | 0.775 |
| level1_inner_ask_sub1 | ask | 3 | 8 | 15 | 13.40 | 0.020 |
| level1_near_ask_sub2 | ask | 5 | 12 | 12 | 6.67 | 0.464 |
| level1_inner_ask_sub3 | ask | 8 | 25 | 923 | 1348.96 | 0.000 |
| level2_outer_ask | ask | 8 | 25 | 632 | 350.20 | 0.000 |
| level3_outer_ask | ask | 16 | 25 | 15 | 3.00 | 0.964 |

### Trade arrivals

- p_active per tick: **0.0330** (33/1000)
- p_buy | active: **0.3636**
- total trades: 332
- KS vs geometric (gap survival): 0.7094

### Trade sizes

**buy** (n=12):
  - size 3: 0.083
  - size 4: 0.167
  - size 5: 0.417
  - size 6: 0.167
  - size 7: 0.083
  - size 8: 0.083

**sell** (n=21):
  - size 3: 0.143
  - size 4: 0.333
  - size 5: 0.238
  - size 6: 0.143
  - size 7: 0.095
  - size 8: 0.048


# PEPPER guarded-carry research note

Date: 2026-04-16

This note records the first in-repo pass on a "guarded carry" PEPPER
family built on top of `PepperCoreLongStrategy`.

## What changed in code

- Added opt-in negative-drift protection knobs to
  `src/strategies/pepper_core_long.py`:
  `guard_window`, `guard_negative_slope`, `guard_r2_min`,
  `guard_target`
- Added opt-in residual + imbalance micro-bias knobs:
  `micro_residual_threshold`, `micro_imbalance_threshold`,
  `micro_add_size`, `micro_trim_size`
- Added `open_take_mode` with `all_asks` and `level1_only`
- Added tests in `tests/test_pepper_core_long.py`

All new behavior is disabled by default; legacy PEPPER configs are
unchanged when the new knobs are omitted.

## Candidate shapes tested

Baseline:

- `V3_nearhold`

New variants:

- `guard0`: V3-like core, but cap target at 0 when a 32-step rolling
  slope falls below `-0.02` (no `r2` gate)
- `guard20`: same but cap at +20
- `guard0_l1`: `guard0` + `open_take_mode="level1_only"`
- `guard0_micro`: `guard0` + residual/imbalance micro-bias

## First-pass results

PEPPER PnL only.

### Real 3-day tape

| candidate | day -2 | day -1 | day 0 | mean |
|---|---:|---:|---:|---:|
| `V3_nearhold` | 79,549.0 | 79,204.0 | 79,391.0 | 79,381.3 |
| `guard0` | 79,549.0 | 79,204.0 | 79,391.0 | 79,381.3 |
| `guard20` | 79,549.0 | 79,204.0 | 79,391.0 | 79,381.3 |
| `guard0_l1` | 79,627.0 | 79,381.0 | 79,243.0 | 79,417.0 |
| `guard0_micro` | 79,361.5 | 79,065.0 | 79,504.0 | 79,310.2 |

### Stress tapes

| candidate | flat | reversed | high_vol | stepped |
|---|---:|---:|---:|---:|
| `V3_nearhold` | -451.0 | -80,431.0 | 86,838.0 | -451.0 |
| `guard0` | -256.0 | -7,760.0 | 85,431.0 | 32,810.0 |
| `guard20` | -256.0 | -24,902.0 | 85,431.0 | 26,150.0 |
| `guard0_l1` | -130.0 | -3,402.0 | 85,545.0 | 32,888.0 |
| `guard0_micro` | 867.0 | -7,760.0 | 86,180.0 | 32,894.0 |

## Read

- The original `r2` gate made the guard effectively inert on the
  synthetic tapes. Dropping the `r2` gate is what unlocked the
  reversal protection.
- `guard0` is "free" on the real 3-day PEPPER tape and massively
  improves the `reversed` and `stepped` scenarios.
- `guard0_l1` is the best first-pass candidate:
  - slightly better 3-day mean than `V3_nearhold`
  - best `reversed` result in this pass
  - best `flat` result in this pass
  - keeps most of the `high_vol` upside
- `guard0_micro` is interesting but not ready:
  - improves `flat`, `stepped`, and stays strong on `high_vol`
  - but adds more variance across the real days than `guard0_l1`

## Recommendation

If the objective is "more real edge on unseen data", the next PEPPER
search should anchor around:

```python
CoreLongParams(
    base_long=80,
    add_thresh=3.0,
    trim_thresh=8.0,
    add_gain=5.0,
    trim_gain=2.0,
    floor=0,
    ceiling=80,
    step=8,
    exec_style="taker",
    open_seed_size=65,
    open_window=500,
    open_no_short=True,
    open_take_mode="level1_only",
    guard_window=32,
    guard_negative_slope=0.02,
    guard_r2_min=0.0,
    guard_target=0,
)
```

This should be treated as a new PEPPER family (`guarded carry`), not
as a tiny `V3` parameter tweak.

## Narrow frontier sweep

After the first-pass note above, a tighter follow-up sweep was run
around the strongest region only:

- `guard_window ∈ {24, 32}`
- `guard_negative_slope ∈ {0.01, 0.02}`
- `guard_target ∈ {0, 20}`
- `open_take_mode ∈ {"all_asks", "level1_only"}`

Scoring used:

```text
score = mean_real
      + 0.10 * (reversed - v3_reversed)
      + 0.10 * (stepped  - v3_stepped)
      + 0.02 * (flat     - v3_flat)
      + 0.05 * (high_vol - v3_high_vol)
```

Top PEPPER candidates from that narrow pass:

| rank | label | real mean | flat | reversed | high_vol | stepped |
|---|---|---:|---:|---:|---:|---:|
| 1 | `w32_g0.02_t0_l1` | **79,417.0** | -130.0 | **-3,402.0** | 85,545.0 | **32,888.0** |
| 2 | `w32_g0.01_t0_l1` | 79,417.0 | **+153.0** | -3,402.0 | 85,043.0 | 32,888.0 |
| 3 | `w24_g0.02_t0_l1` | 79,417.0 | -121.0 | -3,402.0 | 79,749.0 | 32,888.0 |
| 4 | `w24_g0.01_t0_l1` | 79,417.0 | +36.0 | -3,402.0 | 79,199.0 | 32,888.0 |
| 5 | `w32_g0.02_t0_all` | 79,381.3 | -256.0 | -7,760.0 | 85,431.0 | 32,810.0 |
| ref | `V3_nearhold` | 79,381.3 | -451.0 | -80,431.0 | **86,838.0** | -451.0 |

Read:

- `level1_only` opening **dominates** `all_asks` on robustness.
- `guard_target=0` **dominates** `guard_target=20`.
- `guard_window=32` is the cleanest compromise; `24` preserves the
  reversal / stepped benefit but gives up too much `high_vol`.
- `guard_negative_slope=0.02` is the best overall setting in this
  narrow band; `0.01` is close, with slightly better `flat` but
  slightly worse `high_vol`.

## Updated recommendation

The best PEPPER guarded-carry candidate in the repo right now is:

```python
CoreLongParams(
    base_long=80,
    add_thresh=3.0,
    trim_thresh=8.0,
    add_gain=5.0,
    trim_gain=2.0,
    floor=0,
    ceiling=80,
    step=8,
    exec_style="taker",
    hybrid_threshold=2.0,
    open_seed_size=65,
    open_window=500,
    open_no_short=True,
    open_take_mode="level1_only",
    guard_window=32,
    guard_negative_slope=0.02,
    guard_r2_min=0.0,
    guard_target=0,
)
```

This is the first PEPPER variant in the repo that:

- stays at the `V3` / `buy_hold` ceiling on the real drift-up tape,
- materially improves `flat`,
- massively improves `reversed`,
- massively improves `stepped`,
- and still keeps most of the `high_vol` upside.

## Expanded frontier stress pass

The 4 original PEPPER stress tapes were enough to prove that a
negative-drift guard matters, but they were still too coarse to cleanly
separate `guard_negative_slope = 0.01` from `0.02` from `0.05`.

A tighter follow-up pass fixed all other knobs at the current frontier:

- `open_take_mode="level1_only"`
- `guard_target=0`
- `guard_window=32`

and swept only:

- `guard_negative_slope ∈ {0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.07, 0.10}`

while adding 4 new PEPPER-specific stress tapes:

- `mild_reversed`: shallow negative drift
- `late_reversed`: drift-up most of the day, then late sharp reversal
- `reversed_high_vol`: reversed drift with residuals amplified
- `shock_down_recover`: temporary drawdown that later recovers

### Key result

All guarded variants from `0.005` through `0.04` tie on the real
3-day PEPPER tape:

- real mean = `79,417.0`

They also tie on the "easy" strong-reversal scenarios:

- `reversed = -3,402.0`
- `late_reversed = +49,598.0`
- `stepped = +32,888.0`

The real separator is the tradeoff between:

- catching **shallow / noisy reversals** early enough, and
- **not** overreacting to a temporary drawdown.

### Frontier snapshot

| candidate | flat | mild_reversed | reversed_high_vol | high_vol | shock_down_recover |
|---|---:|---:|---:|---:|---:|
| `g=0.005` | **+213.5** | **-2,551.0** | **-3,101.5** | 85,055.0 | 78,927.0 |
| `g=0.010` | +153.0 | **-2,551.0** | -3,825.5 | 85,043.0 | 79,719.0 |
| `g=0.015` | -2.0 | -2,939.0 | -3,825.5 | 85,545.0 | 79,740.0 |
| `g=0.020` | -130.0 | -3,085.0 | -4,618.0 | 85,545.0 | **79,887.0** |
| `g=0.050` | -289.0 | -10,107.5 | -3,391.5 | **86,914.0** | 79,687.0 |

### Read

- `0.05` is now clearly too late:
  - keeps more `high_vol` upside,
  - but gives back too much on `mild_reversed`,
  - and even starts slipping on full `reversed`.
- `0.02` is no longer the cleanest overall setting:
  - it is fine on big reversals,
  - but it is meaningfully worse than `0.01` on
    `mild_reversed` and `reversed_high_vol`.
- `0.005` is the most defensive:
  - best on `flat`,
  - best on `mild_reversed`,
  - best on `reversed_high_vol`,
  - but it gives up the most on `shock_down_recover`, which suggests
    more false-positive de-risking.
- `0.01` is the best **balanced** frontier point:
  - same real 3-day mean as every other top candidate,
  - same protection as `0.005` on `mild_reversed`,
  - much better `shock_down_recover` than `0.005`,
  - and much better `mild_reversed` / `reversed_high_vol` than `0.02`.

### Updated recommendation

If the objective is **max real edge on unseen PEPPER data**, my current
preference shifts slightly earlier than the old `0.02` recommendation:

```python
CoreLongParams(
    base_long=80,
    add_thresh=3.0,
    trim_thresh=8.0,
    add_gain=5.0,
    trim_gain=2.0,
    floor=0,
    ceiling=80,
    step=8,
    exec_style="taker",
    hybrid_threshold=2.0,
    open_seed_size=65,
    open_window=500,
    open_no_short=True,
    open_take_mode="level1_only",
    guard_window=32,
    guard_negative_slope=0.01,
    guard_r2_min=0.0,
    guard_target=0,
)
```

If we wanted the most reversal-defensive setting regardless of
false-positive risk, `0.005` is the answer. But for a balance of:

- real-day carry retention,
- early reaction to weaker negative regimes,
- and not flinching too hard on temporary shocks,

`0.01` is the better PEPPER frontier point.

## vNext pass: adaptive caps + tiny micro overlays

After the `0.01` frontier was selected, the next question was whether
PEPPER had more edge in:

- adaptive long-cap tiers, and/or
- a very small residual/imbalance timing overlay.

This was tested in `run_guarded_carry_vnext.py` with a small candidate
set around:

- baseline `guard=0.01`,
- conservative adaptive caps (`40/60/80` and `50/65/80`),
- tiny micro overlays (`1`- to `2`-lot),
- and combinations of both.

### What happened

1. **Conservative adaptive caps were effectively inert.**
   With `adaptive_r2_min=0.9`, the PEPPER fit almost never cleared the
   confidence gate on the real tape, so capped variants tied the
   baseline almost exactly.

2. **Relaxing the confidence gate made adaptive caps actively bad.**
   A follow-up inline check with `adaptive_r2_min=0.0` showed the caps
   did activate — and they destroyed carry:
   - real mean dropped from `79,417.0` to `75,631.0` (`40/60/80`)
   - `high_vol` dropped from `85,043.0` to `74,107.0`
   - `shock_down_recover` dropped from `79,719.0` to `76,890.0`

   This strongly suggests that PEPPER's edge is still too
   carry-dominated for slope-tiered caps to help unless they are nearly
   inert.

3. **Tiny micro overlays were the only vNext lever that moved at all.**
   The best micro-only pass did:
   - real mean: `79,397.2` (slightly worse than `79,417.0`)
   - `flat`: `+570.0` (better than `+153.0`)
   - `late_reversed`: `50,349.0` (better than `49,598.0`)
   - `high_vol`: `85,323.0` (better than `85,043.0`)
   - `stepped`: `32,944.0` (better than `32,888.0`)
   - `shock_down_recover`: `79,595.0` (worse than `79,719.0`)

### Read

- **Adaptive caps are not the next PEPPER edge.**
  When gated tightly they do nothing; when relaxed they give away too
  much carry.
- **The micro overlay is still the only plausible next alpha source.**
  But at the tested sizes it is still trading a small amount of real
  carry for synthetic-stress upside.

### Current PEPPER conclusion

The best PEPPER unseen-data candidate is still:

- guarded carry,
- `open_take_mode="level1_only"`,
- `guard_window=32`,
- `guard_negative_slope=0.01`,
- `guard_target=0`,
- **no adaptive caps**.

If PEPPER has more edge left, it is more likely to come from a better
micro-timer than from dynamic inventory tiers.

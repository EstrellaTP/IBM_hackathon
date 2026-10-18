# Activity features

All features are computed per person from an **hourly activity series** (sum of
activity per clock hour), built from NHANES hourly MIMS (`PAXHR_G/H`) or from DEPRESJON
minute counts aggregated to hours (`ml/features/hourly.py`). Code:
`ml/features/circadian.py`; tests with hand-built series: `tests/ml/test_circadian.py`.

**Validity.** NHANES hour: 60 minutes measured, ≥ 45 minutes worn (wake + sleep wear),
≤ 15 minutes quality-flagged. DEPRESJON hour: all 60 minutes present. A day is used
when ≥ 20 of its 24 hours are valid; a person when ≥ 4 days are valid.

Notation: x_i is the activity of valid hour i (N hours), x̄ the overall mean, x̄_h the
mean of clock hour h over all days, p = 24.

| Feature | Formula | Meaning | Reference |
|---|---|---|---|
| `is_` interdaily stability | IS = N·Σ_h (x̄_h − x̄)² / (p·Σ_i (x_i − x̄)²) | 0–1; how similar the days are | Witting et al., *Biol Psychiatry* 27 (1990) 563–572 |
| `iv` intradaily variability | IV = N·Σ_i (x_i − x_{i−1})² / ((N−1)·Σ_i (x_i − x̄)²), consecutive hours only | ≈0 smooth rhythm, ≈2 noise; fragmentation of the rhythm | Witting et al. (1990) |
| `l5`, `l5_start_h` | mean of the 5 consecutive least active hours of the 24-h profile (circular), and its start hour | night-time rest level and timing | van Someren et al., *Chronobiol Int* 16 (1999) 505–518 |
| `m10`, `m10_start_h` | same for the 10 most active hours | daytime activity level and timing | van Someren et al. (1999) |
| `ra` relative amplitude | (M10 − L5) / (M10 + L5) | 0–1; strength of the rhythm | van Someren et al. (1999) |
| `daytime_activity` | mean hourly activity 08:00–22:00 | overall daytime activity | — |
| `rest_hours_per_day` | mean hours/day with activity < 0.1·M10 | sleep/rest duration proxy (relative to the person's own active level) | threshold chosen for this project |
| `night_fragmentation` | mean rest→active transitions per night, in the 8 h centred on L5 | interrupted rest (awakenings proxy) | — |
| `sedentary_share` | share of daytime hours with activity < 0.25·M10 | sedentary daytime | threshold chosen for this project |
| `daily_total_cv` | SD / mean of daily activity totals | day-to-day variability | — |

**Comparability across devices.** NHANES uses MIMS from a wrist ActiGraph, DEPRESJON
Actiwatch counts. IS, IV, RA, timings, shares and the CV are scale-free.
`l5`, `m10` and `daytime_activity` keep device units: before pooling or transferring a
model they are `log1p`-transformed and z-scored **within each dataset**
(`circadian.standardise_within_dataset`).

**Limitations.** Hourly resolution cannot see sleep latency or short awakenings: the
rest and fragmentation features are proxies, not polysomnographic sleep measures. The
thresholds 0.1·M10 and 0.25·M10 were set a priori, not tuned on the labels.

**Real data** (`ml/reports/features_summary.md`): effect sizes of every feature in
NHANES (PHQ-9 ≥ 10 vs < 10) and DEPRESJON (patients vs controls).

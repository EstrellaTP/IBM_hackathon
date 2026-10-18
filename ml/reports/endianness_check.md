# Big-endian check: same input, same prediction on x86 and s390x

Generated with `python -m ml.models.endianness_check` on both machines (2026-10-18).
Input: 50 seeded synthetic feature rows (no health data), identical on both machines.

| | Laptop | LinuxONE VM |
|---|---|---|
| Machine | `AMD64` (little-endian) | `s390x` (big-endian) |
| Deployed model | `logistic-depresjon-55` | `logistic-depresjon-55` |

| Model | Max absolute difference over 50 rows |
|---|---|
| Deployed depression model (`depression_model.json`, logistic + Platt calibration) | **0.0** |
| LightGBM saved as text on s390x, loaded on both | **0.0** |

Predictions are compared as exact IEEE-754 values (`float.hex()`), so 0.0 means
bit-identical results. First rows:

| Row | Deployed, x86 | Deployed, s390x | LightGBM text, x86 | LightGBM text, s390x |
|---|---|---|---|---|
| 0 | `0x1.3f5179466a5d4p-17` | `0x1.3f5179466a5d4p-17` | `0x1.128a53dd98148p-5` | `0x1.128a53dd98148p-5` |
| 1 | `0x1.8922fb52f29fbp-1` | `0x1.8922fb52f29fbp-1` | `0x1.e49b680acb122p-2` | `0x1.e49b680acb122p-2` |
| 2 | `0x1.3de1f3035761ep-17` | `0x1.3de1f3035761ep-17` | `0x1.d1164b4896841p-1` | `0x1.d1164b4896841p-1` |

Why it holds: the models are stored in text formats (JSON coefficients, LightGBM text),
never as pickles or raw binary arrays, and the arithmetic is plain IEEE-754 double on
both architectures. Requirement: difference < 1e-6 (docs/QUALITY.md), met with margin.

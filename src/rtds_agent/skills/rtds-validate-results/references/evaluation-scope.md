# Supported numerical evaluation

The JSON adapter evaluates supplied discrete samples; behavior between samples is not proven. Only these requirement kinds are implemented:

| Kind | Meaning |
| --- | --- |
| `min_max` | Minimum, maximum and sample count over the inclusive interval; no threshold verdict (`not_evaluated`). |
| `range` | All interval samples must lie within inclusive `lower`/`upper` bounds. |
| `settling_band` | All samples at or after `settle_after` inside the interval must lie within the band. `sampled_settling_time` is a discrete observation, not proof of continuous settling. |
| `reference_error` | Each absolute error must be at most `absolute_tolerance + relative_tolerance * abs(reference)`. Optional `rmse_limit` also constrains the sample-wise RMSE. |

Every requirement needs its ID, exact channel ID, units, sign convention, seconds/time basis, start/end, and criterion provenance. Units, per-unit bases, time bases, signs, and reference sample timestamps must match exactly. The implementation performs no interpolation, conversion, resampling, or arbitrary expression evaluation. `max_sample_gap_seconds` can constrain sampling gaps explicitly.

Artifact/request hash or identity mismatches fail before assessment. Invalid or missing channel samples and inadequate intervals make affected requirements inconclusive. No requirements yields channel summaries with `not_evaluated`; `engineering_verdict` remains `not_evaluated` even when specified requirements pass. Caller-supplied provenance is recorded, not independently authenticated.

Rise time, overshoot, harmonic analysis, integrals, CSV, and native vendor capture adapters are unsupported in this version. Do not present those as available metrics. Synthetic traces validate the software path only.

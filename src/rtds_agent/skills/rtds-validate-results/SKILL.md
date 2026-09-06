---
name: rtds-validate-results
description: Evaluate prepared RTDS result data against explicit numerical requirements with channel units, time windows, provenance, and narrowly scoped verdicts.
---

# Validate numerical RTDS results

## Use when

Compare supplied baseline and candidate waveforms or evaluate captured data against explicit acceptance criteria.

## Do not use when

The request only asks whether compilation succeeded, has no numerical data, or requires an unprovided engineering requirement to be invented. Do not treat synthetic data as a live rack experiment.

## Prerequisites

Identify the raw data source/hash, channel names and units, time unit and ordering, sampling characteristics, evaluation windows, baseline/reference, and explicit thresholds. Call `get_capabilities()` and keep missing values, non-finite samples, insufficient windows, and mismatched units visible. The dataset declares `schema_version` = `"1.0"`, `input_project_sha256`, `run_id`, `attempt_id`, `time_unit` = `"s"`, a `time_basis`, and channels with `channel_id`, `units`, `sign_convention`, strictly increasing `times`, and numeric `values`; pu channels also need `pu_base`. Run identities are declarations cross-checked against the artifact, not independently verified simulator qualifications. Read [evaluation-scope.md](references/evaluation-scope.md) when selecting or interpreting metrics.

## Tool order

1. For workflow data, call `get_workflow_status(workflow_path)` and `revalidate_execution_evidence(workflow_path)` to associate the correct project and attempt. External prepared data requires its own provenance and must not be relabeled as execution evidence.
2. Inspect the relevant bounded interval with `read_result_samples(source, channel_id, start_time, end_time, offset, limit)`, retaining the source hash for every page. Call `evaluate_results(request)` with the structured `source` artifact reference, optional `reference`, `specification`, and `specification_sha256`. Each artifact reference contains `data_path`, `data_sha256`, `input_project`, `input_project_sha256`, `run_id`, and `attempt_id`. Use the advertised schema for each requirement. Only the documented JSON sample adapter is supported; existing CSV captures require a separately verified conversion and are not accepted directly.
3. Check every returned metric's data/window/algorithm evidence and limitations. The implementation requires matching sample timestamps, units, sign convention, time basis, and pu base. It performs no interpolation, resampling, or unit conversion.
4. Distinguish `passed`, `failed`, `inconclusive`, and `not_evaluated` outcomes. Unsupported formats or criterion kinds fail validation. Preserve criteria that cannot be evaluated instead of silently excluding them. When the user wants a saved report, call `save_result_assessment(request)`; it writes a separate local assessment without changing approved workflows.

Use `capture_rtds_results` mode `workflow_native` for saved native session receipts; channel declarations come from the bound plan and cannot be overridden. Legacy `workflow` conversion refuses native receipts. `supplied_csv` remains explicitly caller-supplied evidence. Keep capture success separate from safe completion: a failed control restoration or Runtime stop remains a failure even if samples convert or numerical criteria pass. Source-bound metadata declarations, SDK-generated plot time, freshness and atomicity are not independently verified by conversion.

## Completion

Provide numerical values, units, thresholds, source hashes, windows, alignment/conversion assumptions, per-requirement outcomes, and the exact scope of the verdict. Separate structural validity, compile status, execution status, and requirements demonstrated by these data.

## On failure

Report the smallest missing or invalid input, retain valid independent measurements, and leave affected requirements inconclusive or unsupported. Do not replace missing samples with zero, smooth data silently, choose a favorable interval, invent defaults, or announce overall system safety.

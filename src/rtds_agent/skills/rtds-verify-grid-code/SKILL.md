---
name: rtds-verify-grid-code
description: Compare hash-bound RTDS result samples with explicitly sourced grid-code criteria and report requirement traceability, data gaps, and the limits of numerical acceptance.
---

# Verify supplied grid-code criteria

## Use when

The user has a requirement source, an explicit test specification and saved result data to assess against it.

## Do not use when

The user is asking for legal certification, general dynamic-stability approval or an automatic real-rack run. A toolkit numerical pass does not establish those outcomes.

## Prerequisites

Read the applicable local document and exact page. Bind the result to its project hash, run and attempt; confirm channel identity, units, sign convention, time basis, pu base and sampling coverage. Do not substitute plot pixels for numeric samples.

## Tool order

1. Use `get_manual_page(source_path, page)` for the cited criterion and context. Separate the clause from the chosen sampled calculation and any interpretation.
2. Use `capture_rtds_results(request)` for an existing saved backend CSV, or supply a canonical JSON artifact directly. This acquisition tool does not initiate a simulation.
3. Use `read_result_samples(source, channel_id, start_time, end_time)` if an interval or transient needs inspection. Use `evaluate_results(request)` or `save_result_assessment(request)` with explicit acceptance thresholds. For a prepared experiment suite, use `run_experiment_suite(request)` with mode `assess` to retain run/axis/requirement mappings.
4. Read all inconclusive reasons and unassessed requirements before reporting. Sampled recovery, coherent-window THD and single-mode damping estimates have distinct assumptions; never treat them as interchangeable compliance proofs.

## Completion

Report requirement ID, source/hash/page, tested events, measured channel, metric definition, supplied threshold, numerical result and evidence gaps. Preserve `engineering_verdict: not_evaluated`; state which runs were not supplied or executed.

## On failure

Distinguish an actual supplied-criterion failure from stale inputs, wrong units, missing captures or insufficient sampling. Suggest a specific next measurement or reviewed model change. Do not modify criteria to make an existing run pass or automatically rerun hardware.

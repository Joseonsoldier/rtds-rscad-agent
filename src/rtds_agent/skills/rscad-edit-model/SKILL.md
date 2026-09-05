---
name: rscad-edit-model
description: Change supported numeric RSCAD component parameters in an isolated copy using catalog evidence, exact old values, and post-edit comparison.
---

# Edit RSCAD numeric parameters

## Use when

The user requests supported REAL or INTEGER parameter changes while preserving the original project and companions.

## Do not use when

The request needs string or selector edits, component creation, wiring changes, live Runtime controls, or changes to vendor definitions. Do not replace unsupported edits with arbitrary file writes.

## Prerequisites

Establish the source hash, exact component UUID and context, component type, old values, requested new values, and installed RSCAD version. Call `get_capabilities()` and check each parameter against validated catalog evidence. Select a catalog snapshot explicitly when definitions are ambiguous; preserve the returned snapshot identity in the patch request. Reject uncertain units, stale definitions, duplicate targets, non-finite numbers, and out-of-range values.

## Tool order

1. Call `inspect_rscad_project(project_path)` and `get_component(project_path, component_id, context)` to establish current evidence.
2. Use `lookup_parameter(component_type, parameter, rscad_version, parameter_catalog_snapshot_id)` to inspect supported type, definition provenance, and bounds. If catalog evidence is absent, report the required local indexing setup; do not manufacture defaults.
3. Call `apply_parameter_patch_batch(request)` once for related changes. The structured request contains `schema_version` = `"1.0"`, `source_project`, `source_sha256`, supported `rscad_version`, `project_label`, the selected `parameter_catalog_snapshot_id`, and 1-20 `operations`. Each operation specifies `op` = `"set_parameter"`, `component_id`, `context`, `component_type`, `parameter`, and exact `expected_old_value` / `new_value` strings. This validates the whole transaction before publishing a copy; do not split Kp/Ki across independent single changes.
4. Re-read the resulting isolated copy using `get_component(project_path, component_id, context)` and `validate_project(project_path)`. Use `compare_project_versions(project_a, project_b)` to verify that only requested values changed; the summary `compare_projects(project_a, project_b)` is not a detailed unchanged-parameter or wiring proof.

## Completion

Report the original and copy hashes, catalog/definition evidence actually used, exact old/new values, detailed diff, companion preservation, and static validation limitations. Publication of a copy is not compile or engineering acceptance.

## On failure

A stale hash or old-value mismatch requires reinspection and a newly grounded change request. Do not silently rebase the user's expected values, mutate the original, relax the policy, or list an unpublished staging directory as a completed project.

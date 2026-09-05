---
name: rscad-edit-model
description: Change supported RSCAD parameters or bounded component templates in an isolated copy using definition evidence, exact old values, project policy, and post-edit comparison.
---

# Edit RSCAD numeric parameters

## Use when

The user requests supported parameter changes or bounded structural edits while preserving the original project and companions.

## Do not use when

The request needs live Runtime controls, changes to vendor definitions, opaque-reference removal, or general model generation without a verified template. Do not replace unsupported edits with arbitrary file writes.

## Prerequisites

Establish the source hash, exact component UUID and context, component type, old values, requested new values, and installed RSCAD version. Call `get_capabilities()` and check each parameter against validated catalog evidence. Select a catalog snapshot explicitly when definitions are ambiguous; preserve the returned snapshot identity in the patch request. Reject uncertain units, stale definitions, duplicate targets, non-finite numbers, and out-of-range values.

## Tool order

1. Call `inspect_rscad_project(project_path)` and `get_component(project_path, component_id, context)` to establish current evidence.
2. Use `lookup_parameter(component_type, parameter, rscad_version, parameter_catalog_snapshot_id)` to inspect supported type, definition provenance, and bounds. If catalog evidence is absent, report the required local indexing setup; do not manufacture defaults.
3. Call `apply_parameter_patch_batch(request)` once for related changes. The structured request contains `schema_version` = `"1.0"`, `source_project`, `source_sha256`, supported `rscad_version`, `project_label`, the selected `parameter_catalog_snapshot_id`, and 1-20 `operations`. Each operation specifies `op` = `"set_parameter"`, `component_id`, `context`, `component_type`, `parameter`, and exact `expected_old_value` / `new_value` strings. This validates the whole transaction before publishing a copy; do not split Kp/Ki across independent single changes.
4. Re-read the resulting isolated copy using `get_component(project_path, component_id, context)` and `validate_project(project_path)`. Use `compare_project_versions(project_a, project_b)` to verify that only requested values changed; the summary `compare_projects(project_a, project_b)` is not a detailed unchanged-parameter or wiring proof.

For selector/string/location or structure edits, use `get_component_schema(component_type)` and the existing operator-authored project component policy. Use `edit_rscad_model(request)` in preview mode, inspect every changed component/net and model-check finding, then use apply mode with that preview ID within the user's authorized scope. Insertion/clone/wire creation require an exact same-context template; removal with opaque non-DFX records is unsupported. The editor cannot write or enable its policy. `check_rscad_model(project_path)` adds static rules; candidate publication does not qualify native RSCAD structural editing.

The optional `backend` defaults to `static`. Explicit `native` supports existing flat Draft parameter/location edits and the sole operation `{"op":"rebuild_draft","strategy":"insert"}` or `strategy:"clipboard"`. Reconstruction requires one subsystem, 1–500 globally unique component IDs, an empty saved Runtime and no opaque archive payloads. Insert supports flat models; clipboard supports GROUP/hierarchy only after saved membership and explicit UUID/context mapping pass. The operator policy must allow every component type (including GROUP); insertion also requires every stored parameter to be allowed. No policy is created. Check the preview's scope and SDK evidence. A reconstruction preview has no predicted candidate hash; its plan, source, definitions, companions, policy and adapter hashes bind apply. New-case identity/cleanup has not passed live qualification on the observed host; report that limitation before an authorized attempt.

`auto` refuses apply; reconstruction auto mode provides a read-only plan, not a static reconstruction. Never substitute static apply. Native saves a new isolated file, closes, reopens the exact path and verifies parsed semantics and preserved non-DFX bytes before publishing. Inspect the durable journal on failure. Unknown identity or cleanup blocks subsequent native apply, Compile and Runtime; never retry, force-close or reconnect using an old session's case ID. Static grouped mutation remains unsupported. Compile and Runtime use their separate permissions and workflows.

## Completion

Report the original and copy hashes, catalog/definition evidence actually used, exact old/new values, detailed diff, companion preservation, and static validation limitations. Publication of a copy is not compile or engineering acceptance.

## On failure

A stale hash or old-value mismatch requires reinspection and a newly grounded change request. Do not silently rebase the user's expected values, mutate the original, relax the policy, or list an unpublished staging directory as a completed project.

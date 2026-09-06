# Model changes, prepared results, and bounded experiments

For opt-in native acquisition, prepare source-bound metadata and exact saved/live graph scope, inspect `capture_rtds_results` mode `prepare_native`, and execute only through the existing authorized Runtime workflow. Convert the completed attempt with `workflow_native`, which derives channel metadata from its receipt. No preparation or conversion starts RSCAD. See [NATIVE_CAPTURE.md](NATIVE_CAPTURE.md).

The partial WP-N05 [event timing workflow](EVENT_TIMING.md) records offline evidence from supplied clock-channel values without interpolation. Observed transitions carry conservative timing-error brackets and cannot be reused or reordered; model-native planning, preparation and assessment do not authorize live dispatch or Runtime grant creation. Use the unchanged grounding document for sweep declarations; omitted timing keeps legacy plans and sleep/write behavior.

For native editing or a source-derived `rebuild_draft`, follow [preview/plan, isolated creation, mapped comparison, exact reopen and recovery](NATIVE_EDITING.md). Default static behavior is unchanged; auto apply remains refused. Reconstruction has synthetic qualification and three task-scoped local construction/Compile trials; public live apply remains unqualified. A recovery marker blocks further native apply/Compile/Runtime until operator review; do not reconnect using an old case ID. Do not promote private tutorial scripts or synthetic policies into operator authorizations.

For saved Runtime structure use `inspect_runtime_layout(project_path, representation="ir")` and retain its source/snapshot hashes. [Runtime IR](RUNTIME_IR.md) preserves unresolved references and distinguishes stored positions from current values. A live write plan additionally needs exact verified `object_subpage`, type/name/ID, expected value and existing execution authorization. The driver rejects ambiguous candidates and rechecks scope before writing/restoration. No overlay generation tool is available.

Optional WP-N06A load-flow initialization is limited to `check_rscad_model(..., initialization=None)` planning and supplied evidence; see [LOADFLOW_INITIALIZATION.md](LOADFLOW_INITIALIZATION.md). Enabled legacy Runtime initialization is refused before backend, rack, or grant access. Omitted or disabled initialization remains unchanged, and any plan inspection may retain historical enabled contracts without executing them. Load-flow initialization must precede Compile; supplied convergence does not qualify live integration.

The MCP server publishes the explicit [tool contracts](TOOL_CONTRACTS.md), with separate local read, local output, and live-action annotations. Document/source reads, project inspection, numeric-copy edits and run preparation are separate from live execution. Unlike the private prototype, a new user creates a fresh workflow instead of importing someone else's accepted experiment.

## Source and plan

Configure source roots read-only. `prepare_workflow(source_project, test_spec, grounding_paths)` accepts a source or existing working copy, discovers companion files from installed definitions, makes a new isolated `projects/<id>/working/` copy, and records hashes and source evidence. Grounding paths must be the local documents actually used to choose the plan. This records provenance, not automatic confirmation that the engineering design is correct.

A minimal capture plan has this structure. Replace the signal path and units with values verified for your case; this example is not an executable vendor model.

```json
{
  "test_id": "my_capture",
  "execution_mode": "runtime_read_only_signal_capture",
  "runtime_required": true,
  "event": {"type": "none"},
  "runtime_controls": {
    "read_only_signal_capture": true,
    "runtime_parameter_writes": [],
    "hardware_io_changes": [],
    "rack_configuration_changes": [],
    "deployment_actions": []
  },
  "runtime_capture": {"warmup_seconds": 1, "minimum_samples_per_channel": 3},
  "measurement_channels": [
    {"channel_id": "my_voltage", "signal_path": "replace-with-exact-signal-path", "units": "kV"}
  ],
  "output_requirements": {
    "raw_numeric_data_required": true,
    "screenshot_only_pass_fail_forbidden": true
  }
}
```

The compatibility field `read_only_signal_capture` remains true for measurement collection even in control mode. To include supported controls use `execution_mode: runtime_control_and_signal_capture` and the exact action schema in [runtime_test_spec.schema.json](../src/rtds_agent/schemas/runtime_test_spec.schema.json). Do not guess UUIDs, labels, values, units or LockFree meaning. Restore/readback are mandatory, and the local policy must also include `runtime_controls`.

## Tool order

1. `get_capabilities`, `get_execution_policy`, and `get_knowledge_status`. Confirm this task permits the intended live actions; file/dependency presence and active policy alone do not authorize them.
2. Search local sources, read original manual pages/images where needed, and inspect project snapshots. For numeric copy editing, first build or explicitly select local parameter catalog evidence through the CLI.
3. `prepare_workflow` with the planned capture and source documents.
4. `compile_project(workflow_path)` — uses a currently available permitted rack.
5. `prepare_simulation_run(workflow_path)` — returns a request path and hash without starting anything.
6. `run_simulation(workflow_path, request_path, request_sha256)` — executes the exact request and writes local result/cleanup evidence.
7. `get_workflow_status` and `revalidate_execution_evidence` — inspect and rehash saved results. Neither reruns an experiment nor certifies its physics.

The same workflow cannot be used for multiple completed/failed attempts. Prepare a fresh copy for a new experiment. Changing the test plan, source documents, settings, policy, companions or compiled artifacts invalidates the relevant binding.

`run_offline_test` supports the original backend's offline frequency-scan/FSAT contract, not arbitrary Python or shell code. It needs an appropriate `offline_frequency_scan` plan, compiled evidence and an installed FSAT executable. It never queries or starts a rack itself. Runtime warmup is wall-clock scheduling and must not be reported as precise simulator elapsed time.

## Limitations

Static topology is a parser over local RTFX/MLIB data, not a complete vendor API or proof of circuit correctness. Missing/ambiguous definitions, unsupported expression syntax and dependency discovery failures must remain visible. Some Runtime signal objects, hierarchical models, plot formats and API releases may be unsupported. The first public alpha does not include the prototype's experiment-specific acceptance plugins or verified error catalogue. It reports execution/evidence status without generating an inherited engineering pass.

## Change Kp and Ki together while preserving the original

This workflow can finish its software portions without any RSCAD connection or rack.

1. Read capabilities and the project overview, then hierarchy, exact controller context/UUID, stored parameters, and relevant ports. Keep source hash, parser warnings/coverage, and `snapshot_id`. A source-root listing is explicit; default listing shows published working copies.
2. Index the relevant permitted project with `rtds-agent knowledge parameters --project PATH`. Use `lookup_parameter` for Kp/Ki with the returned catalog snapshot. Confirm each parameter's type, old value, units, range, and definition hash. Migration of an existing legacy catalog is explicit; see [MIGRATION.md](MIGRATION.md).
3. Call `apply_parameter_patch_batch` once. The following illustrates the request shape; replace every identity/hash/value with inspected evidence. The two operations must target a real supported component, not an assumed controller shape.

```json
{
  "request": {
    "schema_version": "1.0",
    "source_project": "D:\\Projects\\controller.rtfx",
    "source_sha256": "replace-with-inspected-source-sha256",
    "rscad_version": "2.7.3",
    "project_label": "controller-kp-ki",
    "parameter_catalog_snapshot_id": "replace-with-selected-snapshot-id",
    "operations": [
      {"op": "set_parameter", "component_id": 1, "context": "subsystem:0", "component_type": "synthetic_controller", "parameter": "Kp", "expected_old_value": "1", "new_value": "2"},
      {"op": "set_parameter", "component_id": 1, "context": "subsystem:0", "component_type": "synthetic_controller", "parameter": "Ki", "expected_old_value": "0.1", "new_value": "0.2"}
    ]
  }
}
```

4. Re-read both parameters in the returned `working_project`, inspect `detail_diff` and companion/source preservation, and call `compare_project_versions` and `validate_project`. Follow pagination with the returned snapshots. Require only the intended parameter changes; record any ambiguous identity, changed definition evidence, incomplete coverage, or unexplained difference. `compare_projects` only supplies a summary.
5. Evaluate the prepared baseline/candidate JSON artifacts with `evaluate_results`. Bind each artifact to its actual project hash and declared run/attempt identity. Specify exact channels, units/sign/base/time basis, inclusive windows, and user-defined or cited criteria. Reference comparison requires identical sample times. Use metrics-only `min_max` when acceptance criteria are missing; do not invent pass thresholds.
6. Optionally save the separate result assessment. Report original/copy hashes, catalog and patch evidence, static comparison findings, raw-data/specification hashes, measured requirement outcomes, and remaining uncertainty. A synthetic software result is not a real model/rack qualification.
7. Only if this task's live operation is authorized and capabilities/policy/plan/target conditions are ready, continue the existing prepare/compile/fresh-request/run sequence above. Preserve exact control readback, restoration, stop and cleanup. Otherwise identify live integration as not executed and retain the completed offline results.

## Diagnose the relevant compile attempt

Use `get_workflow_status`, `revalidate_execution_evidence`, and `get_execution_diagnostics(workflow_path, stage="compile")`. The workflow's attempt journal and result references must agree on attempt identity, input hashes, and saved artifacts. This does not select an arbitrary historical attempt or rerun the compiler. Use the correct workflow and inspect its returned `attempt_id`; an old success is not evidence of the current attempt's success.

Diagnostic rows retain message/severity, attempt, source hash and JSON location. Only an exact unambiguous context/UUID match links a component; absent or conflicting identity stays `unknown`. Interpret original manual evidence before proposing a supported numeric correction. Native text/binary logs without an adapter remain `unsupported` with source references. An empty partial log never implies no diagnostics; unsupported/incomplete/stale evidence and separate grounding/structure/execution/data/requirement states remain visible. Do not invent an automatic repair or retry after uncertain Runtime cleanup.

## Interpret numerical results

The current adapter accepts supplied JSON samples, with a maximum 20 MiB file, 64 channels, and 100,000 samples per channel. It does not read Runtime CSV or vendor capture formats directly. See [the sample and requirement contract](TOOL_CONTRACTS.md#numerical-assessment-request).

Use `read_result_samples` to inspect bounded inclusive sample windows with source-hash-preserving pagination. Supported criteria are interval min/max, inclusive range, sampled settling band, and absolute/relative reference error with optional RMSE bound. Artifact and specification hashes are checked; units, per-unit bases, sign convention, time basis, capture interval, and optional sample-gap requirements remain explicit. No implicit conversion or time resampling occurs. Empty criteria produce metrics and `not_evaluated`; invalid samples or insufficient data make affected criteria inconclusive. Run/attempt IDs are checked against the supplied artifact and do not authenticate an actual simulator run.

An assessment's numerical status is separate from `engineering_verdict: not_evaluated`. `save_result_assessment` stores a separate deterministic local report without modifying approved workflow hashes. Preserve raw capture evidence and the documented provenance of any separately produced input adapter.

## Optional task skills

The package includes nine instruction-only skills: `rscad-understand-model`, `rscad-edit-model`, `rscad-diagnose-compile`, `rtds-run-experiment`, `rtds-validate-results`, `rtds-ground-with-manuals`, `rtds-read-documentation`, `rtds-derive-test-requirements`, and `rtds-verify-grid-code`. Versioned JSON manifests describe their tool/capability requirements. They use actual public tools and keep unsupported operations explicit. Unknown-source routing is explained in [UNKNOWN_RESOLUTION.md](UNKNOWN_RESOLUTION.md); new engineering flows are in [V2_DEVELOPMENT.md](V2_DEVELOPMENT.md). The earlier seven/six-skill discovery records below are historical checkpoints, not new model-driven qualification.

```powershell
rtds-agent skills list
rtds-agent skills export --destination ".agents\skills" --dry-run
rtds-agent skills export --destination ".agents\skills"
```

The destination is an explicit example for a chosen repository. Export adds named skill directories and refuses existing skill directories, traversal, symlinks, or junctions; it does not select a user-global location or modify host configuration. `--skill NAME` can select a subset. Dry-run performs no writes. Export itself reports that host discovery has not been verified.

The [official skill documentation](https://learn.chatgpt.com/docs/build-skills), checked on 2026-09-05, documents repository `.agents/skills` discovery from the current working directory up to the repository root and user `$HOME/.agents/skills`. The installed Codex CLI/Desktop version observed was `0.153.3`. An isolated temporary repository export was actually discovered through that version's app-server `skills/list`: all six entries were enabled with repository scope and no discovery errors. No global install or model/rack request was made. The optional `RTDS_TEST_CODEX_DISCOVERY=1` test reproduces this local check; it is distinct from skill lint and from an agent completing an engineering task.

For an installed distribution, run `python tools/wheel_check.py PATH_TO_WHEEL` from the source/release-check checkout. It creates a separate temporary venv, installs the wheel and constrained dependencies, verifies imports originate in that venv, runs the synthetic demo and actual STDIO contract check, and reads/exports packaged skills. `--wheelhouse PATH` selects local dependency wheels without a package index. No active operator settings or API keys are inherited by the checked product calls.


A qualitative independent review of the six skills also exercised three hypothetical requests: combined Kp/Ki plus supplied-data comparison without live authorization; a current compile failure alongside an earlier success and ambiguous component identity; and a diagram-dependent manual question without a renderer. The reviewed paths selected relevant inspection/edit/assessment or diagnostic/manual tools, kept live execution unauthorized, preserved ambiguous identities, and continued text-only work while leaving the diagram unverified. This is a workflow review, not an executed model/rack qualification or evidence that every future agent invocation will succeed.

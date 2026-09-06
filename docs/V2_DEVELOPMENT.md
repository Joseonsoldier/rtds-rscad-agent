# Engineering development v2.0

WP-N04 implements an opt-in acquisition session inside the existing Runtime/suite execution path and adds read-only native preparation and receipt conversion to `capture_rtds_results`. This supersedes the earlier converter-only scope for explicitly native workflows. Legacy behavior remains the default. Live native capture and authoritative event timing remain unqualified; see [NATIVE_CAPTURE.md](NATIVE_CAPTURE.md).

The partial WP-N05 [event timing contract](EVENT_TIMING.md) adds debug/model-native schedule fields and offline evidence from supplied clock-channel values without interpolation. Timing observations retain conservative error brackets and cannot be reused or reordered. Model-native workflows may plan, prepare and assess, but live dispatch and Runtime grant creation are refused before the backend; no SDK scheduler adapter or native `initial_conditions`/source-only-clock-evidence Draft sweep is supported. Core timing tests are synthetic, with no real RSCAD, Compile, Runtime, rack or GUI activity; this is not complete WP-N05.

The subsequent [native checkpoints](NATIVE_EDITING.md) add a bounded existing-component SDK backend, GROUP inspection and source-derived insertion/wiring or GROUP clipboard reconstruction with explicit UUID/context mapping. Reconstruction is synthetically tested; its local new-case trial stopped on file identity with cleanup unconfirmed. This supersedes the earlier software-unavailable statements below. Live construction, Runtime and full closed-loop qualification remain pending.

The v2.0 work order is implemented as bounded software extensions to the existing workflows. Full MCP now has 49 tools: all previous 43 plus six engineering entry points. No dependency, supported FX target, execution policy or existing grant is migrated automatically. Native structural qualification, native Compile-log grammar, actual Runtime/rack experiments and general DFX generation remain separate, uncompleted qualifications.

## Component discovery and project policy

`search_component_catalog(query, limit=20, offset=0, snapshot_id=None)` searches installed definition names and relative library paths. Pin the returned `catalog_snapshot_id` on subsequent pages. `get_component_schema(component_type, definition_id=None, parameters=None, context="subsystem:0", snapshot_id=None)` returns parsed parameter types, defaults, bounds, selector labels and active nodes for explicit values/context. A duplicate basename needs an exact `definition_id`; unresolved names never become a guessed component. Stored model values remain distinct from definition defaults.

The catalog hashes at most 12,000 files, 2 MiB per file, 128 MiB total, with 16 directory levels and a bounded traversal. It refuses links, rechecks the inventory and includes reader/parser/configuration evidence in its snapshot. Schema output is limited to 500 parameters, 2,000 nodes and the existing 100,000-character JSON guard. Unsupported definition syntax, port meaning and placement restrictions remain explicit. No SDK import or index persistence is needed.

The structural editor reads `rtds-component-policy.json` beside the source project. An absent policy denies edits; empty allowlists allow nothing; deny overrides allow. An operator authors this file outside MCP. There is no policy write/enable tool. For example, a policy for an authored component could contain:

```json
{
  "allowed_components": ["synthetic_gain", "WIRE"],
  "denied_components": [],
  "allowed_parameters": {
    "synthetic_gain": ["Gain", "Name", "Mode"],
    "WIRE": ["x1", "y1", "x2", "y2"]
  },
  "structural_edits": true
}
```

`inspect_rscad_project` returns this policy's read-only status/rules/path/hash so an MCP client can construct the edit request. Invalid policy is reported without disabling legacy model inspection; the editor still rejects it. Policy hashes are separate from the existing model snapshot. This policy controls isolated file edits only. It cannot authorize Compile, Runtime, rack access or hardware I/O. Existing numeric batch edits retain their existing catalog-based contract and do not acquire a new policy prerequisite.

## Structural candidate transactions

`edit_rscad_model(request)` uses [the exact packaged schema](../src/rtds_agent/schemas/model_edit.schema.json). Required bindings are source path/hash, project snapshot, policy file hash, label and 1–64 operations. First call `mode: preview`, inspect the semantic diff and all model-check findings, then call `mode: apply` with the returned `preview_id`. Changing any reviewed input, policy, definition or candidate invalidates that preview. A preview can create a private temporary transaction but cleans it up and publishes no project.

| Operation | Supported scope |
|---|---|
| `set_parameter` | Stored REAL/INTEGER field, exact old string, finite declared bounds. |
| `set_selector` | Stored TOGGLE field, exact old/new declared labels and resolved active-node expressions. |
| `set_string` / `rename_component` | Stored NAME/CHAR/TEXT/CHARACTER fields; rename requires NAME. No FILE/path rewriting. |
| `move_component` | Exact previous location and new bounded integer coordinates. |
| `insert_component` / `clone_component` | `component_id` identifies an existing same-context template. Explicit fresh globally unused UUID, location and validated stored-field overrides. No blank component generation. |
| `create_wire` | Existing WIRE template, unrotated and unmirrored; explicit new UUID and distinct endpoints. Coordinates use the existing parser's pixel representation. |
| `rewire` | Existing WIRE, exact old x1/y1/x2/y2 strings, new endpoints; same orientation constraints. |
| `remove_component` / `remove_wire` | Complete simple records in DFX-only archives. Archives containing opaque non-DFX/RTX records are rejected because reference removal is unqualified. |

The pipeline is hash-bound source snapshot → private working copy → verified DFX transformation → save → static reopen/reparse → expected record comparison and semantic diff → model check → source/definition/companion/policy recheck → atomic publication. Copies keep archive members, comments and all non-DFX bytes. Policy and required companions travel unchanged. Successful copies have a `structural_model_edit.json` marker and appear in project listings. Failed transactions are removed from the verified staging root.

Models need complete component identification, resolved definitions/nodes, no parser warnings and at most 2,000 parsed components. Hierarchy mutation and cloning/deleting records with unknown metadata are rejected. A checker error blocks publication; warnings and changed connectivity remain in the reviewed preview. `status: completed` means the file transaction completed; `integration_qualified: false` and the static-only qualification remain. The editor never calls the SDK, clipboard, Compile, Runtime or a rack. The older `preview_selector_change`/`prepare_extension_trial` tools keep their unchanged-copy contracts.

## Model checks, diagnostics and representations

`check_rscad_model(project_path, snapshot_id=None, electrical_rules=None)` checks duplicate identities, declared parameter counts/values, selector labels, potential unconnected ports/dangling endpoints, incompatible declared signal types and potential multiple drivers. Symbolic numeric expressions are unresolved warnings, not automatically invalid numbers. Findings contain severity, affected identity, evidence, likely cause, suggested fix and `autofix_available: false`.

Electrical rules explicitly bind context/UUID/parameter/units and provenance. Supported kinds are positive, range, equal and ratio; fields and tolerances must match the selected kind. They can express nominal-frequency/base/transformer-ratio/physical-parameter checks only when the caller supplies the actual mapping. There is no inference from a parameter name, no unit conversion and no authenticated engineering interpretation. Missing rules, placement constraints, required/optional semantics, hardware allocation, timestep compatibility and dynamic stability are reported as not evaluated. `no_errors_in_checked_scope` is not a general model pass.

`get_execution_diagnostics(..., include_grounding=True)` adds exact installed exception-class evidence, an explicitly limited ranked cause, local manual references and the already resolved component/definition evidence. `CommunicationError`, `ConnectionSetupError` and `RSCADError` are matched by reported type, not guessed message text. A missing SDK declaration yields no asserted cause. Native Compile-log grammar/message codes remain unqualified; arbitrary native logs are retained as hash-bound references. There is no automatic repair or retry. A reviewed correction starts a new edit/preview and a new workflow; consumed or failed actions are never reused.

`inspect_rscad_project(..., representation="ir")` returns a versioned parsed-subset IR containing hierarchy, components, parameters, ports, connections, coordinates and source/coverage metadata. `representation="mermaid"` returns deterministic, escaped static graph text, bounded to 500 components/1,000 nets. It is not a GUI screenshot or a complete electrical drawing. An IR→general DFX serializer is deferred until native structural round trips are qualified; no external generator code or vendor templates are distributed.

## Saved native results and metrics

`capture_rtds_results(request)` converts an existing native long-form CSV to the existing canonical JSON sample adapter. [Its schema](../src/rtds_agent/schemas/result_capture.schema.json) offers `supplied_csv` with explicit source/project/run/attempt hashes, or `workflow` with a saved workflow whose Runtime/Compile/result/attempt evidence is rechecked. Neither mode starts an acquisition session. Explicit channel metadata supplies exact signal path, units, sign convention and pu base; time basis is declared by the caller. Native CSV columns must be exactly `channel_id,signal_path,units,sample_index,time_s,value`, with contiguous zero-based sample indices per channel. Missing/extra channels, wrong identity/units, nonfinite values, nonmonotonic times and stale hashes fail. Limits remain 20 MiB, 64 channels, 100,000 samples/channel. Canonical artifacts publish atomically under `data/results` with source provenance and an observed uniform sample rate, or null when nonuniform.

Existing `evaluate_results`/`save_result_assessment` add `kind: power_metric`, `metric`, exact `metric_options`, and optional `metric_acceptance: {lower, upper, units}`. All normal requirement identity, interval, channel units/sign/pu-base and provenance fields still apply. Calculation without acceptance returns `not_evaluated`; numerical acceptance never changes `engineering_verdict`.

| Metric | Options and definition |
|---|---|
| `voltage_nadir`, `frequency_nadir` | Empty options; minimum sampled value. |
| `RoCoF` | Empty options; Hz input, maximum absolute adjacent finite difference, Hz/s output. No smoothing. |
| `voltage_recovery_time`, `active_power_recovery`, `settling_time` | `lower`, `upper`, `event_time`; time from event to first sample after the last band violation through capture end. Unobserved recovery is inconclusive. |
| `reactive_power_peak` | Empty options; maximum absolute sample. |
| `reactive_current_injection` | Empty options; maximum signed sample under the declared sign convention. |
| `overshoot` | `baseline`; positive peak above baseline, in channel units, not percent. |
| `oscillation_frequency` | `baseline`; mean period of at least three rising crossings with linear crossing-time estimation. |
| `damping_ratio` | `baseline`; logarithmic decrement of at least three strictly decaying positive peaks. Single-mode assumption is not verified. |
| `angle_separation` | `other_channel_id`; maximum principal wrapped difference, matching deg/rad metadata and exact time alignment. |
| `THD` | `fundamental_hz`, integer `harmonics` 2–50; coherent rectangular DFT of harmonics 2…H relative to fundamental, percent. Requires uniform sampling, ≥2 whole cycles in N×dt and all requested harmonics below Nyquist. |
| `current_limit_duration` | `threshold`; sum of left-sample-held intervals where current magnitude meets/exceeds threshold. |

These are discrete-sample definitions and estimates. Behavior between samples, actual event latency, general oscillation modes, PLL synchronization, GFM interactions and collapse margins are not established.

## Experiments, sweeps and traceability

`run_experiment_suite(request)` implements [a canonical JSON DSL](../src/rtds_agent/schemas/experiment_suite.schema.json), not a free-text/Gherkin interpreter. Authored runnable examples are in [the experiment tests](../tests/test_experiment_suites.py). It has exact control mappings/units/expected initial values, initial conditions, an event array, channels, capture limits, criteria and document traces. Fault/clear/trip/reclose/reference labels describe caller intent; only explicitly supplied control writes implement them. Durations expand into explicit clear actions. Repeated targets form expected-value chains and restore to the original value through the existing driver. Same-target simultaneous writes, duplicate aliases, wrong units and events beyond capture are rejected.

Event times are controller wall-clock delays after run confirmation, as in the existing Runtime driver. They are **not qualified deterministic simulator-time fault scheduling**. High-precision protection/grid-code timing requires separately verified model-native event mechanisms and actual measurements.

Modes are:

1. `plan`: validates requirements, targets and cartesian/paired matrices; returns immutable content-derived suite/run IDs and exact native plans without creating workflows.
2. `prepare`: requires the reviewed `suite_id`; reuses atomic numeric editing for Draft sweeps and the existing isolated workflow preparation. Repeating it resumes existing validated runs. Draft axes require an already audited parameter catalog and explicit string values; event/initial-value axes require numeric values. Paired axes have equal lengths. Maximum 8 axes, 32 values/axis, 64 sequential runs.
3. `execute`: requires exact selected run/action/workflow hashes. Compile's optional `expected_workflow_sha256` is checked inside the existing execution lock. Runtime requires an existing explicit request path/hash from `prepare_simulation_run`. This mode neither enables policy nor creates Runtime grants. One action/run/dispatch; no multi-rack parallelism. Successful, unchanged, revalidated evidence is skipped on repeat. Interrupted/failed actions need a fresh reviewed workflow. Compile failures are isolated; any Runtime failure stops further dispatch because restore/stop may be incomplete.
4. `assess`: evaluates supplied captures bound to each prepared model/workflow, retaining run IDs, axis values, requirement traces, assessment hashes, status counts and unsupplied runs. Supplied attempt IDs do not independently prove simulator execution.

Traces map document path/hash/page → requirement ID/statement → declared event/channel IDs → explicit criterion → saved assessment. Actual source bytes/page availability are verified; the clause interpretation and electrical meaning are not authenticated. Cited-document criteria require traces. Reference-error comparisons still use `evaluate_results` directly with an explicit reference artifact; suites do not infer a reference. These outputs are not grid-code certification.

## Tool profiles, skills and evaluation

Default `rtds-agent mcp serve` keeps all 49 tools. Optional `--profile core` exposes 10 workflow entry points; `--profile engineering` exposes 29 including discovery, schemas, comparisons and grant preparation. Profiles change advertisement only, never policy or runtime authority. Core is intentionally compact; switch to engineering/full for prerequisite discovery not advertised there.

All nine packaged skills carry versioned `manifest.json` metadata: required/optional tools, capabilities, minimum API context, safety class, tags and examples. The two additions are `rtds-derive-test-requirements` and `rtds-verify-grid-code`. They remain instruction-only, explicitly exported without overwriting or changing host configuration.

[Nine benchmark contracts](../evals/tasks.json) cover unknown API, inspection, Kp/Ki atomicity, duplicate identity, diagnostics, model building, LVRT specification, result assessment and unsafe-operation rejection. `python tools/run_evals.py --case EVAL-01 --trace TRACE.json` scores recorded calls/evidence/final state. It does not run a model or authenticate a supplied trace. Synthetic scorer tests and direct/STDIO scenarios are not model-driven evaluation results.

## Qualification boundaries

The 2026-09-05 installed-source check hashed 1,590 definition files, resolved the actual GAIN schema and three exact SDK declarations, rejected an invented log API, and preserved all 70 previously protected files. SDK imports, process launch and socket connections were blocked during that probe. This proves only the static source routes.

No new RSCAD connection, native structural edit/reopen, Compile, Runtime, rack query/reservation/connection or GUI action was performed for v2.0. Existing earlier isolated native open/read/save/reopen evidence remains in its original report; it does not qualify the new editor. Compile still lacks established rack-free operation. Actual live validation requires a specified isolated model, exact proposed actions and separately authorized scope. The v2.0 software work does not change that restriction.

The installed `Case.compile` declaration has a `None` return annotation, while the existing native driver checks a truthy observed return in addition to artifact/safety checks. The connected implementation's actual return semantics have not been measured. They remain a native compatibility question; this work does not change a failed/unknown native result into success based only on the annotation. LockFree group matching was corrected to exact hierarchy segments without changing its identity/readback/restore constraints.

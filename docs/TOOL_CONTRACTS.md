# Public tool contracts

WP-N11 adds only [development evaluation tooling](MODEL_EVALUATION.md). Its eleven-tool synthetic recording server is not a production MCP profile. Public names, signatures, policies and output contracts remain unchanged; recording envelopes appear only in explicit evaluation runs.

WP-N10 adds the read-only CLI `lines list`, `lines inspect ABS_TLI --sha256 SHA`, `lines preview ABS_REQUEST_JSON` and `lines verify ABS_CONSTANTS_REQUEST_JSON`; no MCP tool/signature changes. The strict source-bound schemas, positive scalar profile, exact numeric preview, supplied TLI/TLO comparison and byte limits are documented in [LINE_AUTHORING.md](LINE_AUTHORING.md). Constants verification returns zero only for numerical consistency. Bound generation records remain unauthenticated declarations; neither consistency nor parsing/preview establishes freshness, native constants generation, Draft connectivity or Compile success.

WP-N09 retains the `get_execution_diagnostics` signature and adds `native_compile_analysis` only when a saved Compile result contains a strict `native_compile_logs` receipt. Workflow, attempt, action and both input hashes must match; raw files are bounded, linked paths refused and nested hashes rechecked after interpretation. Collection declarations, parser coverage and recorded execution remain separate. Old standalone text `result_ref` is still unsupported. Structured logs now retain operational/cleanup errors; failed attempts and native receipts cannot claim complete empty success. The read-only `diagnostics list` and `diagnostics corpus` CLI commands add no MCP names (profiles remain 50/10/30). The backend does not automatically publish native receipts. See [formats, receipt and corpus contracts](COMPILE_DIAGNOSTICS.md).

WP-N08 appends optional `rulepacks=None` to `check_rscad_model`, retaining its old required inputs and legacy `electrical_rules` behavior. Strict schema 1.0 supports ten organizational domain labels and sixteen explicitly selected numerical criteria, with source hashes, scope, severity, confidence and exact model/definition/value/selector/quantity/unit/base bindings. Results retain passed/failed/inconclusive criteria and an assessment hash; criterion failures or unresolved observations add advisory findings to the model check. No automatic engineering applicability, repairs, SDK calls, policy changes or execution authority are provided. Tool counts remain 50/10/30. See [rulepack contract and limits](POWER_SYSTEM_RULEPACKS.md).

WP-N07 adds read-only `query_component_knowledge(request)` to full/engineering profiles (now 50/10/30 full/core/engineering). The request requires an exact `graph_id` and `mode`: `search` requires `query`; `get`/`neighbors` require `node_id`. Only neighbors accepts `depth` 1–2 and optional `edge_kinds`; all modes accept offset and limit 1–100. Unknown/cross-mode fields fail before reads. Explicit local CLI `knowledge graph build` publishes the cache; no MCP builder or automatic query indexing exists. Queries verify graph/current source/settings/implementation hashes and return advisory evidence with compatibility/integration false. See [graph contract, annotations and bounds](COMPONENT_KNOWLEDGE.md).

Native checkpoint additions: `edit_rscad_model.request.backend` accepts `static` (default), `native` or `auto`. Native supports existing flat Draft edits and one sole `{"op":"rebuild_draft","strategy":"insert"}` or `strategy:"clipboard"`. Rebuild requires one subsystem, 1–500 globally unique saved component IDs, no saved Runtime records/opaque payloads, and an operator policy allowing every type (including GROUP); insert also requires all stored parameters to be allowed. Insert is flat only. Clipboard maps hierarchy contexts and GROUP membership explicitly. A reconstruction preview returns a bound plan and `candidate_sha256:null`; apply returns the observed candidate hash only after saved/reopened verification. `reconstruction.uuid_mapping` identifies old/new IDs; translation is per context and ambiguous matches fail. The plan declares exact source empty-RTX preservation after native close if only canvas dimensions differ; raw native DFX is retained. New temporary-file provenance and source-bound GROUP-local readbacks are mandatory. Auto only previews/plans and refuses apply. Public native construction is synthetically tested; three local adapter/Compile trials do not establish public live apply or general integration. This mixed tool retains live/destructive annotations; current profile counts are 50/10/30. See [scope, journal and qualification](NATIVE_EDITING.md).

The local STDIO server uses an explicit allowlist. Treat the connected server's `tools/list` input schemas as the callable contract; the repository's independent smoke test detects missing, renamed, or unreviewed tools. Optional project-query fields are additive. No tool enables policy, runs arbitrary code, writes arbitrary paths, changes rack/hardware configuration, saves a running case, or deploys.

The partial WP-N05 [event timing contract](EVENT_TIMING.md) adds optional debug/model-native schedule evidence from supplied clock-channel values, with conservative timing-error brackets and no interpolation. Model-native live dispatch and Runtime grant creation are refused before the backend; no SDK scheduler adapter, native `initial_conditions`, or source-only-clock-evidence Draft sweep is supported. Omit timing to keep legacy plans and behavior.

WP-N06A adds optional `check_rscad_model(..., initialization=None)` read-only planning and supplied-evidence inspection; see [load-flow initialization](LOADFLOW_INITIALIZATION.md). Enabled legacy Runtime `loadflow_initialization` is refused before backend/rack/grant access, while omitted or disabled initialization is unchanged. The SDK compatibility finding is that frequency is the first argument, and LF must precede Compile; no qualified live adapter or automatic compiled-artifact mutation is provided.

## Read tools

WP-N04 adds `capture_rtds_results` modes `prepare_native` (read-only, no grant) and `workflow_native` (saved receipt/CSV conversion, no metadata overrides). Native acquisition executes only through the existing Runtime/suite policy and one-use-grant path. Exact fields, hash bindings, compatibility and recovery are in [NATIVE_CAPTURE.md](NATIVE_CAPTURE.md).

The v2.0 checkpoint introduced 49 tools; WP-N07 adds one read-only query for a current total of 50. Six additions are `search_component_catalog`, `get_component_schema`, `edit_rscad_model`, `check_rscad_model`, `capture_rtds_results` and `run_experiment_suite`. Their fields, modes, bounds, qualifications and safety behavior are in [V2_DEVELOPMENT.md](V2_DEVELOPMENT.md) and the packaged JSON schemas. All previous 43 names remain in default full mode. Optional core/engineering profiles expose 10/30 names. The mixed-mode suite tool carries live/destructive annotations because execute mode can call existing guarded live actions; plan/prepare/assess do not call RSCAD.

Existing signatures add optional fields: `inspect_rscad_project(..., representation=None)` accepts `ir` or `mermaid`; `get_execution_diagnostics(..., include_grounding=False)` adds local evidence; `compile_project(..., expected_workflow_sha256=None)` pins the workflow hash inside the existing execution lock. Existing assessment kinds remain and `power_metric` is additive. Existing numeric tools retain their original policy/catalog requirements; only the new structural tool needs a component policy and reviewed preview.

| Tools | Contract and evidence |
| --- | --- |
| `get_capabilities()` | Reads package versions, configured/observed version evidence, installation files, optional dependencies, parameter catalog, policy, and per-feature qualification state. It does not import vendor code, launch a process, connect to RSCAD, or query racks. `dependency_available`, `statically_inspected`, and `integration_qualified` have separate meanings. `doctor` includes this report while retaining its legacy top-level fields. |
| `get_knowledge_status()`, `search_rtds_local(query, top_k)` | Local source/index readiness and hash-checked search results. Text search does not require Poppler. |
| `get_manual_page(source_path, page)`, `get_manual_section(source_path, start_page, page_count)` | Read permitted source text with 1-based page identity and source evidence. |
| `lookup_parameter(component_type, parameter, rscad_version, parameter_catalog_snapshot_id)` | Verify catalog DB/audit and current definition hashes. The snapshot argument is optional when matching definition identity is unique; ambiguity requires an explicit snapshot. Omitted `rscad_version` remains `2.7.3`. |
| `list_rscad_projects(limit, offset, source_root, snapshot_id)` | Lists published working copies by default. To list immutable sources, explicitly select one absolute configured `source_root`. Hidden/unpublished staging copies are excluded. |
| `inspect_rscad_project(project_path, snapshot_id)`, `get_project_hierarchy(project_path, limit, offset, snapshot_id)` | Static overview, hierarchy, parser coverage/warnings, and project/definition/companion/parser hash snapshot. |
| `find_components(project_path, query, limit, offset, snapshot_id)`, `list_components(project_path, scope, component_type, limit, offset, snapshot_id)` | Bounded component discovery. Exact context plus UUID is the comparison identity; a snapshot-specific component key is not a vendor persistent identifier. |
| `get_component(project_path, component_id, context, snapshot_id, limit, offset)`, `get_component_parameters(project_path, component_id, context, snapshot_id)` | Target records and stored parameters. Keep duplicate/ambiguous identities and stored/default provenance distinct. |
| `find_project_parameters(project_path, query, scope, component_type, limit, offset, snapshot_id)` | Searches stored parameter names/values with optional context/type filters. |
| `get_component_graph(project_path, scope, limit, offset, snapshot_id, member_offset, member_limit)` | Static net records with separate net/member pagination. |
| `trace_signal(project_path, component_id, port, context, limit, offset, snapshot_id)`, `find_unconnected_ports(project_path, scope, limit, offset, snapshot_id)` | Trace an exact observed port and report potential static disconnections. Trace reports same-net endpoints only; electrical phase ports are undirected. Unsupported port semantics remain explicit. |
| `compare_component_settings(project_a, project_b, component_id, ...)` | Detailed parameters for one exact component identity, including optional context and version snapshot constraints. |
| `compare_project_versions(project_a, project_b, ...)` | Detailed component/settings/parameter and normalized parsed-topology changes. `same_static_topology` ignores incidental net numbering/record ordering but includes explicit wire geometry. Duplicate comparison identities return ambiguity. |
| `compare_projects(project_a, project_b, snapshot_id_a, snapshot_id_b)` | Preserves the existing component-type count and coverage summary. It is not a substitute for detailed version comparison. |
| `validate_project(project_path, snapshot_id)` | Rechecks static parser consistency and source hashes. Passing does not prove compile success, electrical correctness, or dynamic stability. |
| `get_execution_policy()`, `get_workflow_status(workflow_path)`, `revalidate_execution_evidence(workflow_path)` | Read policy/workflow state and saved evidence. They neither grant authority nor rerun an experiment. |
| `get_execution_diagnostics(workflow_path, stage, offset, limit)` | Read one saved attempt's supported diagnostics; `stage` defaults to `compile`, with `runtime` / `offline_test` alternatives. Returns attempt/input/artifact hashes, raw-message locations, severity, exact context/UUID component mapping where unambiguous, and completeness. Native unsupported logs remain artifact references. Stale inputs never become current success, and empty partial logs do not mean no errors. It does not rerun. |
| `read_result_samples(source, channel_id, start_time, end_time, offset, limit)` | Read an inclusive bounded interval of one hash-bound JSON channel. `source` uses the artifact-reference schema below; default limit 100, maximum 500, with `next_offset`. No resampling or simulator call. |
| `evaluate_results(request)` | Evaluate existing bounded JSON sample artifacts against explicit requirements; described below. Reads only. |

Project-query pagination starts at `offset=0`. Pass the returned snapshot identifier on later pages; a nonzero offset without a snapshot or changed content is rejected. Project comparisons accept `snapshot_id_a` and `snapshot_id_b`. The snapshot is an observed content identity, not a persistent cache: current bytes are rehashed and reparsed. Inspect `next_offset`, truncation, warnings, and coverage rather than treating a page as the complete model.

`search_rtds_knowledge(query, top_k)` is the separate cloud read tool. It requires an explicitly configured store and authorized key; it does not upload documents. Other listed reads are local.

## Local output tools

`get_manual_figure(source_path, page)` keeps its legacy `path`, `source_sha256`, and `page` metadata, and adds a real MCP image block plus `source_id`, `source_path`, `image_sha256`, `mime_type`, `width`, `height`, `bytes`, `rendering`, and `cache_key`. Source hash/page/render settings key the local cache. Cached images are rechecked. Rendering is limited to a 50 MiB source, 5,000 pages, 1,800 pixels per dimension, an 8 MiB image, and a 45-second renderer timeout. A path-only result is not evidence that a client viewed the picture. Actual Codex model image ingestion/content recognition has not been evaluated; the separately reported host skill-discovery test does not establish it.

`apply_parameter_patch_batch(request)` accepts the strict structured [batch schema](../src/rtds_agent/schemas/parameter_patch_batch.schema.json). Required common fields are `schema_version: "1.0"`, `source_project`, `source_sha256`, `rscad_version: "2.7.3"`, `project_label`, and 1-20 `operations`; `parameter_catalog_snapshot_id` optionally pins catalog evidence. Each operation has `op: "set_parameter"`, integer `component_id`, exact `context`, `component_type`, `parameter`, and string `expected_old_value`/`new_value`. Extra fields, duplicate targets, booleans as integers, non-finite/out-of-range values, and unsupported types are rejected. All operations are verified before a private temporary copy is changed; reparse, detailed expected changes, original/companion hashes and archive-member preservation must pass before publication. The result includes `working_project`, source/copy hashes, manifest/request hashes, `detail_diff`, and actual catalog snapshot IDs. This file transaction does not promise rack rollback.

`apply_parameter_patch(source_project, source_sha256, component_id, context, component_type, parameter, expected_old_value, new_value, project_label, rscad_version, parameter_catalog_snapshot_id)` remains the single-edit compatibility wrapper over the same batch core. It does not support strings/selectors/structure changes.

`prepare_workflow(source_project, test_spec, grounding_paths)` publishes a grounded isolated copy and hash-bound workflow. Its `test_spec` advertises a structured union of [Runtime](../src/rtds_agent/schemas/runtime_test_spec.schema.json) and [offline FSAT](../src/rtds_agent/schemas/offline_test_spec.schema.json) JSON Schemas. `prepare_simulation_run(workflow_path)` prepares a fresh one-use Runtime request; it does not start the case.

`save_result_assessment(request)` evaluates and saves a separate deterministic local assessment under the configured data directory. It returns an assessment ID and file hash, refuses conflicting existing contents, and never rewrites historical workflows or approvals.

## Live tools

Runtime writes and suite controls require `object_subpage`, a nonempty exact live SDK page name of at most 256 characters. It is not derived from saved VIEW-ID. Runtime schema ID is 1.2 and suite schema ID is 1.1; old write plans must be prepared again. Current case/hash, unique type/name lookup, exact Runtime ID/subtab/page and expected current value must agree. Scope is rechecked before writes and restoration; ambiguity or changed identity fails closed. Read-only empty-write plans retain their contract.

`compile_project(workflow_path)`, `run_offline_test(workflow_path)`, and `run_simulation(workflow_path, request_path, request_sha256)` retain existing policy, installation, plan, project/dependency, compile-artifact, and one-use authority checks. Runtime remains bound to the compile rack and exact control/initial-value/readback/restoration/stop/cleanup requirements. The offline FSAT backend launches its permitted local executable; it does not itself start/query a rack. Task-specific live authorization and preparation are required even if policy is already active. No new recurring approval prompt is introduced inside an already authorized scope.

## Numerical assessment request

The source of truth is [result_assessment_request.schema.json](../src/rtds_agent/schemas/result_assessment_request.schema.json). The top-level object contains `source`, optional `reference`, `specification`, and `specification_sha256`. Each artifact reference requires `data_path`, `data_sha256`, `input_project`, `input_project_sha256`, `run_id`, and `attempt_id`. Data must be a permitted local `.json` artifact (at most 20 MiB), and the referenced project must pass its path/hash check.

The JSON sample adapter has this shape. Substitute actual provenance and samples; the illustrative hash text is not a valid request hash.

```json
{
  "schema_version": "1.0",
  "input_project_sha256": "replace-with-actual-project-sha256",
  "run_id": "supplied-run-identifier",
  "attempt_id": "supplied-attempt-identifier",
  "time_unit": "s",
  "time_basis": "simulator_time",
  "channels": [{
    "channel_id": "voltage",
    "units": "V",
    "sign_convention": "positive bus to ground",
    "times": [0.0, 0.5, 1.0],
    "values": [99.0, 100.0, 101.0]
  }]
}
```

There are 1-64 channels and at most 100,000 samples per channel. Times must be finite and strictly increasing; values must be finite numeric values with equal array lengths. Per-unit channels need a positive `pu_base`. The request's project hash/run ID/attempt ID must match the artifact. Those IDs are declarations, not independently verified simulator qualification.

`specification` contains `schema_version: "1.0"` and up to 64 uniquely identified `requirements`. Each requirement declares `requirement_id`, `kind`, `channel_id`, `units`, `sign_convention`, `time_unit: "s"`, `time_basis` (`simulator_time` or `wall_clock`), `start_time`, `end_time`, and `provenance` with `kind` (`user_defined`, `supplied_spec`, or `cited_document`) and `reference`. Compute `specification_sha256` with UTF-8 SHA-256 of `json.dumps(specification, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.

| Requirement kind | Additional fields and meaning |
| --- | --- |
| `min_max` | Inclusive-window minimum/maximum/sample count; status `not_evaluated` because there is no acceptance threshold. |
| `range` | Inclusive `lower`/`upper`; every selected sample must be within bounds. |
| `settling_band` | Inclusive bounds and `settle_after` inside the interval; checks samples at/after that time and reports a sampled settling time. |
| `reference_error` | Hash-bound `reference`, `absolute_tolerance`, `relative_tolerance`; optionally `reference_channel_id` and `rmse_limit`. Every absolute error must meet `absolute_tolerance + relative_tolerance * abs(reference)`; optional RMSE also must pass. |

`max_sample_gap_seconds` optionally bounds sampling gaps. Channel units, sign, time basis and pu base must match exactly; reference-error timestamps must match exactly. There is no sample resampling, reference interpolation, unit conversion or arbitrary expression evaluator. Existing native long-form CSV can be explicitly converted by `capture_rtds_results`; assessment itself still reads canonical JSON. Individual power metrics declare their estimators. Unsupported formats/kinds are validation errors. Missing/invalid samples or inadequate intervals produce `inconclusive` requirements; no criteria yields metrics and `not_evaluated`. A numerical `passed` status applies only to supplied requirements and samples. `engineering_verdict` remains `not_evaluated`, and caller-supplied criterion provenance is recorded without authenticating it.


## Offline extension investigation and trials

The earlier four extension tools remain available. The API-discovery checkpoint had 43 tools; the subsequent v2.0 additions bring full mode to 49. Existing numeric edits and live tools retain their required-input contracts.

| Tool | Input/output and side effects |
|---|---|
| `inspect_extension_support()` | Read only. Fixed bounded SDK files and API HTML under configured installation; returns source/declaration/doc/hash evidence and unqualified live capabilities. CLI equivalent: `rtds-agent extensions`. Does not import the SDK or invoke an executable. |
| `preview_selector_change(request)` | Read only. [Strict selector schema](../src/rtds_agent/schemas/selector_preview.schema.json) requires source_project/source_sha256/snapshot_id, component_id/context/component_type, parameter and exact expected_old_value/new_value. Only declared TOGGLE labels. Returns deterministic preview_id, before/after active nodes and affected existing nets. No changed archive; semantics/dependency effects are not_evaluated. |
| `prepare_extension_trial(request)` | Local write. Same selector request; requires resolved preview and complete current companions. Copies unchanged source/companion bytes under projects/.extension-trials, publishes a hash-bound prepared_unexecuted manifest, leaves candidate absent and hides trials from normal project listings. No actual selector edit, RSCAD call, policy change or engineering pass. |
| `inspect_runtime_layout(project_path, snapshot_id=None, offset=0, limit=100, representation="inventory")` | Read only; default paginated inventory, max 500 records/page. `representation="ir"` returns whole-document [semantic IR](RUNTIME_IR.md), requiring default offset/limit. Bounds: 10,000 records/32 nesting levels/16 MiB RTX, 256 pages, 2,000 graphs, 256 curves/graph, 20,000 references, 10 MiB IR. Missing layout is unsupported; duplicate/unknown records and unresolved IR references are partial. Snapshot includes project and parser/IR modules; it differs from project_snapshot_id. Saved COMP_ID-only candidates are not live targets; no GUI observation, current values, inferred units or overlay authoring. |

[Extension findings and exact unexecuted stages](EXTENSION_QUALIFICATION.md) distinguish confirmed API declarations from working, qualified integration. Native structural application, clipboard clone, native case save and screenshot tools are not exposed. V2.0 adds a separate bounded offline candidate editor. A prepared trial is not permission to connect or run.

## API discovery and evidence additions

Two additive read-only tools, search_rscad_api(query, top_k=10, expected_api_version=None, snapshot_id=None) and lookup_rscad_api(symbol, expected_api_version=None, snapshot_id=None), expose bounded static installed-source declarations. Search yields found/unresolved and candidates; lookup yields found/ambiguous/unresolved and never selects an arbitrary ambiguous target. Source hashes, lines, signature/docstring, snapshot and SDK version are returned. No vendor import or live call occurs. [Bounds, coverage, version interpretation and exact usage](UNKNOWN_RESOLUTION.md) are part of this contract.

Existing local search/page outputs add source type, evidence level, document/chunk/version/relevance metadata without changing their database schema or required inputs. Parameter lookups and project snapshot outputs add provenance labels; stored/default and configured/observed distinctions remain. Vector Store results are explicitly supplementary and never installed API verification. Existing result fields and execution safety contracts remain intact. The discovery checkpoint contained 43 tools; the current full registry contains 50.

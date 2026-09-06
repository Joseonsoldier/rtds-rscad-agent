# Load-flow initialization evidence

WP-N06A adds read-only initialization inspection to `check_rscad_model`. It checks declared operating points and supplied results against saved models. No Load Flow solver is invoked and no model, workflow, execution policy or grant is written. Reported convergence, saved-file consistency and actual solver qualification are separate.

## Installed-source findings

Read-only inspection of the installed SDK 1.1 found `Case.run_loadflow(frequency=60, threshold=1e-6, flat_start=True, algorithm="FAST_DECOUPLED", **kwargs)`. Its first argument is system frequency in Hz. The client raises returned `RSCADError` objects and otherwise discards the response, returning `None`. Neither `None` nor a test driver's `True` proves convergence. No solver timeout argument is established by the inspected signature and documentation.

The former Runtime hook incorrectly passed `timeout_seconds` into that frequency argument. It also ran Load Flow after Compile. The installed Introductory Tutorial, PDF pages 35–37 and 53, describes initialization that updates model parameters and requires subsequent Compile. SDK `State.modified` or unchanged saved bytes cannot prove equivalence between unsaved initialized parameters and the compiled case. Therefore enabled legacy Runtime initialization is now refused before backend/rack access or grant creation, including direct driver entry. The incorrect invocation is removed. Completion of an LF call provides no compiled-artifact hash exemption.

Installed `DOC/COMPONENTS/Features/loadflow.pdf` describes balanced three-phase Load Flow, bus labels and slack-bus prerequisites, temporary RAW input and `.lfo`, `.rst`, `.rpt` outputs. Definitions declare updates to source magnitudes/angles/P/Q, bus results, machine initial conditions and selected controls. These declarations are not evidence that those changes happened. Tutorial PDF page 55 distinguishes breaker assumptions for Load Flow from actual Runtime breaker state; page 106 does not establish automatic initialization of custom controls. No vendor document text or model is distributed here.

## Optional request

`check_rscad_model(project_path, snapshot_id=None, electrical_rules=None, initialization=None)` retains the previous result when initialization is omitted. The optional request uses the packaged `loadflow_initialization.schema.json`:

- `schema_version: "1.0"`, `mode: "preconditions"` or `"supplied_evidence"`, and exact `input_project_sha256`.
- `entities`: explicit `entity_id`, `role` (`source`, `generator`, `load`), context/component ID/type, requested operating point and stored parameter bindings. Quantities have explicit values, units, sign conventions and any required base. No electrical role or unit conversion is inferred from a name.
- `provenance`: permitted source paths, exact SHA-256 hashes and locators. Hash consistency does not authenticate an engineering interpretation.
- In supplied mode, `evidence` binds a JSON result file and the after-model path/hash/snapshot. Before and after remain read-only.

Each parameter binding records the requested `parameter`/`expected_stored_value` and separate `calculated_parameter`/`expected_calculated_stored_value`. For example, requested source P maps to `Pt`, while calculated P maps to `P`. Both require source-bound numeric definitions and matching units. Calculated quantities must exactly match the explicitly bound quantity set. Omitted P/Q/V/angle quantities are reported as not evaluated, so a partial mapping cannot establish complete initialization.

Precondition inspection returns a plan hash. A supplied artifact records that exact plan hash, before/after model hashes, reported solver status/warnings, entity initial states and declared parameter changes. Use the schema and tool output for the full bounded field contract. Stored values from an example are not new solver output.

Saved semantic comparison retains parameter, identity, settings, geometry, GROUP and topology changes and checks archive/non-DFX preservation. Unexplained or missing changes cannot establish consistent initialization evidence. Fresh model, companion, definition, evidence and provenance hashes are checked again before returning. An internally consistent caller-supplied `converged` report remains unverified; no result certifies the electrical network, unlocks Compile/Runtime or supplies a live convergence receipt.

## Compatibility

Tool profiles remain 49/10/29, with nine skills and unchanged Python/dependencies. The optional model-check argument and capability reports are additive. Runtime schema 1.5 accepts the exact disabled request `{"enabled": false}` and preserves enabled legacy requests for historical plan inspection. Live dispatch of enabled requests is intentionally no longer supported; prepare a separately qualified pre-Compile initialization workflow when that adapter becomes available. Existing omitted/disabled capture, grants, restoration and cleanup remain subject to their existing gates. Historical evidence is not rewritten.

## Actual execution and unfinished qualification

In this wave, one new isolated CH6 `gen1` copy was opened and compiled through the local API. Compile returned `True` in 1.187 seconds; the fresh success log, empty error log and matching 292,269-byte build/output binaries passed offline checks. All 18 RPCs were allowlisted, the input and 47 protected hashes remained unchanged, and exact case close/disconnect were verified. RSCAD reported 2.7. This is task-scoped Compile evidence, not a Load Flow, Runtime or general public integration pass. Python calls were restricted to loopback; background networking inside the separate Java application was not measured.

The simplest inspected future LF candidate is CH2 `acsys1`, with explicit source/slack/PQ declarations. CH1 Voltage Divider and CH5 `torque-spd` lack an explicit inspected slack bus; CH6 also has an exciter with stored `LFInit=No`. None is called LF-ready solely from those stored fields.

Pending local qualification must bind an exact isolated CH2 copy, check all LF prerequisites, invoke reviewed frequency/options, retain fresh solver files and before/after native parameter evidence, save the isolated copy, close/reopen and compare it, then Compile the initialized copy. Server-side rack/Compile behavior, output grammar/freshness, in-memory updates and recovery after interruption are unresolved. No live LF invocation, rack query/reservation/connection, Runtime start/control/capture or GUI operation occurred in this wave. WP-N05 live timing and WP-N06 live initialization remain incomplete; subsequent packages retain their dependency requirements.

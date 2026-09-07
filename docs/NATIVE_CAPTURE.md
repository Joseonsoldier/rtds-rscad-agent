# Native signal acquisition — WP-N04

The [2026-09-07 rack checkpoint](RACK_QUALIFICATION.md) exercised actual array reads through the older capture driver, with successful stop/close but a failed compiled-artifact integrity check. It did not qualify this opt-in transaction: the installed examples' unnamed graphs and duplicate saved container IDs still fail its discovery contract. Those checks remain unchanged.

The opt-in `native_signal_arrays` mode implements a bounded SDK array session inside the existing Runtime execution path. Software integration is tested with authored SDK doubles. This checkpoint performs no real connection, Compile, Runtime, rack query, load flow or GUI operation. Installed source inspection establishes an API surface, not live qualification.

## Prepare and acquire

Keep the existing workflow and single-use execution grant. In a runtime test specification set `runtime_capture.acquisition_mode` to `native_signal_arrays` and `minimum_samples_per_channel` to at least 2. The experiment-suite DSL accepts the same mode as `specification.acquisition_mode`. Each measurement channel requires:

```json
{
  "channel_id": "voltage",
  "signal_path": "Subsystem #1|Outputs|V",
  "units": "V",
  "sign_convention": "positive at measured terminal",
  "time_basis": "simulator_time",
  "pu_base": null,
  "metadata_evidence": {
    "source_sha256": "<SHA-256 of bound model or grounding document>",
    "locator": "<exact source location supporting these declarations>"
  },
  "runtime_identity": {
    "object_uuid": 101,
    "object_name": "Voltage",
    "object_subpage": "Plots"
  }
}
```

The example is authored, not an installed tutorial mapping. Supply real evidence before preparing a real case. A positive pu base is required for `pu`; other units may leave it null. Missing metadata, unknown live page, duplicate paths or ambiguous saved references fail preparation. A hash and locator bind a declaration to a source; they do not automatically verify its meaning. Receipts retain `metadata_semantics_independently_verified=false`.

1. `prepare_workflow` validates the native plan and grounding hashes before creating the isolated workflow.
2. `capture_rtds_results({"mode":"prepare_native","workflow_path":"..."})` returns the bound plan, saved discovery and plan hash without SDK import, grant creation or file mutation.
3. A separately authorized Runtime execution uses the existing policy, release/installation checks, Compile evidence and `prepare_simulation_run` / `run_simulation` grant. `run_experiment_suite` dispatches these same functions. Preparation does not authorize execution.
4. The driver binds the saved graph and a unique current typed/name lookup with exact Runtime ID, subtab, supplied page and current case/hash. The graph ID is distinct from its plot container and saved Draft COMP_ID. Saved COMP_ID is reported as a stored reference, not proof of the live signal source. Signal handles must use the exact request path and current Runtime owner. The SDK constructs the handle's path identity locally; this is not independent remote signal-ID verification.
5. After the existing Runtime start/update/wait path, read time, values, then time again. Changed axes, missing/empty/one-point arrays, nonfinite values, nonincreasing time or mismatched counts fail. Recheck source and live binding around reads. At most 64 channels and 100,000 samples across channels are accepted. Array limits are checked after the SDK returns; they are not RPC memory or hard-timeout guarantees.
6. `capture_rtds_results({"mode":"workflow_native","workflow_path":"..."})` converts the current attempt's raw CSV using its native receipt. It accepts no channel/time overrides. Run ID, actual journal attempt ID, project/source hashes, channel declarations, graph binding, sample counts, hashes and sampling intervals/rates must agree. Then use the existing `evaluate_results` tool with explicit requirements.

## Recovery and evidence

Recovery attempts run in this order: stop local acquisition dispatch, restore controls, stop Runtime, close owned acquisition handles, then existing case close/disconnect. Each acquisition stage records its own result and order. The SDK sources inspected here provide no verified remote acquisition abort method. `stop()` prevents further local pulls; it does not claim cancellation of an in-flight remote request. Unconfirmed stop/resource release never becomes safe completion. Remaining cleanup is attempted after a stage fails, without automatic retry.

The internal `runtime_execution.json` adds a version 1.0 `native_acquisition` receipt. It includes context (`run_id`, `attempt_id`, `input_project_sha256`), saved discovery, per-channel binding/metadata/sample hash/count/interval/rate, lifecycle state, and separate capture/recovery flags. Raw SDK numeric arrays are retained through the existing long-form CSV export. Capture success can coexist with restoration/stop/cleanup failure. Canonical conversion preserves that failure; a numerical criterion cannot establish whole-system safety.

## Installed SDK findings and limits

The read-only Python 1.1 source audit confirms `Case.get_signal`, `Signal.get_time_data`, `Signal.get_data`, and exact Runtime graph lookup/property declarations. `Case.update_plots` requests an asynchronous update. Separate Java bytecode inspection shows time values generated from plot finish-time/point settings and descriptor result arrays trimmed for trailing NaNs. These are SDK-returned samples, not untouched hardware acquisition bytes.

Equal before/after time arrays detect some window changes but do not prove an atomic snapshot, a fresh update, trigger alignment or the live simulator clock. Receipts explicitly leave freshness, atomicity, time origin and integration qualification unverified. Metadata time basis is source-bound declaration. WP-N05 must separately resolve deterministic simulator-time events; existing warmup/waits use wall-clock scheduling and are not authoritative event-time evidence.

No Runtime construction adapter is introduced. Many installed saved layouts contain duplicate IDs or unresolved references, so this strict mode can refuse them. It neither selects a preferred duplicate nor creates/edits a saved Runtime. Installed tutorial capture and real restoration/stop remain untested.

## Compatibility

Runtime schema ID is 1.3, suite schema ID 1.2, capture request schema ID 1.1. The optional mode leaves old runtime plans canonicalized identically; legacy array/meter/CSV behavior is unchanged. Native mode has no meter or CSV fallback. Existing `supplied_csv` and legacy `workflow` conversion remain, but `workflow` refuses an artifact containing a native receipt so metadata cannot be silently relabeled; use `workflow_native`. Canonical channel records additionally carry run/attempt/project identity and sample interval. There is no new public tool, dependency or policy activation path. Tool profiles remain 49/10/29 with nine packaged skills.

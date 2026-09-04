# Preparing and executing a case

The MCP server exports 25 tools. Document/source reads, project inspection, numeric-copy edits and run preparation are separate from live execution. Unlike the private prototype, a new user creates a fresh workflow instead of importing someone else's accepted experiment.

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

1. `get_execution_policy` and `get_knowledge_status`.
2. Search local sources and inspect the project. For numeric copy editing, first build a local parameter index through the CLI.
3. `prepare_workflow` with the planned capture and source documents.
4. `compile_project(workflow_path)` — uses a currently available permitted rack.
5. `prepare_simulation_run(workflow_path)` — returns a request path and hash without starting anything.
6. `run_simulation(workflow_path, request_path, request_sha256)` — executes the exact request and writes local result/cleanup evidence.
7. `get_workflow_status` and `revalidate_execution_evidence` — inspect and rehash saved results. Neither reruns an experiment nor certifies its physics.

The same workflow cannot be used for multiple completed/failed attempts. Prepare a fresh copy for a new experiment. Changing the test plan, source documents, settings, policy, companions or compiled artifacts invalidates the relevant binding.

`run_offline_test` supports the original backend's offline frequency-scan/FSAT contract, not arbitrary Python or shell code. It needs an appropriate `offline_frequency_scan` plan, compiled evidence and an installed FSAT executable. It never queries or starts a rack itself. Runtime warmup is wall-clock scheduling and must not be reported as precise simulator elapsed time.

## Limitations

Static topology is a parser over local RTFX/MLIB data, not a complete vendor API or proof of circuit correctness. Missing/ambiguous definitions, unsupported expression syntax and dependency discovery failures must remain visible. Some Runtime signal objects, hierarchical models, plot formats and API releases may be unsupported. The first public alpha does not include the prototype's experiment-specific acceptance plugins or verified error catalogue. It reports execution/evidence status without generating an inherited engineering pass.

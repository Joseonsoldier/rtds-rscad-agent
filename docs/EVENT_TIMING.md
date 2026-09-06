# Event timing — WP-N05 partial software checkpoint

The suite DSL can retain an explicit simulator-time schedule and assess supplied clock/state samples. There is no qualified live scheduler adapter. Model-native workflows support plan, isolated preparation and offline assessment; Compile, Runtime request creation and all live execution routes refuse them before backend/rack dispatch. No schedule is silently converted to host writes. This checkpoint makes no actual RSCAD connection, case mutation, Compile, Runtime, rack, GUI or load-flow call.

## Contract and preparation

Omitting `specification.event_timing` preserves legacy canonical plans and sleep/write behavior. Optional `{"mode":"wall_clock_debug"}` explicitly labels controller timing; observed simulator time/error stay null. The host's requested-delay accumulator excludes write/lookup latency and is not a measured simulator clock.

For offline native intent, add this field to an otherwise complete experiment DSL:

```json
{
  "mode": "model_native",
  "clock_channel_id": "clock",
  "source_evidence": {
    "source_sha256": "<SHA-256 of bound model or unchanged grounding document>",
    "locator": "<source location declaring clock/reset meaning>"
  },
  "observations": [
    {
      "action_id": "event.fault_on",
      "channel_id": "state",
      "window_start_seconds": 0.8,
      "window_end_seconds": 1.2,
      "value_tolerance": 0,
      "max_timing_error_seconds": 0.01,
      "max_sample_gap_seconds": 0.001
    }
  ]
}
```

This is authored syntax, not a mapping to an installed tutorial. The original event uses `event_id=fault_on`; a duration also creates `clear.fault_on`, which requires its own observation. State channels use the exact control units and sign convention. The separate clock channel declares units `s`, signal path and sign convention. The source hash/locator binds a declaration; it does not verify interpretation, reset linkage or the clock's epoch. For a Draft parameter sweep, clock evidence must come from an unchanged grounding source; an original model hash alone is refused before patch publication. No compatible native scheduler target is inferred from these declarations.

At most 64 DSL events expand into 128 onset/clear actions within 0–30 seconds. Contracts retain event/action/target IDs, transition kind, requested time, before/after values, units and per-action observation. Duplicate instants, inconsistent target value/unit chains, overlapping state-tolerance bands or incomplete observations are rejected. Native `initial_conditions` must be empty until their model-native representation exists; they are not silently omitted. Native schedules contain no Runtime parameter writes. Original control identities remain in the suite DSL, with no claim that their model-native actuation has been established.

`run_experiment_suite` plan returns the canonical timing contract and unqualified execution status. Prepare creates normal isolated/hash-bound workflows with no grant. A `qualified:true` field cannot override any gate. The canonical Runtime contract retains and hashes `event_timing`; an unsupported field cannot disappear into the legacy path. Runtime schema ID is 1.4; suite schema ID is 1.3. No new public tool, dependency, host setting or execution-policy change is introduced. Profiles remain 49/10/29, with nine packaged skills.

## Supplied timing evidence

Use existing suite `assess` mode with its canonical JSON sample reference. The standard loader verifies file/model hashes and run/attempt IDs. The public timing path checks each used channel's signal path, units, sign and pu base against the immutable DSL declaration, then rechecks source/plan hashes before publishing. It does not authenticate caller-supplied data as a simulator run.

Clock **values** provide the proposed simulator seconds; plot timestamps are used only for exact clock/state alignment. Require finite samples, strictly increasing nonnegative clock values, matching timestamp arrays, sufficient window coverage and bounded clock sample gaps. No interpolation, resampling or conversion is performed. Each action requires exactly one direct sampled transition between its declared states, with a predecessor in the window. Missing, multiple, reused or out-of-order transitions are inconclusive. An earlier transition cannot stand in for an event that never occurred.

The first post-transition sample supplies `observed_simulator_time`, with the prior/current clock values retained as a transition bracket. The report also retains signed `measured_timing_error_seconds`, absolute error, error bounds, sample indices, mechanism, time source, qualification state, context and contract/source hashes. These names describe observations from the declared clock channel; they are not independent simulator-clock verification. The physical transition is not known exactly between samples. Agreement passes only when the entire conservative error bracket lies within tolerance, fails when entirely outside, and otherwise remains inconclusive. Discrete endpoint arithmetic is not rounded into a pass.

Suite output keeps per-run `event_timing` reports and separate `timing_status_counts`; ordinary numerical requirement statuses stay separate. Every timing report retains `deterministic_verified=false` and `integration_qualified=false`, even when supplied samples agree. Event labels such as fault/trip do not establish electrical effects. Timing agreement cannot establish successful restoration, Runtime stop or overall system safety.

## Installed sources and unresolved operation

Read-only discovery examined installed definitions, Python API/local HTML, full relevant manual-page text and existing example files. Source identities and hashes remain in private validation evidence; vendor content is not distributed. Figures were not rendered or used to infer wiring.

| Evidence | Established scope | Still unresolved |
| --- | --- | --- |
| `rtds_sharc_ctl_SCHED` definition; Control Components manual §2.12.5, PDF pages 164–166 | Model elapsed-time/value lists up to 30 entries; List/File/Random selection, time units, initial value and repeat horizon | Compiled solver behavior, enable/reset epoch, exact timestep boundary, effect on a particular actuator |
| `rtds_sharc_ctl_TIME`; manual §2.12.1, PDF page 160 | Time output since its reset; seconds or timestep mode | Shared epoch with SCHED, timestep domain, current run provenance |
| Sequencer definition/manual §5.1, PDF pages 865–868 | Trigger-relative native delays and documented breaker/fault sequence concepts | Qualified Python submission/authoring path and absolute run-start alignment |
| Python `Case.get_plot_time_data`, `Signal.get_time_data`, PlotContainer time-zero properties and local HTML | Plot-window axes and declared signal-array surface | Authoritative simulator clock, atomic/fresh synchronized acquisition |
| Legacy Script Manual PDF pages 17–19 and sequencer examples | Historical breakpoint/resume/sequencer usage | Applicable supported Python methods or real-time actuation guarantees |

The inspected scheduler example is actively `SDS=File` and `Tu=min`, despite storing inactive list pairs. A compatible List/sec scheduler was not established in the inspected current/example targets. An existing-source numeric patch may eventually be viable after exact selectors, reset horizon, topology and output type are grounded; the existing atomic patch limit remains 20 operations. This wave adds no SCHED insertion, selector conversion, numeric schedule patch, RTX/SEQ writer or live retry. Bounded absence of Python declarations does not prove remote/dynamic absence.

WP-N05 remains partial. Qualifying a model-native path still needs a specified compatible isolated target, confirmed scheduler/reset/time-source wiring, documented API/authoring behavior, timestep-domain evidence, fresh synchronized capture, measured actuation error and verified recovery under a separately authorized serialized live trial. WP-N06–N11 remain pending.

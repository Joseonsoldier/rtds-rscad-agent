"""Canonical JSON experiment DSL and deterministic sequential sweep expansion."""
from __future__ import annotations
import copy
import itertools
from .state_machine import sha256_json
from .runtime_backend import validate_runtime_test_spec


def compile_spec(spec):
    controls = {c["target_id"]:c for c in spec["controls"]}
    if len(controls) != len(spec["controls"]): raise ValueError("Duplicate DSL control target_id")
    physical = [(c["object_uuid"],c["attribute"]) for c in controls.values()]
    if len(set(physical)) != len(physical): raise ValueError("One physical control cannot have multiple DSL aliases")
    events = spec["events"]
    if len({e["event_id"] for e in events}) != len(events): raise ValueError("Duplicate DSL event_id")
    initials = spec["initial_conditions"]
    if len({i["target_id"] for i in initials}) != len(initials): raise ValueError("Duplicate initial condition")
    channels = spec["channels"]
    if len({c["channel_id"] for c in channels}) != len(channels): raise ValueError("Duplicate measurement channel")
    scheduled = []
    for initial in initials:
        scheduled.append({**initial,"action_id":"initial."+initial["target_id"],"at_seconds":0,"phase":"before_run"})
    for event in events:
        scheduled.append({**event,"action_id":"event."+event["event_id"],"phase":"after_run"})
        if "duration_seconds" in event:
            scheduled.append({**event,"action_id":"clear."+event["event_id"],"value":event["clear_value"],
                              "at_seconds":event["at_seconds"]+event["duration_seconds"],"phase":"after_run"})
    scheduled.sort(key=lambda e:(e["phase"] != "before_run", e["at_seconds"],e["action_id"]))
    writes, last, instants = [], {k:c["expected_initial_value"] for k,c in controls.items()}, set()
    for event in scheduled:
        key = event["target_id"]
        if key not in controls: raise ValueError("Event target is not declared exactly")
        c = controls[key]
        if event["units"] != c["units"]: raise ValueError("DSL control units mismatch; no conversion")
        if event["at_seconds"] > spec["capture_after_seconds"]: raise ValueError("Event ends after capture")
        instant = (key,event["phase"],event["at_seconds"])
        if instant in instants: raise ValueError("Simultaneous writes to the same target are ambiguous")
        instants.add(instant)
        writes.append({**{k:v for k,v in c.items() if k not in {"target_id","units"}},"action_id":event["action_id"],
                       "expected_initial_value":last[key],"value":event["value"],"apply_after_seconds":event["at_seconds"],
                       "phase":event["phase"],"restore_after_capture":True})
        last[key] = event["value"]
    result = {"test_id":spec["test_id"],"execution_mode":"runtime_control_and_signal_capture" if writes else "runtime_read_only_signal_capture",
              "runtime_required":True,"event":{"type":"none"},
              "runtime_controls":{"read_only_signal_capture":True,"runtime_parameter_writes":writes,
                  "hardware_io_changes":[],"rack_configuration_changes":[],"deployment_actions":[]},
              "runtime_capture":{"warmup_seconds":spec["capture_after_seconds"],"minimum_samples_per_channel":spec["minimum_samples_per_channel"]},
              "measurement_channels":copy.deepcopy(channels),
              "output_requirements":{"raw_numeric_data_required":True,"screenshot_only_pass_fail_forbidden":True},
              "experiment_dsl_sha256":sha256_json(spec),"event_timing_basis":"controller_wall_clock_after_run_confirmation",
              "event_semantics":"caller-declared mapping; fault/trip labels do not imply verified electrical effects"}
    validate_runtime_test_spec(result)
    return result


def expand(spec, sweep):
    axes = sweep["axes"]
    if len({a["name"] for a in axes}) != len(axes): raise ValueError("Duplicate sweep axis name")
    if len({sha256_json(a["target"]) for a in axes}) != len(axes): raise ValueError("Duplicate sweep target")
    lengths = [len(a["values"]) for a in axes]
    count = 1
    if sweep["mode"] == "paired" and axes:
        if len(set(lengths)) != 1: raise ValueError("Paired axes must have equal lengths")
        count = lengths[0]
    else:
        for length in lengths: count *= length
    if count > 64: raise ValueError("Suite exceeds 64 sequential runs")
    combinations = [()] if not axes else zip(*(a["values"] for a in axes)) if sweep["mode"] == "paired" else itertools.product(*(a["values"] for a in axes))
    runs = []
    for combination in combinations:
        candidate, patches, values = copy.deepcopy(spec), [], {}
        for axis,value in zip(axes,combination):
            target = axis["target"]
            values[axis["name"]] = value
            if target["kind"] == "draft_parameter":
                if not isinstance(value,str): raise ValueError("Draft sweep values must be explicit strings")
                patches.append({**{k:v for k,v in target.items() if k != "kind"},"op":"set_parameter","new_value":value})
            else:
                if type(value) not in (int,float): raise ValueError("Runtime sweep values must be numeric")
                field, identity = ("events","event_id") if target["kind"] == "event_value" else ("initial_conditions","target_id")
                rows = [r for r in candidate[field] if r[identity] == target["id"]]
                if len(rows) != 1: raise ValueError("Sweep target is missing or ambiguous")
                rows[0]["value"] = value
        test_spec = compile_spec(candidate)
        runs.append({"axis_values":values,"draft_operations":patches,"specification":candidate,"test_spec":test_spec})
    return runs

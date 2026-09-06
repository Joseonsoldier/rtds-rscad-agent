"""Bounded event declarations and offline sampled timing evidence; no live scheduler."""
from __future__ import annotations

import copy
import math

from .state_machine import sha256_json


ACTION_KEYS = {
    "action_id", "event_id", "transition", "target_id", "kind",
    "requested_simulator_time", "from_value", "to_value", "units",
}
OBSERVATION_KEYS = {
    "action_id", "channel_id", "window_start_seconds", "window_end_seconds",
    "value_tolerance", "max_timing_error_seconds", "max_sample_gap_seconds",
}
CONTRACT_KEYS = {"schema_version", "mode", "clock_channel_id", "source_evidence", "actions"}
MAX_ACTIONS = 128
MAX_SAMPLES = 100000
EVENT_KINDS = {"fault", "clear_fault", "trip", "reclose", "reference_change", "operator_control"}


def _text(value, label, maximum=None):
    if not isinstance(value, str) or not value.strip() or (maximum is not None and len(value) > maximum):
        raise ValueError(f"{label} must be a nonempty string" + (f" of at most {maximum} characters" if maximum else ""))
    return value


def _number(value, label, lower=None, upper=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError):
        valid = False
    if not valid or (lower is not None and value < lower) or (upper is not None and value > upper):
        raise ValueError(f"{label} must be a finite number within its declared bounds")
    return value


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} fields must exactly match the timing contract")


def _channels(channels):
    if isinstance(channels, dict):
        rows = list(channels.values())
        if any(not isinstance(row, dict) or row.get("channel_id") != key for key, row in channels.items()):
            raise ValueError("Channel mapping keys must match exact channel IDs")
    elif isinstance(channels, list):
        rows = channels
    else:
        raise ValueError("Channels must be a list or an exact ID mapping")
    if not 1 <= len(rows) <= 64:
        raise ValueError("Timing requires 1–64 declared channels")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Channel declaration must be an object")
        identity = _text(row.get("channel_id"), "channel_id", 160)
        if identity in result:
            raise ValueError("Duplicate timing channel ID")
        result[identity] = row
    return result


def build_timing(timing, actions, channels):
    """Canonicalize a declaration without granting any execution authority."""
    if not isinstance(timing, dict) or not isinstance(timing.get("mode"), str) or timing["mode"] not in {"wall_clock_debug", "model_native"}:
        raise ValueError("Unsupported event timing mode")
    native = timing["mode"] == "model_native"
    _exact(timing, {"mode", "clock_channel_id", "source_evidence", "observations"} if native else {"mode"}, "timing")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS or (native and not actions):
        raise ValueError("Timing requires at most 128 actions and model-native requires at least one")
    declared = _channels(channels)
    identifiers, transitions, instants = set(), set(), set()
    target_states = {}
    previous = -1
    canonical = []
    for action in actions:
        _exact(action, ACTION_KEYS, "action")
        for key in ("action_id", "event_id", "target_id"):
            _text(action[key], key, 160)
        _text(action["units"], "units", 500)
        if not isinstance(action["kind"], str) or action["kind"] not in EVENT_KINDS:
            raise ValueError("Unsupported timing event kind")
        if not isinstance(action["transition"], str) or action["transition"] not in {"apply", "clear"}:
            raise ValueError("Timing transition must be apply or clear")
        requested = _number(action["requested_simulator_time"], "requested_simulator_time", 0, 30)
        for key in ("from_value", "to_value"):
            _number(action[key], key)
        if requested < previous:
            raise ValueError("Timing actions must be ordered by requested simulator time")
        if action["action_id"] in identifiers or (action["event_id"], action["transition"]) in transitions:
            raise ValueError("Duplicate event action or transition ID")
        instant = (action["target_id"], requested)
        if instant in instants:
            raise ValueError("Simultaneous actions on one timing target are ambiguous")
        target = action["target_id"]
        if native and target in target_states and target_states[target] != (action["from_value"], action["units"]):
            raise ValueError("Model-native actions on one target must form an exact declared value and units chain")
        target_states[target] = (action["to_value"], action["units"])
        identifiers.add(action["action_id"])
        transitions.add((action["event_id"], action["transition"]))
        instants.add(instant)
        previous = requested
        canonical.append({**copy.deepcopy(action), "observation": None})
    clock_id, source = None, None
    if native:
        clock_id = _text(timing["clock_channel_id"], "clock_channel_id", 160)
        clock = declared.get(clock_id)
        if clock is None or clock.get("units") != "s":
            raise ValueError("Model-native timing requires a declared clock channel with units s")
        _text(clock.get("sign_convention"), "clock sign_convention")
        source = timing["source_evidence"]
        _exact(source, {"source_sha256", "locator"}, "source_evidence")
        digest = source["source_sha256"]
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Timing source_sha256 must be 64 lowercase hexadecimal characters")
        _text(source["locator"], "source locator", 1000)
        observations = timing["observations"]
        if not isinstance(observations, list) or len(observations) != len(actions):
            raise ValueError("Each model-native action requires exactly one observation")
        observed = {}
        for observation in observations:
            _exact(observation, OBSERVATION_KEYS, "observation")
            identity = _text(observation["action_id"], "observation action_id", 160)
            if identity not in identifiers or identity in observed:
                raise ValueError("Observation action ID is absent or duplicated")
            observed[identity] = observation
        for action in canonical:
            observation = observed[action["action_id"]]
            state_id = _text(observation["channel_id"], "observation channel_id", 160)
            state = declared.get(state_id)
            if state_id == clock_id or state is None or state.get("units") != action["units"]:
                raise ValueError("Observed state must be a separate declared channel with exact action units")
            _text(state.get("sign_convention"), "state sign_convention")
            start = _number(observation["window_start_seconds"], "window_start_seconds", 0, 30)
            end = _number(observation["window_end_seconds"], "window_end_seconds", 0, 30)
            if not start < end or not start <= action["requested_simulator_time"] <= end:
                raise ValueError("Observation window must enclose requested time and have start < end")
            tolerance = _number(observation["value_tolerance"], "value_tolerance", 0)
            _number(observation["max_timing_error_seconds"], "max_timing_error_seconds", 0)
            gap = _number(observation["max_sample_gap_seconds"], "max_sample_gap_seconds", 0)
            if gap == 0:
                raise ValueError("max_sample_gap_seconds must be positive")
            if abs(action["to_value"] - action["from_value"]) <= 2 * tolerance:
                raise ValueError("Transition states must have distinct, nonoverlapping tolerance bands")
            action["observation"] = copy.deepcopy(observation)
    return {"schema_version": "1.0", "mode": timing["mode"], "clock_channel_id": clock_id,
            "source_evidence": copy.deepcopy(source), "actions": canonical}


def validate_timing_contract(contract, channels):
    """Rebuild the strict contract; supplied qualification fields are never accepted."""
    _exact(contract, CONTRACT_KEYS, "event_timing")
    if contract["schema_version"] != "1.0" or not isinstance(contract["actions"], list) or len(contract["actions"]) > MAX_ACTIONS:
        raise ValueError("Unsupported timing schema or action count")
    actions, observations = [], []
    for action in contract["actions"]:
        _exact(action, ACTION_KEYS | {"observation"}, "canonical action")
        actions.append({key: copy.deepcopy(action[key]) for key in ACTION_KEYS})
        observations.append(copy.deepcopy(action["observation"]))
    raw = {"mode": contract["mode"]}
    if contract["mode"] == "model_native":
        raw.update(clock_channel_id=contract["clock_channel_id"], source_evidence=contract["source_evidence"], observations=observations)
    rebuilt = build_timing(raw, actions, channels)
    if rebuilt != contract:
        raise ValueError("Contradictory canonical timing fields")
    return rebuilt


def require_executable_timing(test_spec):
    """Reject native scheduling before any backend; no caller can qualify it."""
    if not isinstance(test_spec, dict):
        raise ValueError("Test specification must be an object")
    if "event_timing" not in test_spec:
        return
    contract = test_spec["event_timing"]
    if isinstance(contract, dict) and contract.get("mode") == "model_native":
        raise ValueError("Unavailable qualified model-native scheduler; execution refused before any backend")
    validate_timing_contract(contract, test_spec.get("measurement_channels"))


def _sample_quality(channel):
    if channel is None:
        return ["channel_not_found"]
    times, values = channel.get("times"), channel.get("values")
    if not isinstance(times, list) or not isinstance(values, list) or not 1 <= len(times) <= MAX_SAMPLES or len(times) != len(values):
        return ["missing_mismatched_or_oversized_sample_arrays"]
    try:
        for value in times + values:
            _number(value, "sample")
    except ValueError:
        return ["non_finite_or_non_numeric_samples"]
    if any(left >= right for left, right in zip(times, times[1:])):
        return ["non_monotonic_or_duplicate_time"]
    if not isinstance(channel.get("units"), str) or not channel["units"].strip() or not isinstance(channel.get("sign_convention"), str) or not channel["sign_convention"].strip():
        return ["missing_channel_units_or_sign_convention"]
    if channel["units"] == "pu":
        try:
            base = _number(channel.get("pu_base"), "pu_base", 0)
            if base == 0:
                raise ValueError("Zero base")
        except ValueError:
            return ["missing_or_invalid_pu_base"]
    return []


def _event_evidence(action, contract):
    native = contract["mode"] == "model_native"
    return {**{key: action[key] for key in ("action_id", "event_id", "transition", "target_id", "kind", "requested_simulator_time")},
            "observed_simulator_time": None, "measured_timing_error_seconds": None,
            "absolute_timing_error_seconds": None, "transition_sample_indices": None,
            "transition_time_bracket_seconds": None, "timing_error_bounds_seconds": None,
            "timing_mechanism": "supplied_model_native_declaration" if native else "wall_clock_debug",
            "time_source": {"kind": "clock_channel_values", "channel_id": contract["clock_channel_id"]} if native else None,
            "qualification_state": "source_declared_clock_not_independently_verified" if native else "debug_nonauthoritative",
            "deterministic_verified": False, "integration_qualified": False,
            "sample_agreement_status": "inconclusive", "reasons": [],
            "observation": copy.deepcopy(action["observation"])}


def evaluate_timing(contract, data, channels):
    """Compare supplied state transitions against declared times using clock VALUES.

    Brackets conservatively bound sampled transition time. Numerical agreement
    never independently verifies the clock, scheduler, or electrical effects.
    """
    declared = _channels(channels)
    # Revalidate declaration structure independently of missing/invalid samples.
    # These temporary metadata placeholders are never returned as evidence.
    _exact(contract, CONTRACT_KEYS, "event_timing")
    validation_channels = {}
    if contract["mode"] == "model_native":
        clock_id = _text(contract["clock_channel_id"], "clock_channel_id", 160)
        validation_channels[clock_id] = {"channel_id": clock_id, "units": "s", "sign_convention": "validation-only"}
        if not isinstance(contract["actions"], list) or len(contract["actions"]) > MAX_ACTIONS:
            raise ValueError("Unsupported timing action count")
        for action in contract["actions"]:
            _exact(action, ACTION_KEYS | {"observation"}, "canonical action")
            _exact(action["observation"], OBSERVATION_KEYS, "observation")
            state_id = _text(action["observation"]["channel_id"], "observation channel_id", 160)
            units = _text(action["units"], "action units", 500)
            if state_id in validation_channels and validation_channels[state_id]["units"] != units:
                raise ValueError("One timing channel cannot have contradictory units")
            validation_channels[state_id] = {"channel_id": state_id, "units": units, "sign_convention": "validation-only"}
    contract = validate_timing_contract(contract, validation_channels or declared)
    if not isinstance(data, dict):
        raise ValueError("Canonical sample data must be an object")
    report = {"schema_version": "1.0", "mode": contract["mode"], "status": "not_evaluated",
              "contract_sha256": sha256_json(contract),
              **{key: data.get(key) for key in ("run_id", "attempt_id", "input_project_sha256")},
              "source_evidence": copy.deepcopy(contract["source_evidence"]),
              "integration_qualified": False, "deterministic_verified": False, "events": [],
              "limitations": ["Agreement concerns supplied discrete samples only.",
                              "Clock origin and model-native scheduling are not independently verified.",
                              "Event kind labels do not establish electrical effects."]}
    clock = declared.get(contract["clock_channel_id"])
    clock_errors = []
    if contract["mode"] == "model_native":
        if data.get("time_unit") != "s" or data.get("time_basis") != "simulator_time":
            clock_errors.append("simulator_time_metadata_required")
        clock_errors.extend("clock_" + reason for reason in _sample_quality(clock))
        if clock is not None and clock.get("units") != "s":
            clock_errors.append("clock_units_must_be_seconds")
        if not clock_errors:
            if any(value < 0 for value in clock["values"]) or any(a >= b for a, b in zip(clock["values"], clock["values"][1:])):
                clock_errors.append("clock_values_must_be_nonnegative_and_strictly_increasing")
    used_transitions, last_target_times, last_channel_times = set(), {}, {}
    for action in contract["actions"]:
        result = _event_evidence(action, contract)
        report["events"].append(result)
        if contract["mode"] == "wall_clock_debug":
            result["reasons"] = ["controller_sleep_and_write_timing_is_debug_nonauthoritative", "observed_simulator_time_unavailable"]
            continue
        observation = action["observation"]
        state = declared.get(observation["channel_id"])
        result["reasons"] = [*clock_errors, *("state_" + reason for reason in _sample_quality(state))]
        if state is not None and state.get("units") != action["units"]:
            result["reasons"].append("state_units_mismatch")
        if result["reasons"]:
            continue
        if state["times"] != clock["times"]:
            result["reasons"] = ["clock_state_sample_timestamps_do_not_match_exactly"]
            continue
        times, values = clock["values"], state["values"]
        start, end = observation["window_start_seconds"], observation["window_end_seconds"]
        if times[0] > start or times[-1] < end:
            result["reasons"] = ["insufficient_clock_capture_interval"]
            continue
        if any(b - a > observation["max_sample_gap_seconds"] for a, b in zip(times, times[1:]) if b > start and a < end):
            result["reasons"] = ["clock_sample_gap_exceeds_specification"]
            continue
        eligible = [i for i, value in enumerate(times) if start <= value <= end]
        if len(eligible) < 2:
            result["reasons"] = ["empty_or_insufficient_interval_samples"]
            continue
        tolerance = observation["value_tolerance"]
        before = lambda value: abs(value - action["from_value"]) <= tolerance
        after = lambda value: abs(value - action["to_value"]) <= tolerance
        candidates = [i for i in eligible if i > 0 and times[i - 1] >= start and before(values[i - 1]) and after(values[i])]
        if len(candidates) != 1:
            no_predecessor = after(values[eligible[0]])
            result["reasons"] = ["multiple_ambiguous_transitions" if len(candidates) > 1 else
                                 "transition_without_predecessor_in_window" if no_predecessor else "transition_not_observed"]
            continue
        index = candidates[0]
        channel_id, target_id = observation["channel_id"], action["target_id"]
        transition_key = (channel_id, index - 1, index)
        if transition_key in used_transitions:
            result["reasons"] = ["sample_transition_already_assigned_to_another_action"]
            continue
        if (times[index] <= last_target_times.get(target_id, -1)
                or times[index] <= last_channel_times.get(channel_id, -1)):
            result["reasons"] = ["observed_transition_out_of_declared_action_order"]
            continue
        # Assign the sole candidate even if its timing bracket fails acceptance.
        # Never filter earlier candidates to silently select a convenient edge.
        used_transitions.add(transition_key)
        last_target_times[target_id] = times[index]
        last_channel_times[channel_id] = times[index]
        requested = action["requested_simulator_time"]
        lower, upper = times[index - 1] - requested, times[index] - requested
        limit = observation["max_timing_error_seconds"]
        status = "passed" if -limit <= lower <= upper <= limit else "failed" if lower > limit or upper < -limit else "inconclusive"
        result.update(observed_simulator_time=times[index], measured_timing_error_seconds=upper,
                      absolute_timing_error_seconds=abs(upper), transition_sample_indices=[index - 1, index],
                      transition_time_bracket_seconds=[times[index - 1], times[index]],
                      timing_error_bounds_seconds=[lower, upper], sample_agreement_status=status,
                      reasons=[] if status == "passed" else ["timing_error_bracket_outside_tolerance"] if status == "failed" else ["timing_error_bracket_overlaps_tolerance_boundary"])
    statuses = {event["sample_agreement_status"] for event in report["events"]}
    report["status"] = "failed" if "failed" in statuses else "inconclusive" if "inconclusive" in statuses else "passed" if "passed" in statuses else "not_evaluated"
    return report

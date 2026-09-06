"""Synthetic contract and clock-value timing evaluation; never imports a vendor SDK."""
import test_environment
import copy
import unittest

from rtds_agent.core.event_timing import (
    build_timing, evaluate_timing, require_executable_timing, validate_timing_contract,
)
from rtds_agent.core.state_machine import sha256_json


def action():
    return {"action_id": "event.fault", "event_id": "fault", "transition": "apply",
            "target_id": "breaker", "kind": "fault", "requested_simulator_time": 1,
            "from_value": 0, "to_value": 1, "units": "position"}


def metadata():
    return [{"channel_id": "clock", "units": "s", "sign_convention": "increasing"},
            {"channel_id": "state", "units": "position", "sign_convention": "closed=1"}]


def timing():
    return {"mode": "model_native", "clock_channel_id": "clock",
            "source_evidence": {"source_sha256": "a" * 64, "locator": "synthetic clock declaration"},
            "observations": [{"action_id": "event.fault", "channel_id": "state",
                              "window_start_seconds": 0, "window_end_seconds": 2,
                              "value_tolerance": 0, "max_timing_error_seconds": 0.25,
                              "max_sample_gap_seconds": 0.25}]}


def samples():
    channels = metadata()
    # Plot timestamps deliberately disagree with clock VALUES and requested time.
    for channel in channels:
        channel["times"] = [100 + index for index in range(9)]
    channels[0]["values"] = [index / 4 for index in range(9)]
    channels[1]["values"] = [0, 0, 0, 0, 1, 1, 1, 1, 1]
    data = {"schema_version": "1.0", "time_unit": "s", "time_basis": "simulator_time",
            "run_id": "synthetic-run", "attempt_id": "synthetic-attempt",
            "input_project_sha256": "b" * 64, "channels": channels}
    return data, {row["channel_id"]: row for row in channels}


class TimingContractTests(unittest.TestCase):
    def test_canonical_rebuild_is_deterministic_and_nonmutating(self):
        raw, actions, channels = timing(), [action()], metadata()
        before = copy.deepcopy((raw, actions, channels))
        contract = build_timing(raw, actions, channels)
        self.assertEqual(contract, validate_timing_contract(contract, channels))
        self.assertEqual((raw, actions, channels), before)
        contract["actions"][0]["observation"]["value_tolerance"] = 0.1
        self.assertEqual(raw["observations"][0]["value_tolerance"], 0)

    def test_debug_preserves_actions_and_allows_no_op(self):
        first = action()
        first["to_value"] = 0
        contract = build_timing({"mode": "wall_clock_debug"}, [first], metadata())
        self.assertIsNone(contract["clock_channel_id"])
        self.assertIsNone(contract["source_evidence"])
        self.assertIsNone(contract["actions"][0]["observation"])
        require_executable_timing({"event_timing": contract, "measurement_channels": metadata()})
        require_executable_timing({})

    def test_no_caller_native_qualification_or_debug_extra_fields(self):
        for extra in ({"integration_qualified": True}, {"observations": []}, {"clock_channel_id": "clock"}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                build_timing({"mode": "wall_clock_debug", **extra}, [], metadata())
        native = timing()
        native["integration_qualified"] = True
        with self.assertRaises(ValueError):
            build_timing(native, [action()], metadata())
        with self.assertRaisesRegex(ValueError, "qualified model-native scheduler.*before any backend"):
            require_executable_timing({"event_timing": {"mode": "model_native", "qualified": True}})
        for mode in ([], {}, None, True, "unknown"):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                build_timing({"mode": mode}, [action()], metadata())

    def test_native_requires_actions_and_one_observation_each(self):
        for observations in ([], [timing()["observations"][0]] * 2,
                             [{**timing()["observations"][0], "action_id": "absent"}]):
            raw = timing()
            raw["observations"] = observations
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                build_timing(raw, [action()], metadata())
        with self.assertRaises(ValueError):
            build_timing(timing(), [], metadata())

    def test_actions_reject_duplicates_order_instant_unknown_fields_and_bounds(self):
        first = action()
        next_action = {**first, "action_id": "event.other", "event_id": "other", "target_id": "other", "requested_simulator_time": 2}
        invalid = [[first, first], [next_action, first],
                   [first, {**next_action, "target_id": first["target_id"], "requested_simulator_time": 1}],
                   [{**first, "extra": 1}], [{**first, "transition": "reset"}], [{**first, "transition": []}]]
        invalid += [[{**first, "requested_simulator_time": value}] for value in (-1, 31, True, float("nan"), float("inf"), 10**1000)]
        invalid += [[{**first, "from_value": value}] for value in (False, "0", float("nan"))]
        invalid.append([first] * 129)
        for rows in invalid:
            with self.subTest(rows=str(rows)[:120]), self.assertRaises(ValueError):
                build_timing({"mode": "wall_clock_debug"}, rows, metadata())

    def test_onset_and_clear_keep_distinct_action_identity(self):
        clear = {**action(), "action_id": "clear.fault", "transition": "clear", "requested_simulator_time": 2,
                 "from_value": 1, "to_value": 0}
        raw = timing()
        raw["observations"].append({**raw["observations"][0], "action_id": "clear.fault"})
        contract = build_timing(raw, [action(), clear], metadata())
        self.assertEqual([row["action_id"] for row in contract["actions"]], ["event.fault", "clear.fault"])
        self.assertEqual([row["event_id"] for row in contract["actions"]], ["fault", "fault"])

    def test_canonical_text_bounds_and_event_kind_match_public_contract(self):
        for key in ("action_id", "event_id", "target_id"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_timing({"mode": "wall_clock_debug"}, [{**action(), key: "x" * 161}], metadata())
        for key, value in (("units", "x" * 501), ("kind", "arbitrary_script"), ("kind", [])):
            with self.subTest(key=key), self.assertRaises(ValueError):
                build_timing({"mode": "wall_clock_debug"}, [{**action(), key: value}], metadata())
        channels = metadata()
        channels[0]["channel_id"] = "x" * 161
        with self.assertRaises(ValueError):
            build_timing({"mode": "wall_clock_debug"}, [action()], channels)

    def test_clock_and_state_identity_units_sign_are_required(self):
        variants = []
        for index, field, value in ((0, "units", "ms"), (0, "sign_convention", ""),
                                    (1, "units", "V"), (1, "sign_convention", None)):
            channels = metadata()
            channels[index][field] = value
            variants.append(channels)
        variants += [metadata()[:1], metadata()[1:], metadata() + [metadata()[0]]]
        for channels in variants:
            with self.subTest(channels=channels), self.assertRaises(ValueError):
                build_timing(timing(), [action()], channels)
        raw = timing()
        raw["observations"][0]["channel_id"] = "clock"
        with self.assertRaises(ValueError):
            build_timing(raw, [action()], metadata())

    def test_windows_tolerances_source_and_state_overlap_fail_closed(self):
        changes = [("window_start_seconds", -1), ("window_start_seconds", 1.5),
                   ("window_end_seconds", 0), ("window_end_seconds", 31),
                   ("value_tolerance", 0.5), ("value_tolerance", -1),
                   ("max_timing_error_seconds", True), ("max_timing_error_seconds", float("inf")),
                   ("max_sample_gap_seconds", 0)]
        for key, value in changes:
            raw = timing()
            raw["observations"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                build_timing(raw, [action()], metadata())
        for source in ({"source_sha256": "z" * 64, "locator": "x"},
                       {"source_sha256": "a" * 64, "locator": " "},
                       {"source_sha256": "a" * 64, "locator": "x" * 1001}):
            raw = timing()
            raw["source_evidence"] = source
            with self.assertRaises(ValueError):
                build_timing(raw, [action()], metadata())
        with self.assertRaises(ValueError):
            build_timing(timing(), [{**action(), "to_value": 0}], metadata())

    def test_canonical_extra_or_contradictory_fields_rejected(self):
        canonical = build_timing({"mode": "wall_clock_debug"}, [action()], metadata())
        variants = [{**canonical, "deterministic_verified": True}, {**canonical, "clock_channel_id": "clock"},
                    {**canonical, "source_evidence": {}}, {**canonical, "schema_version": "2.0"}]
        altered = copy.deepcopy(canonical)
        altered["actions"][0]["observation"] = timing()["observations"][0]
        variants.append(altered)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_timing_contract(value, metadata())

    def test_native_target_chain_rejects_incoherent_from_state(self):
        clear = {**action(), "action_id": "clear.fault", "transition": "clear", "requested_simulator_time": 1.5,
                 "from_value": 2, "to_value": 0}
        raw = timing()
        raw["observations"].append({**raw["observations"][0], "action_id": "clear.fault"})
        with self.assertRaisesRegex(ValueError, "exact declared value and units chain"):
            build_timing(raw, [action(), clear], metadata())
        # The legacy declaration contract keeps its existing debug behavior.
        build_timing({"mode": "wall_clock_debug"}, [action(), clear], metadata())


class TimingEvaluationTests(unittest.TestCase):
    def evaluate(self, data=None, channels=None, raw=None, actions=None):
        if data is None:
            data, channels = samples()
        contract = build_timing(raw or timing(), actions or [action()], metadata())
        return evaluate_timing(contract, data, channels)

    def test_clock_values_not_plot_axis_determine_time_and_provenance(self):
        data, channels = samples()
        before = copy.deepcopy((data, channels))
        contract = build_timing(timing(), [action()], metadata())
        result = evaluate_timing(contract, data, channels)
        event = result["events"][0]
        self.assertEqual(result["status"], "passed")
        self.assertEqual(event["observed_simulator_time"], 1)
        self.assertEqual(event["transition_sample_indices"], [3, 4])
        self.assertEqual(event["transition_time_bracket_seconds"], [0.75, 1])
        self.assertEqual(event["timing_error_bounds_seconds"], [-0.25, 0])
        self.assertEqual(event["measured_timing_error_seconds"], 0)
        self.assertEqual(result["contract_sha256"], sha256_json(contract))
        for key in ("run_id", "attempt_id", "input_project_sha256"):
            self.assertEqual(result[key], data[key])
        self.assertFalse(result["deterministic_verified"])
        self.assertFalse(event["deterministic_verified"])
        self.assertFalse(result["integration_qualified"])
        self.assertIn("not_independently_verified", event["qualification_state"])
        self.assertEqual((data, channels), before)
        self.assertEqual(evaluate_timing(contract, data, channels), result)

    def test_early_late_and_straddling_brackets(self):
        for edge, expected, error in ((1, "failed", -0.75), (7, "failed", 0.75), (6, "inconclusive", 0.5)):
            data, channels = samples()
            channels["state"]["values"] = [0] * edge + [1] * (9 - edge)
            result = self.evaluate(data, channels)
            self.assertEqual(result["status"], expected)
            self.assertEqual(result["events"][0]["measured_timing_error_seconds"], error)
            self.assertEqual(result["events"][0]["absolute_timing_error_seconds"], abs(error))

    def test_exact_sample_does_not_prove_zero_tolerance_timing(self):
        raw = timing()
        raw["observations"][0]["max_timing_error_seconds"] = 0
        result = self.evaluate(raw=raw)
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["events"][0]["measured_timing_error_seconds"], 0)

    def test_onset_and_clear_are_evaluated_independently(self):
        data, channels = samples()
        channels["state"]["values"] = [0, 0, 0, 0, 1, 1, 0, 0, 0]
        clear = {**action(), "action_id": "clear.fault", "transition": "clear", "requested_simulator_time": 1.5,
                 "from_value": 1, "to_value": 0}
        raw = timing()
        raw["observations"].append({**raw["observations"][0], "action_id": "clear.fault"})
        result = self.evaluate(data, channels, raw, [action(), clear])
        self.assertEqual(result["status"], "passed")
        self.assertEqual([row["observed_simulator_time"] for row in result["events"]], [1, 1.5])

    def test_later_action_cannot_reuse_earlier_rising_transition(self):
        data, channels = samples()
        channels["state"]["values"] = [0, 0, 0, 0, 1, 1, 0, 0, 0]
        actions = [action(),
                   {**action(), "action_id": "clear.fault", "transition": "clear", "requested_simulator_time": 1.1,
                    "from_value": 1, "to_value": 0},
                   {**action(), "action_id": "event.second", "event_id": "second", "requested_simulator_time": 1.2}]
        raw = timing()
        raw["observations"] = [{**raw["observations"][0], "action_id": row["action_id"], "max_timing_error_seconds": 0.6}
                               for row in actions]
        result = self.evaluate(data, channels, raw, actions)
        self.assertEqual(result["status"], "inconclusive")
        events = result["events"]
        self.assertEqual([event["observed_simulator_time"] for event in events], [1, 1.5, None])
        self.assertIn("sample_transition_already_assigned_to_another_action", events[2]["reasons"])
        for key in ("measured_timing_error_seconds", "absolute_timing_error_seconds", "transition_sample_indices",
                    "transition_time_bracket_seconds", "timing_error_bounds_seconds"):
            self.assertIsNone(events[2][key])
        brackets = [tuple(event["transition_sample_indices"]) for event in events if event["transition_sample_indices"] is not None]
        self.assertEqual(len(brackets), len(set(brackets)))

    def test_valid_three_action_sequence_uses_three_distinct_ordered_edges(self):
        data, channels = samples()
        channels["state"]["values"] = [0, 0, 0, 0, 1, 1, 0, 1, 1]
        actions = [action(),
                   {**action(), "action_id": "clear.fault", "transition": "clear", "requested_simulator_time": 1.5,
                    "from_value": 1, "to_value": 0},
                   {**action(), "action_id": "event.second", "event_id": "second", "requested_simulator_time": 1.75}]
        raw = timing()
        raw["observations"] = [{**raw["observations"][0], "action_id": row["action_id"],
                                "window_start_seconds": start, "window_end_seconds": end}
                               for row, (start, end) in zip(actions, [(0, 1.25), (1.25, 1.75), (1.5, 2)])]
        result = self.evaluate(data, channels, raw, actions)
        self.assertEqual(result["status"], "passed")
        self.assertEqual([event["observed_simulator_time"] for event in result["events"]], [1, 1.5, 1.75])
        self.assertEqual([event["transition_sample_indices"] for event in result["events"]], [[3, 4], [5, 6], [6, 7]])
        self.assertFalse(result["deterministic_verified"])

    def test_same_channel_transition_cannot_prove_different_targets(self):
        actions = [action(), {**action(), "action_id": "event.other", "event_id": "other", "target_id": "other",
                             "requested_simulator_time": 1.25}]
        raw = timing()
        raw["observations"] = [{**raw["observations"][0], "action_id": row["action_id"], "max_timing_error_seconds": 0.6}
                               for row in actions]
        result = self.evaluate(raw=raw, actions=actions)
        self.assertEqual(result["status"], "inconclusive")
        self.assertIn("sample_transition_already_assigned_to_another_action", result["events"][1]["reasons"])
        self.assertIsNone(result["events"][1]["observed_simulator_time"])

    def test_target_observed_order_is_checked_across_different_channels(self):
        data, channels = samples()
        channels["state"]["values"] = [0, 0, 0, 0, 0, 0, 1, 1, 1]
        other = {**copy.deepcopy(channels["state"]), "channel_id": "other_state", "values": [1, 1, 1, 1, 0, 0, 0, 0, 0]}
        channels["other_state"] = other
        data["channels"].append(other)
        actions = [action(), {**action(), "action_id": "clear.fault", "transition": "clear",
                             "requested_simulator_time": 1.25, "from_value": 1, "to_value": 0}]
        raw = timing()
        raw["observations"][0]["max_timing_error_seconds"] = 0.6
        raw["observations"].append({**raw["observations"][0], "action_id": "clear.fault", "channel_id": "other_state"})
        contract = build_timing(raw, actions, list(channels.values()))
        result = evaluate_timing(contract, data, channels)
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["events"][0]["observed_simulator_time"], 1.5)
        self.assertIn("observed_transition_out_of_declared_action_order", result["events"][1]["reasons"])
        self.assertIsNone(result["events"][1]["observed_simulator_time"])
        self.assertIsNone(result["events"][1]["transition_sample_indices"])

    def test_multiple_missing_and_absent_predecessor_are_inconclusive(self):
        for values, reason in (([0] * 9, "transition_not_observed"),
                               ([1] * 9, "transition_without_predecessor_in_window"),
                               ([0, 1, 0, 0, 1, 1, 1, 1, 1], "multiple_ambiguous_transitions")):
            data, channels = samples()
            channels["state"]["values"] = values
            result = self.evaluate(data, channels)
            event = result["events"][0]
            self.assertEqual(result["status"], "inconclusive")
            self.assertIn(reason, event["reasons"])
            self.assertIsNone(event["observed_simulator_time"])
        raw = timing()
        raw["observations"][0]["window_start_seconds"] = 1
        self.assertIn("transition_without_predecessor_in_window", self.evaluate(raw=raw)["events"][0]["reasons"])

    def test_clock_time_basis_alignment_epoch_and_monotonicity(self):
        for change, reason in (
            (lambda d, c: d.update(time_basis="wall_clock"), "simulator_time_metadata_required"),
            (lambda d, c: d.update(time_unit="ms"), "simulator_time_metadata_required"),
            (lambda d, c: c["clock"]["times"].__setitem__(0, 99), "clock_state_sample_timestamps_do_not_match_exactly"),
            (lambda d, c: c["clock"]["values"].__setitem__(0, -0.25), "clock_values_must_be_nonnegative_and_strictly_increasing"),
            (lambda d, c: c["clock"]["values"].__setitem__(4, 0.75), "clock_values_must_be_nonnegative_and_strictly_increasing"),
            (lambda d, c: c["clock"].update(values=[v + 1 for v in c["clock"]["values"]]), "insufficient_clock_capture_interval"),
        ):
            data, channels = samples()
            change(data, channels)
            result = self.evaluate(data, channels)
            self.assertEqual(result["status"], "inconclusive")
            self.assertIn(reason, result["events"][0]["reasons"])

    def test_actual_clock_gap_is_used_and_nonuniform_samples_are_allowed(self):
        data, channels = samples()
        channels["clock"]["values"][3] = 0.875
        raw = timing()
        raw["observations"][0]["max_sample_gap_seconds"] = 0.5
        self.assertEqual(self.evaluate(data, channels, raw)["status"], "passed")
        self.assertIn("clock_sample_gap_exceeds_specification", self.evaluate(data, channels)["events"][0]["reasons"])

    def test_invalid_missing_oversized_samples_and_metadata_are_inconclusive(self):
        cases = [lambda d, c: c.pop("clock"), lambda d, c: c.pop("state"),
                 lambda d, c: c["state"].update(units="V"),
                 lambda d, c: c["clock"].update(units="ms"),
                 lambda d, c: c["state"].update(sign_convention=True),
                 lambda d, c: c["state"].update(values=[]),
                 lambda d, c: c["clock"]["values"].__setitem__(1, float("nan")),
                 lambda d, c: c["state"]["values"].__setitem__(1, True),
                 lambda d, c: c["state"]["times"].__setitem__(1, c["state"]["times"][0]),
                 lambda d, c: c["state"].update(times=list(range(100001)), values=[0] * 100001)]
        for change in cases:
            data, channels = samples()
            change(data, channels)
            with self.subTest(change=change):
                result = self.evaluate(data, channels)
                self.assertEqual(result["status"], "inconclusive")
                self.assertIsNone(result["events"][0]["observed_simulator_time"])

    def test_debug_has_no_observed_or_deterministic_timing(self):
        data, channels = samples()
        contract = build_timing({"mode": "wall_clock_debug"}, [action()], metadata())
        result = evaluate_timing(contract, data, channels)
        event = result["events"][0]
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(event["qualification_state"], "debug_nonauthoritative")
        for key in ("observed_simulator_time", "measured_timing_error_seconds", "absolute_timing_error_seconds",
                    "transition_sample_indices", "transition_time_bracket_seconds", "timing_error_bounds_seconds", "time_source"):
            self.assertIsNone(event[key])
        empty = build_timing({"mode": "wall_clock_debug"}, [], metadata())
        self.assertEqual(evaluate_timing(empty, data, channels)["status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()

"""Focused synthetic validation for event timing schema contracts."""
import json
from pathlib import Path
import unittest

import test_environment  # noqa: F401
import jsonschema


SCHEMAS = Path(__file__).resolve().parents[1] / "src" / "rtds_agent" / "schemas"


def _schema(name):
    return json.loads((SCHEMAS / name).read_text(encoding="utf-8"))


def _observation():
    return {
        "action_id": "action_1",
        "channel_id": "clock_1",
        "window_start_seconds": 0,
        "window_end_seconds": 1,
        "value_tolerance": 0.1,
        "max_timing_error_seconds": 0.01,
        "max_sample_gap_seconds": 0.001,
    }


def _native_raw():
    return {
        "mode": "model_native",
        "clock_channel_id": "clock_1",
        "source_evidence": {"source_sha256": "a" * 64, "locator": "fixture"},
        "observations": [_observation()],
    }


def _canonical_action(observation):
    return {
        "action_id": "action_1",
        "event_id": "event_1",
        "transition": "apply",
        "target_id": "target_1",
        "kind": "fault",
        "requested_simulator_time": 1,
        "from_value": 0,
        "to_value": 1,
        "units": "pu",
        "observation": observation,
    }


class EventTimingSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = _schema("experiment_suite.schema.json")
        cls.runtime = _schema("runtime_test_spec.schema.json")
        cls.raw = cls.suite["properties"]["specification"]["properties"]["event_timing"]
        cls.canonical = cls.runtime["properties"]["event_timing"]

    def test_full_schemas_are_valid_draft_2020_12(self):
        jsonschema.Draft202012Validator.check_schema(self.suite)
        jsonschema.Draft202012Validator.check_schema(self.runtime)

    def test_raw_debug_and_native_are_valid(self):
        validator = jsonschema.Draft202012Validator(self.raw)
        validator.validate({"mode": "wall_clock_debug"})
        validator.validate(_native_raw())

    def test_canonical_debug_and_native_are_valid(self):
        validator = jsonschema.Draft202012Validator(self.canonical)
        validator.validate({"schema_version": "1.0", "mode": "wall_clock_debug", "clock_channel_id": None, "source_evidence": None, "actions": [_canonical_action(None)]})
        validator.validate({"schema_version": "1.0", "mode": "model_native", "clock_channel_id": "clock_1", "source_evidence": {"source_sha256": "b" * 64, "locator": "fixture"}, "actions": [_canonical_action(_observation())]})

    def assert_invalid(self, schema, value):
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(schema).validate(value)

    def test_rejects_extra_qualified_flag(self):
        value = _native_raw()
        value["qualified"] = True
        self.assert_invalid(self.raw, value)
        canonical = {"schema_version": "1.0", "mode": "wall_clock_debug", "clock_channel_id": None, "source_evidence": None, "actions": []}
        canonical["qualified"] = True
        self.assert_invalid(self.canonical, canonical)

    def test_rejects_missing_native_clock_or_evidence(self):
        value = _native_raw()
        del value["clock_channel_id"]
        self.assert_invalid(self.raw, value)
        value = _native_raw()
        del value["source_evidence"]
        self.assert_invalid(self.raw, value)

    def test_rejects_invalid_observation_mode_and_bounds(self):
        value = {"schema_version": "1.0", "mode": "model_native", "clock_channel_id": "clock_1", "source_evidence": {"source_sha256": "a" * 64, "locator": "x"}, "actions": [_canonical_action(None)]}
        self.assert_invalid(self.canonical, value)
        value = {"schema_version": "1.0", "mode": "wall_clock_debug", "clock_channel_id": None, "source_evidence": None, "actions": [_canonical_action(_observation())]}
        self.assert_invalid(self.canonical, value)
        value = _native_raw()
        value["observations"] = [_observation()] * 129
        self.assert_invalid(self.raw, value)
        value = _native_raw()
        value["observations"][0]["window_start_seconds"] = -1
        self.assert_invalid(self.raw, value)
        value = _native_raw()
        value["observations"][0]["source_sha256"] = "bad"
        value["source_evidence"]["source_sha256"] = "bad"
        self.assert_invalid(self.raw, value)
        value = _native_raw()
        value["observations"][0]["max_sample_gap_seconds"] = 0
        self.assert_invalid(self.raw, value)


if __name__ == "__main__":
    unittest.main()

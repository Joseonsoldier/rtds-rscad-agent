import test_environment  # isolate config and credentials before application imports
import copy
import unittest
from pydantic import TypeAdapter
from rtds_agent.input_contracts import TestSpecification, TEST_SCHEMA, validate_test_spec, PatchBatchRequest
from test_runtime_backend import runtime_spec

class InputContractTests(unittest.TestCase):
    def test_runtime_schema_is_exposed_without_rewriting_plan(self):
        spec = runtime_spec()
        original = copy.deepcopy(spec)
        self.assertEqual(TypeAdapter(TestSpecification).validate_python(spec), original)
        self.assertEqual(spec, original)
        published = TypeAdapter(TestSpecification).json_schema()
        self.assertEqual(published, TEST_SCHEMA)
        self.assertIn("measurement_channels", published["oneOf"][0]["required"])

    def test_runtime_required_types_and_unknown_control_fields(self):
        for change in [lambda s: s["runtime_capture"].update(minimum_samples_per_channel=True),
                       lambda s: s["runtime_capture"].update(warmup_seconds=float("nan")),
                       lambda s: s["runtime_controls"].update(unsafe=True)]:
            spec = runtime_spec(); change(spec)
            with self.assertRaises(ValueError):
                validate_test_spec(spec)
            with self.assertRaises(ValueError):
                TypeAdapter(TestSpecification).validate_python(spec)

    def test_offline_aliases_have_same_validated_structure(self):
        for mode in ("offline_frequency_scan", "offline_analytical_frequency_scan"):
            spec = {"test_id":"synthetic", "runtime_required":False, "execution_mode":mode,
                    "execution_notes":{"case_run_forbidden":True},
                    "scan":{"system_frequency_hz":60, "start_frequency_hz":0, "end_frequency_hz":1,
                            "frequency_increment_hz":1, "domain":"DQ0", "selected_bus":"BUS1"}}
            self.assertEqual(validate_test_spec(spec), spec)
            spec["scan"]["start_frequency_hz"] = 2
            with self.assertRaises(ValueError): validate_test_spec(spec)

    def test_batch_fields_are_strict(self):
        schema = TypeAdapter(PatchBatchRequest).json_schema()
        self.assertFalse(schema["additionalProperties"])
        self.assertFalse(schema["properties"]["operations"]["items"]["additionalProperties"])
        self.assertIn("expected_old_value", schema["properties"]["operations"]["items"]["required"])

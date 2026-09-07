"""Authored production-boundary recovery regressions; no SDK/native operations."""
import test_environment
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import test_public_release as fixtures
from rtds_agent import execution
from rtds_agent.core.mock_backend import MockBackend
from rtds_agent.core.production_backend import ProductionRscadBackend
from rtds_agent.policy import configure_policy
from rtds_agent.settings import Settings


class AuthoredProduction(ProductionRscadBackend):
    """Exercise the production execution boundary without constructing drivers."""
    def __init__(self, mode="success", on_dispatch=None):
        self.mode, self.on_dispatch = mode, on_dispatch
        self.mock = MockBackend(available_racks=[2], selected_rack=2)
        self.queries = 0

    def refresh_racks(self, action):
        self.queries += 1
        if self.on_dispatch:
            self.on_dispatch()
        if self.mode == "query_error":
            raise RuntimeError("authored connection outcome unknown")
        return self.mock.refresh_racks(action)

    def compile(self, **arguments):
        if self.mode == "compile_error":
            raise RuntimeError("authored compile interruption")
        result = self.mock.compile(**arguments)
        result.update(case_closed=self.mode != "close_failure", disconnected=True,
                      cleanup_errors=[] if self.mode != "close_failure" else [{"operation": "close", "error": "unconfirmed"}])
        if self.mode == "no_native":
            result.update(succeeded=False, native_calls_made=False, connection_attempted=False, connected=False, compile_called=False)
        if self.mode == "capture_failed_clean":
            result["succeeded"] = False
        return result

    def run_runtime(self, **arguments):
        result = self.mock.run_runtime(**arguments)
        stopped = self.mode != "stop_failure"
        result.update(safe_completion=stopped, stopped=stopped,
            cleanup={"case_closed": True, "disconnected": True}, cleanup_errors=[],
            execution={"run_call_attempted": True, "stop_succeeded": stopped,
                       "run_state_after_stop": "stopped" if stopped else "running"},
            runtime_controls={"all_restored": True})
        if self.mode == "capture_failed_clean":
            result.update(safe_completion=False, raw_data_collected=False)
        return result


class ExecutionNativeRecoveryTests(unittest.TestCase):
    setUp = fixtures.PublicReleaseTests.setUp
    prepare = fixtures.PublicReleaseTests.prepare
    enable = fixtures.PublicReleaseTests.enable

    def scenario(self):
        path = self.prepare()
        self.enable()
        for name in ("verify_release", "inspect_installation"):
            substitute = patch.object(execution, name, return_value={"synthetic": True})
            substitute.start()
            self.addCleanup(substitute.stop)
        return path

    def marker(self):
        return self.data / "native_recovery_required.json"

    def attempt(self, path, action="compile"):
        return json.loads((Path(path).parent / (action + ".attempt.json")).read_text(encoding="utf-8"))

    def test_compile_close_failure_creates_barrier_and_blocks_fresh_workflow(self):
        path = self.scenario()
        with patch.object(execution, "_backend", return_value=AuthoredProduction("close_failure")):
            result = execution.compile_project(path)
        self.assertTrue(self.marker().is_file())
        self.assertTrue(result["attempt"]["native_recovery_required"])
        record = json.loads(self.marker().read_text(encoding="utf-8"))
        self.assertEqual(record["workflow_path"], path)
        self.assertFalse(record["automatic_retry"])
        self.assertFalse(record["automatic_clear"])
        original = self.marker().read_bytes()
        fresh = self.prepare()
        with patch.object(execution, "_backend") as factory, self.assertRaises(PermissionError):
            execution.compile_project(fresh)
        factory.assert_not_called()
        self.assertEqual(self.marker().read_bytes(), original)

    def test_successful_flat_compile_cleanup_does_not_block_runtime(self):
        path = self.scenario()
        backend = AuthoredProduction()
        with patch.object(execution, "_backend", return_value=backend):
            result = execution.compile_project(path)
            self.assertTrue(result["attempt"]["native_cleanup_verified"])
            self.assertFalse(result["attempt"]["native_dispatch_pending"])
            request = execution.prepare_simulation_run(path)
            result = execution.run_simulation(path, request["request_path"], request["request_sha256"])
        self.assertTrue(result["attempt"]["native_cleanup_verified"])
        self.assertFalse(self.marker().exists())

    def test_runtime_failed_stop_blocks_next_workflow(self):
        path = self.scenario()
        backend = AuthoredProduction()
        with patch.object(execution, "_backend", return_value=backend):
            execution.compile_project(path)
            request = execution.prepare_simulation_run(path)
            backend.mode = "stop_failure"
            result = execution.run_simulation(path, request["request_path"], request["request_sha256"])
        self.assertTrue(result["attempt"]["native_recovery_required"])
        self.assertEqual(result["attempt"]["native_cleanup_evidence"]["runtime_stop"], "unconfirmed")
        self.assertTrue(self.marker().exists())

    def test_failed_samples_with_confirmed_recovery_need_no_operator_barrier(self):
        path = self.scenario()
        backend = AuthoredProduction()
        with patch.object(execution, "_backend", return_value=backend):
            execution.compile_project(path)
            request = execution.prepare_simulation_run(path)
            backend.mode = "capture_failed_clean"
            result = execution.run_simulation(path, request["request_path"], request["request_sha256"])
        self.assertFalse(result["execution"]["safe_completion"])
        self.assertTrue(result["attempt"]["native_cleanup_verified"])
        self.assertFalse(self.marker().exists())

    def test_native_intent_is_durable_before_query_and_query_error_is_uncertain(self):
        path = self.scenario()
        def check_intent():
            self.assertTrue(self.attempt(path)["native_dispatch_pending"])
        with patch.object(execution, "_backend", return_value=AuthoredProduction("query_error", check_intent)):
            with self.assertRaisesRegex(RuntimeError, "connection outcome"):
                execution.compile_project(path)
        self.assertTrue(self.marker().exists())

    def test_marker_write_failure_leaves_pending_fallback_that_blocks_new_run(self):
        path = self.scenario()
        original = execution._write
        def fail_recovery(path, value, **kwargs):
            if path.name == "native_recovery_required.json":
                raise OSError("authored recovery write failure")
            return original(path, value, **kwargs)
        with patch.object(execution, "_backend", return_value=AuthoredProduction("compile_error")), \
             patch.object(execution, "_write", side_effect=fail_recovery):
            with self.assertRaisesRegex(RuntimeError, "compile interruption") as failure:
                execution.compile_project(path)
        self.assertTrue(any("recovery barrier" in note for note in failure.exception.__notes__))
        self.assertTrue(self.attempt(path)["native_dispatch_pending"])
        fresh = self.prepare()
        with patch.object(execution, "_backend") as factory, self.assertRaisesRegex(PermissionError, "prior native"):
            execution.compile_project(fresh)
        factory.assert_not_called()
        self.assertTrue(self.marker().exists())

    def test_recovery_path_uses_entry_settings_when_ambient_config_changes(self):
        path = self.scenario()
        alien = Settings(self.root / "other-data", self.vendor, (self.sources,), (self.docs,)).validated()
        other_config = self.root / "other-config.json"
        other_config.write_text(json.dumps(alien.as_dict()))
        def change_config():
            os.environ["RTDS_AGENT_CONFIG"] = str(other_config)
        with patch.object(execution, "_backend", return_value=AuthoredProduction("compile_error", change_config)):
            with self.assertRaises(RuntimeError):
                execution.compile_project(path)
        self.assertTrue(self.marker().exists())
        self.assertFalse((alien.data_dir / "native_recovery_required.json").exists())
        evidence = json.loads(self.marker().read_text(encoding="utf-8"))
        self.assertEqual(evidence["settings_sha256"], execution.sha256_json(self.settings.as_dict()))

    def test_factory_error_and_explicit_not_started_do_not_create_recovery(self):
        path = self.scenario()
        with patch.object(execution, "_backend", side_effect=RuntimeError("no driver created")):
            with self.assertRaises(RuntimeError):
                execution.compile_project(path)
        self.assertFalse(self.marker().exists())
        fresh = self.prepare()
        with patch.object(execution, "_backend", return_value=AuthoredProduction("no_native")):
            result = execution.compile_project(fresh)
        self.assertTrue(result["attempt"]["native_cleanup_verified"])
        self.assertFalse(self.marker().exists())

    def test_mock_backend_is_not_mislabeled_as_native(self):
        path = self.scenario()
        with patch.object(execution, "_backend", return_value=MockBackend(available_racks=[2], selected_rack=2)):
            result = execution.compile_project(path)
        self.assertNotIn("native_dispatch_pending", result["attempt"])
        self.assertFalse(self.marker().exists())

    def test_contradictory_no_native_receipt_does_not_prove_cleanup(self):
        base = {"native_calls_made": False, "connection_attempted": False, "connected": False}
        for contradiction in ({"connected": True}, {"cleanup_errors": ["disconnect failed"]},
                {"compile_called": True}, {"execution": {"run_call_attempted": True}}):
            with self.subTest(contradiction=contradiction):
                self.assertIsNone(execution._native_cleanup_state({**base, **contradiction},
                    runtime=True, controls=False, native_capture=False)[0])

    def test_controls_and_acquisition_cleanup_are_independent(self):
        raw = {"cleanup": {"case_closed": True, "disconnected": True},
            "execution": {"run_call_attempted": True, "stop_succeeded": True, "run_state_after_stop": "stopped"},
            "runtime_controls": {"all_restored": False},
            "acquisition": {"dispatch_stopped": True, "resources_closed": True}}
        self.assertIsNone(execution._native_cleanup_state(raw, runtime=True, controls=True, native_capture=True)[0])
        raw["runtime_controls"]["all_restored"] = True
        raw["acquisition"]["resources_closed"] = False
        self.assertIsNone(execution._native_cleanup_state(raw, runtime=True, controls=True, native_capture=True)[0])
        raw["acquisition"]["resources_closed"] = True
        self.assertTrue(execution._native_cleanup_state(raw, runtime=True, controls=True, native_capture=True)[0])

    def test_lf_and_model_native_guards_still_precede_native_intent(self):
        path = self.scenario()
        for message in ("Legacy Runtime loadflow_initialization", "No qualified scheduler"):
            with patch("rtds_agent.core.execution_requirements.require_executable_spec", side_effect=ValueError(message)), \
                 patch.object(execution, "_backend") as factory:
                with self.assertRaisesRegex(ValueError, message):
                    execution.compile_project(path)
                factory.assert_not_called()
            self.assertFalse((Path(path).parent / "compile.attempt.json").exists())
            self.assertFalse(self.marker().exists())


if __name__ == "__main__":
    unittest.main()

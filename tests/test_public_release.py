"""Public setup and safety regressions using only synthetic temporary files."""
import test_environment  # isolate config and credentials before application imports
from contextlib import redirect_stdout
import importlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rtds_agent.settings import Settings, get_settings
from rtds_agent.policy import configure_policy, require_action, execution_lock
from rtds_agent.core.state_machine import ApprovalAction, sha256_file
from rtds_agent.core.mock_backend import MockBackend
from test_runtime_backend import runtime_spec


class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rtds-public-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.vendor = self.root / "licensed install"
        self.sources = self.vendor / "Examples"
        self.docs = self.vendor / "DOC"
        self.defs = self.vendor / "MLIB/COMPONENTS"
        self.data = self.root / "user data 한글"
        for path in (self.sources, self.docs, self.defs, self.data):
            path.mkdir(parents=True)
        self.settings = Settings(self.data, self.vendor, (self.sources,), (self.docs,)).validated()
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps(self.settings.as_dict()), encoding="utf-8")
        self.environment = patch.dict(os.environ, {"RTDS_AGENT_CONFIG": str(self.config), "RSCAD_HOME": "",
                                                   "RTDS_AGENT_DATA_DIR": "", "OPENAI_VECTOR_STORE_ID": "", "OPENAI_API_KEY": ""})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        import rtds_agent.safety as safety
        import rtds_agent.core.structured_patch as patcher
        import rtds_agent.project_tools as projects
        importlib.reload(safety)
        importlib.reload(patcher)
        importlib.reload(projects)
        self.guide = self.docs / "guide.md"
        self.guide.write_text("Synthetic guide. Runtime signal capture and 원상복구.\n", encoding="utf-8")
        (self.defs / "synthetic_gain").write_text('PARAMETERS:\n Gain "Synthetic gain" "pu" REAL 1 0 10\nNODES:\n', encoding="utf-8")
        self.project = self.sources / "synthetic.rtfx"
        with zipfile.ZipFile(self.project, "w") as archive:
            archive.writestr("synthetic.dfx", "DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 1\nPARAMETERS-START:\nGain: 1\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n")

    def prepare(self):
        from rtds_agent.execution import prepare_workflow
        return prepare_workflow(str(self.project), runtime_spec(), [str(self.guide)])["workflow_path"]

    def enable(self, controls=False):
        actions = ["compile", "runtime_start_stop"] + (["runtime_controls"] if controls else [])
        return configure_policy(self.settings, actions, [2], "synthetic operator")

    def test_blank_config_environment_uses_user_default(self):
        from rtds_agent.settings import config_path, user_data_dir
        with patch.dict(os.environ, {"RTDS_AGENT_CONFIG": ""}):
            self.assertEqual(config_path(), (user_data_dir() / "config.json").resolve())

    def test_settings_portable_unicode_and_spaces(self):
        self.assertEqual(get_settings(), self.settings)

    def test_writable_roots_cannot_overlap_sources(self):
        with self.assertRaises(ValueError):
            Settings(self.sources / "write", self.vendor, (self.sources,), (self.docs,)).validated()

    def test_unknown_or_secret_config_field_rejected(self):
        payload = self.settings.as_dict()
        payload["api_key"] = "placeholder"
        self.config.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValueError):
            get_settings()

    def test_default_policy_blocks_before_backend(self):
        from rtds_agent.execution import compile_project
        with patch("rtds_agent.execution._backend") as backend, patch("rtds_agent.execution.inspect_installation") as inspect:
            with self.assertRaises(PermissionError):
                compile_project(str(self.root / "not-a-workflow.json"))
            backend.assert_not_called()
            inspect.assert_not_called()

    def test_policy_change_invalidates_old_configuration(self):
        self.enable()
        altered = Settings(self.data, self.vendor, (self.sources,), (self.docs,), "vs_example")
        with self.assertRaises(PermissionError):
            require_action(altered, "compile")

    def test_controls_are_separate_opt_in(self):
        self.enable()
        with self.assertRaises(PermissionError):
            require_action(self.settings, "runtime_start_stop", controls=True)

    def test_execution_lock_prevents_concurrent_actions(self):
        with execution_lock(self.settings):
            with self.assertRaises(PermissionError):
                with execution_lock(self.settings):
                    self.fail("Lock was bypassed")

    def test_local_index_search_and_source_tamper(self):
        from rtds_agent.knowledge import index_documents, search_rtds_local
        self.assertEqual(index_documents()["files"], 1)
        result = search_rtds_local("원상복구")
        self.assertEqual(result["results"][0]["source_path"], str(self.guide))
        self.guide.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            search_rtds_local("Runtime")

    def test_cloud_search_needs_explicit_store(self):
        from rtds_agent.knowledge import search_rtds_knowledge
        with patch("openai.OpenAI") as client:
            with self.assertRaises(ValueError):
                search_rtds_knowledge("Runtime")
            client.assert_not_called()

    def test_upload_needs_explicit_consent(self):
        from rtds_agent.knowledge import upload_documents
        with patch("openai.OpenAI") as client:
            with self.assertRaises(ValueError):
                upload_documents([str(self.guide)])
            client.assert_not_called()

    def test_manual_rejects_outside_document_roots(self):
        from rtds_agent.knowledge import get_manual_page
        with self.assertRaises(ValueError):
            get_manual_page(str(self.config))

    def test_parameter_index_rechecks_definition(self):
        from rtds_agent.knowledge import index_parameters, lookup_parameter
        self.assertEqual(index_parameters(str(self.project))["parameters"], 1)
        self.assertEqual(lookup_parameter("synthetic_gain", "Gain")["maximum"], 10)
        (self.defs / "synthetic_gain").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            lookup_parameter("synthetic_gain", "Gain")

    def test_numeric_patch_creates_new_copy_preserves_original(self):
        from rtds_agent.knowledge import index_parameters
        from rtds_agent.editing import apply_parameter_patch
        index_parameters(str(self.project))
        original = sha256_file(self.project)
        result = apply_parameter_patch(str(self.project), original, 1, "subsystem:0", "synthetic_gain", "Gain", "1", "2")
        self.assertEqual(sha256_file(self.project), original)
        self.assertIsInstance(result, dict)
        with self.assertRaises(ValueError):
            apply_parameter_patch(str(self.project), original, 1, "subsystem:0", "synthetic_gain", "Gain", "1", "200")

    def test_workflow_setup_is_offline_and_detects_source_change(self):
        from rtds_agent.execution import get_workflow_status
        path = self.prepare()
        self.assertEqual(get_workflow_status(path)["state"], "static_validated")
        self.guide.write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError):
            get_workflow_status(path)

    def test_autonomous_mock_compile_and_runtime_grants_are_single_use(self):
        from rtds_agent import execution
        path = self.prepare()
        self.enable()
        backend = MockBackend(available_racks=[2], selected_rack=2)
        with patch.object(execution, "verify_release", return_value={"synthetic": True}), \
             patch.object(execution, "inspect_installation", return_value={"synthetic": True}), \
             patch.object(execution, "_backend", return_value=backend):
            self.assertEqual(execution.compile_project(path)["state"], "compiled")
            request = execution.prepare_simulation_run(path)
            result = execution.run_simulation(path, request["request_path"], request["request_sha256"])
            self.assertEqual(result["state"], "runtime_completed")
            with self.assertRaises(ValueError):
                execution.run_simulation(path, request["request_path"], request["request_sha256"])
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual([a["status"] for a in manifest["approvals"]], ["consumed", "consumed"])
        self.assertEqual([c["call"] for c in backend.call_log], ["refresh_racks", "compile", "refresh_racks", "run_runtime"])

    def test_release_failure_prevents_backend_construction(self):
        from rtds_agent import execution
        path = self.prepare()
        self.enable()
        with patch.object(execution, "verify_release", side_effect=PermissionError("modified code")), patch.object(execution, "_backend") as backend:
            with self.assertRaises(PermissionError):
                execution.compile_project(path)
            backend.assert_not_called()

    def test_cli_init_never_overwrites_and_policy_needs_acknowledgment(self):
        from rtds_agent.cli import main
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["init"]), 1)
            self.assertEqual(main(["policy", "enable", "--actions", "compile", "--racks", "2", "--operator", "test"]), 1)
        with self.assertRaises(PermissionError):
            require_action(self.settings, "compile")

    def test_demo_is_offline_and_does_not_enable_policy(self):
        from rtds_agent.demo import run_demo
        result = run_demo()
        self.assertFalse(result["live_calls_made"])
        self.assertEqual(result["state"], "runtime_completed")
        self.assertFalse((self.data / "execution_policy.json").exists())


    def test_schema_validation_never_uses_network(self):
        from rtds_agent.execution import get_workflow_status
        path = self.prepare()
        with patch("socket.create_connection", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(get_workflow_status(path)["state"], "static_validated")

    def test_configured_rack_subset_is_applied_before_selection(self):
        from types import SimpleNamespace
        from rtds_agent.core.production_backend import ProductionBackendConfig, RscadFxCompileDriver
        racks = [SimpleNamespace(num=1), SimpleNamespace(num=2)]
        app = SimpleNamespace(connect=lambda: None, disconnect=lambda **kwargs: None,
                              get_version=lambda: "2.7.3", racks=racks, get_available_racks=lambda: racks)
        config = ProductionBackendConfig(self.vendor, self.data, allowed_racks=(2,))
        driver = RscadFxCompileDriver(config)
        with patch.object(driver, "_new_connection", return_value=app):
            self.assertEqual(driver.query_racks()["selected_rack"], 2)

    def test_modified_request_fails_before_execution(self):
        from rtds_agent import execution
        path = self.prepare()
        self.enable()
        backend = MockBackend(available_racks=[2], selected_rack=2)
        with patch.object(execution, "verify_release", return_value={"synthetic": True}), \
             patch.object(execution, "inspect_installation", return_value={"synthetic": True}), \
             patch.object(execution, "_backend", return_value=backend):
            execution.compile_project(path)
            request = execution.prepare_simulation_run(path)
            Path(request["request_path"]).write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                execution.run_simulation(path, request["request_path"], request["request_sha256"])
        self.assertNotIn("run_runtime", [item["call"] for item in backend.call_log])


if __name__ == "__main__":
    unittest.main()

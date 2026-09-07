"""Capability states are file observations, never simulation or rack qualification."""
import test_environment  # isolate config and credentials before application imports
import builtins
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_public_release as fixture
from rtds_agent import capabilities


class CapabilityTests(unittest.TestCase):
    setUp = fixture.PublicReleaseTests.setUp

    def sdk(self, version="1.1"):
        root = self.settings.sdk_root / "rtds"
        (root / "comms").mkdir(parents=True)
        sources = {
            "__init__.py": f'__version__ = "{version}"\nraise RuntimeError("SYNTHETIC API MUST NEVER EXECUTE")\n',
            "rscadfx.py": '''def remote_connection(): pass
class RSCADFX:
    def connect(self) -> None: pass
    def disconnect(self, terminate=False): pass
    def get_version(self): pass
    def open_case(self, file): pass
    def get_case(self, file, open_file=True): pass
    def _get_case_named(self, file, open_file): pass
    def get_available_racks(self): pass
class Rack:
    def __init__(self, num):
        self.num: int = num
''',
            "case.py": '''class Case:
    def close(self, force=False): pass
    def run(self) -> None: pass
    def stop(self) -> None: pass
    def update_plots(self) -> None: pass
    def get_signal(self, path) -> Signal: pass
class State:
    @ConnectedProperty(True, False)
    def run_state(self) -> str: pass
    @ConnectedProperty(True, False)
    def modified(self) -> str: pass
''',
            "case_settings.py": "class CaseSettings:\n    def starting_rack(self) -> int: pass\n",
            "component.py": '''class Component:
    @ConnectedProperty
    def subpage(self) -> str: pass
    @ConnectedProperty
    def subtab(self) -> str: pass
class Signal:
    def get_time_data(self) -> List[float]: pass
    def get_data(self) -> List[float]: pass
class IOComponent:
    @ConnectedProperty(True, True)
    def value(self): pass
class IOPositionalComponent:
    @ConnectedProperty(True, True)
    def position(self): pass
''',
            "rtx.py": "class Runtime:\n    def get_objects(self, comp_type, name): pass\n    def get_object(self, comp_id): pass\n",
            "comms/connection_setup.py": "in_existing: bool = False\nexecutable: Optional[Path] = None\ntimeout: float = 1.0\n",
        }
        for relative, text in sources.items():
            (root / relative).write_text(text, encoding="utf-8")
        (self.vendor / "BIN").mkdir()
        for name in ("RSCAD_FX.exe", "fs.exe"):
            (self.vendor / "BIN" / name).write_bytes(b"synthetic fixture, not an executable")
        return root

    def report(self):
        with patch.object(capabilities, "verify_release", return_value={"status": "passed", "manifest_sha256": "synthetic-test-evidence"}):
            return capabilities.get_capabilities()

    def test_runtime_lookup_signature_or_scope_mismatch_prevents_static_pass(self):
        root=self.sdk()
        from rtds_agent.core.runtime_api_surface import inspect_runtime_api_surface
        self.assertEqual(inspect_runtime_api_surface(site_packages=self.settings.sdk_root)['rscad_fx_version'],'unknown')
        target=root/'component.py';original=target.read_text()
        target.write_text(original.replace('@ConnectedProperty\n','@ConnectedProperty(False)\n'))
        audit=inspect_runtime_api_surface(site_packages=self.settings.sdk_root)
        self.assertFalse(audit['checks']['runtime_component_scope_readable'])
        self.assertEqual(audit['status'],'failed')
        target.write_text(original)
        (root/'rtx.py').write_text('class Runtime:\n    def get_objects(self, wrong): pass\n    def get_object(self, comp_id): pass\n')
        self.assertEqual(inspect_runtime_api_surface(site_packages=self.settings.sdk_root)['status'],'failed')

    def test_unconfigured_report_preserves_unknown_observations(self):
        config = self.settings.as_dict()
        config["rscad_home"] = None
        self.config.write_text(json.dumps(config), encoding="utf-8")
        result = self.report()
        self.assertEqual(result["versions"]["rscad_observed"], "unknown")
        self.assertEqual(result["versions"]["python_api_observed"], "unknown")
        self.assertEqual(result["runtime_api_inspection"]["status"], "not_inspected")
        self.assertFalse(result["features"]["compile"]["dependency_available"])
        self.assertTrue(result["features"]["compile"]["implemented"])

    def test_missing_installation_is_structured_and_policy_remains_inactive(self):
        result = self.report()
        self.assertEqual(result["runtime_api_inspection"]["status"], "unavailable")
        self.assertEqual(result["installation_files"]["rscad_executable"]["status"], "missing")
        self.assertEqual(result["policy"]["status"], "inactive")
        self.assertEqual(result["policy"]["actions"], [])
        self.assertFalse((self.data / "execution_policy.json").exists())

    def test_partial_api_reports_observed_version_and_missing_files(self):
        root = self.sdk()
        (root / "rtx.py").unlink()
        result = self.report()
        self.assertEqual(result["versions"]["python_api_observed"], "1.1")
        self.assertEqual(result["runtime_api_inspection"]["unavailable_files"], ["rtx.py"])
        self.assertFalse(result["features"]["runtime_capture"]["statically_inspected"])

    def test_supported_static_api_is_not_live_or_integration_qualification(self):
        self.sdk()
        result = self.report()
        self.assertEqual(result["runtime_api_inspection"]["status"], "passed", result["runtime_api_inspection"])
        self.assertTrue(result["features"]["runtime_capture"]["statically_inspected"])
        self.assertFalse(result["features"]["compile"]["statically_inspected"])
        self.assertFalse(result["features"]["offline_fsat"]["statically_inspected"])
        self.assertTrue(all(not feature["integration_qualified"] for feature in result["features"].values()))
        self.assertEqual(result["versions"]["rscad_configured"], "2.7.3")
        self.assertEqual(result["versions"]["rscad_observed"], "unknown")
        self.assertEqual(result["qualification"]["state"], "not_evaluated")
        self.assertEqual(result["policy"]["status"], "inactive")

    def test_unsupported_observed_api_version_is_distinct_from_target(self):
        self.sdk(version="9.9")
        result = self.report()
        self.assertEqual(result["versions"]["python_api_supported"], "1.1")
        self.assertEqual(result["versions"]["python_api_observed"], "9.9")
        self.assertEqual(result["runtime_api_inspection"]["status"], "failed")
        self.assertFalse(result["runtime_api_inspection"]["checks"]["api_version_1_1"])
        self.assertFalse(result["features"]["runtime_controls"]["statically_inspected"])

    def test_unsupported_configured_version_returns_report_without_reconfiguring(self):
        value = self.settings.as_dict()
        value["expected_rscad_version"] = "9.9"
        self.config.write_text(json.dumps(value), encoding="utf-8")
        before = self.config.read_bytes()
        result = self.report()
        self.assertEqual(result["configuration"]["status"], "invalid")
        self.assertEqual(result["versions"]["rscad_configured"], "9.9")
        self.assertEqual(result["versions"]["rscad_observed"], "unknown")
        self.assertEqual(self.config.read_bytes(), before)

    def test_poppler_absence_is_independent_of_runtime_api(self):
        self.sdk()
        with patch.object(capabilities.shutil, "which", return_value=None):
            result = self.report()
        self.assertFalse(result["poppler_available"])
        self.assertFalse(result["features"]["manual_figure_rendering"]["dependency_available"])
        self.assertIn("Poppler", result["features"]["manual_figure_rendering"]["reasons"][0])
        self.assertTrue(result["features"]["runtime_capture"]["statically_inspected"])

    def test_linux_reports_static_parse_support_without_live_adapter_support(self):
        self.sdk()
        with patch.object(capabilities.sys, "platform", "linux"):
            result = self.report()
        self.assertFalse(result["host"]["live_adapter_host_supported"])
        self.assertTrue(result["features"]["project_parsing"]["dependency_available"])
        self.assertTrue(result["features"]["runtime_capture"]["statically_inspected"])
        self.assertFalse(result["features"]["runtime_capture"]["dependency_available"])
        self.assertFalse(result["features"]["offline_fsat"]["dependency_available"])

    def test_no_vendor_import_subprocess_connection_or_file_mutation(self):
        self.sdk()
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        real_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "rtds" or name.startswith("rtds."):
                raise AssertionError("Vendor package import is forbidden")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", guarded), patch("socket.create_connection", side_effect=AssertionError("Network")), \
             patch("subprocess.run", side_effect=AssertionError("Subprocess")):
            result = self.report()
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(result["sdk_imported"])
        self.assertFalse(result["rack_query_called"])
        self.assertFalse(result["mutations_performed"])

    def test_active_policy_is_reported_without_operator_or_grant_claim(self):
        self.sdk()
        from rtds_agent.policy import configure_policy
        configure_policy(self.settings, ["compile"], [2], "SYNTHETIC PRIVATE OPERATOR")
        result = self.report()
        self.assertEqual(result["policy"]["actions"], ["compile"])
        self.assertEqual(result["policy"]["configured_allowed_racks"], [2])
        self.assertFalse(result["policy"]["live_racks_observed"])
        self.assertNotIn("SYNTHETIC PRIVATE OPERATOR", json.dumps(result))
        self.assertEqual(result["features"]["compile"]["live_execution_eligibility"], "requires_workflow_validation")

    def test_release_failure_does_not_hide_capability_or_enable_execution(self):
        self.sdk()
        with patch.object(capabilities, "verify_release", side_effect=PermissionError("synthetic stale release")):
            result = capabilities.get_capabilities()
        self.assertEqual(result["release_integrity"]["status"], "failed")
        self.assertIn("Release integrity", " ".join(result["features"]["runtime_capture"]["reasons"]))
        self.assertFalse(result["qualification"]["integration_qualified"])

    def test_unqualified_extensions_return_specific_gaps(self):
        result = self.report()
        for name in ("structural_editing", "gui_runtime_target_discovery"):
            self.assertFalse(result["features"][name]["implemented"])
            self.assertIsNone(result["features"][name]["dependency_available"])
            self.assertIn("unsupported", result["features"][name]["reasons"][0])
            self.assertGreater(len(result["features"][name]["reasons"]), 1)


if __name__ == "__main__":
    unittest.main()

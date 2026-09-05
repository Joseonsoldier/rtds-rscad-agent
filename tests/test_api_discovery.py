"""Synthetic SDK declarations. Importing the fixture would deliberately fail."""
import test_environment
import builtins
from pathlib import Path
import unittest
from unittest.mock import patch
import test_public_release as fixture
from rtds_agent import api_discovery as api
from rtds_agent.safety import sha256_file
from rtds_agent.settings import Settings

SOURCE = '''"""Authored Runtime API documentation."""
raise AssertionError("SDK must not execute")
def collect_signal(channel: str, /, samples=8, *extra, timeout: float = 1.0, **options) -> list[float]:
    """Read a runtime signal in this synthetic API. No real implementation."""
    raise AssertionError("must not call")
class Device:
    """Synthetic device, no connection."""
    def collect_signal(self, name):
        """Read another runtime signal."""
        raise AssertionError("must not call")
    @staticmethod
    async def wait(*, delay=1) -> None:
        pass
    @property
    def value(self):
        """Observed property declaration."""
        return 1
    @value.setter
    def value(self, new):
        pass
def factory():
    def hidden():
        pass
    return hidden
'''


class APIDiscoveryTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        self.sdk = self.settings.sdk_root / "rtds"
        self.sdk.mkdir(parents=True)
        (self.sdk / "__init__.py").write_text('__version__ = "1.1"\nraise RuntimeError("No imports")\n', encoding="utf-8")
        self.api_file = self.sdk / "api.py"
        self.api_file.write_text(SOURCE, encoding="utf-8")

    def test_search_then_exact_lookup_preserves_signature_and_snapshot(self):
        found = api.search_rscad_api("runtime signal", expected_api_version="1.1")
        symbols = {r["symbol"] for r in found["results"]}
        self.assertIn("rtds.api.collect_signal", symbols)
        self.assertIn("rtds.api.Device.collect_signal", symbols)
        result = api.lookup_rscad_api("rtds.api.collect_signal", "1.1", found["snapshot_id"])
        self.assertEqual(result["status"], "found")
        row = result["result"]
        self.assertIn("channel: str, /", row["signature"])
        self.assertIn("*extra", row["signature"])
        self.assertIn("**options", row["signature"])
        self.assertIn("-> list[float]", row["signature"])
        self.assertEqual(row["source_sha256"], sha256_file(self.api_file))
        self.assertEqual(row["source_type"], "installed_api")
        self.assertEqual(row["evidence_level"], "direct")
        self.assertEqual(row["api_version"], "1.1")
        self.assertEqual(row["version_match"], "exact")
        self.assertEqual(result["observed_rscad_version"], "unknown")

    def test_modules_classes_async_and_properties(self):
        for symbol, kind in (("rtds.api", "module"), ("Device", "class"), ("Device.wait", "method")):
            row = api.lookup_rscad_api(symbol)["result"]
            self.assertEqual(row["kind"], kind)
        row = api.lookup_rscad_api("Device.wait")["result"]
        self.assertTrue(row["async_function"])
        self.assertIn("staticmethod", row["decorators"])
        # Getter/setter share a spelling. Return both source locations, not one
        # invented callable signature for the descriptor.
        self.assertEqual(api.lookup_rscad_api("Device.value")["status"], "ambiguous")

    def test_nonexistent_and_matlab_names_remain_unresolved(self):
        for name in ("rtds.api.Device.magic_auto_tune", "simulink.SimulationInput", "hidden", "rtds.api.NoSuchClass"):
            result = api.lookup_rscad_api(name)
            self.assertEqual(result["status"], "unresolved")
            self.assertEqual(result["evidence_level"], "unknown")
            self.assertIsNone(result["result"])
            self.assertEqual(result["searched_sources"], ["installed_api"])
        self.assertEqual(api.search_rscad_api("nonexistent_signal_magic")["status"], "unresolved")

    def test_ambiguous_suffix_never_selects_first(self):
        result = api.lookup_rscad_api("collect_signal")
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["result"])
        self.assertEqual(result["total_matches"], 2)

    def test_search_limit_exposes_remaining_matches(self):
        result = api.search_rscad_api("signal", top_k=1)
        self.assertTrue(result["truncated"])
        self.assertGreater(result["total_matches"], 1)
        self.assertEqual(len(result["results"]), 1)

    def test_version_mismatch_and_missing_literal_are_not_installed_match(self):
        result = api.lookup_rscad_api("Device", "2.0")
        self.assertEqual(result["version_match"], "mismatch")
        self.assertEqual(result["result"]["api_version"], "1.1")
        (self.sdk / "__init__.py").write_text('__version__ = read_version()\n', encoding="utf-8")
        self.assertEqual(api.lookup_rscad_api("Device", "1.1")["version_match"], "compatible_unknown")
        self.assertEqual(api.lookup_rscad_api("Device")["api_version"], "unknown")

    def test_readonly_and_no_sdk_network_process_or_hardware(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "rtds" or name.startswith("rtds."):
                raise AssertionError("Vendor import forbidden")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded), patch("socket.socket.connect", side_effect=AssertionError("network")), patch("subprocess.Popen", side_effect=AssertionError("process")), patch("rtds_agent.execution._backend", side_effect=AssertionError("live backend")):
            for result in (api.search_rscad_api("signal"), api.lookup_rscad_api("Device")):
                self.assertFalse(result["sdk_imported"])
                self.assertFalse(result["live_calls_made"])
                self.assertFalse(result["mutations_performed"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_stale_snapshot_detects_same_size_edit_and_added_file(self):
        snapshot = api.search_rscad_api("Device")["snapshot_id"]
        self.api_file.write_text(SOURCE.replace("samples=8", "samples=9"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            api.lookup_rscad_api("Device", snapshot_id=snapshot)
        snapshot = api.search_rscad_api("Device")["snapshot_id"]
        (self.sdk / "extra.py").write_text("def extra(): pass\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            api.lookup_rscad_api("Device", snapshot_id=snapshot)

    def test_change_during_inspection_fails_closed(self):
        original = api._declarations
        def changing(*args):
            result = original(*args)
            if args[1] == "rtds.api":
                self.api_file.write_text(SOURCE + "# changed\n", encoding="utf-8")
            return result
        with patch.object(api, "_declarations", side_effect=changing):
            with self.assertRaisesRegex(ValueError, "changed during"):
                api.search_rscad_api("signal")

    def test_partial_source_and_conditional_declarations_are_explicit(self):
        (self.sdk / "bad.py").write_text("invalid python @@@", encoding="utf-8")
        (self.sdk / "conditional.py").write_text("if hardware_ready():\n    def conditional_run(): pass\n", encoding="utf-8")
        result = api.lookup_rscad_api("conditional_run")
        self.assertEqual(result["status"], "unresolved")
        self.assertEqual(result["catalog_status"], "partial")
        self.assertEqual(len(result["coverage"]["limitations"]), 2)
        self.assertEqual(api.lookup_rscad_api("Device")["status"], "found")

    def test_absent_installation_no_write_and_no_fake_version(self):
        with patch.object(api, "get_settings", return_value=Settings(self.data)):
            result = api.lookup_rscad_api("Device")
        self.assertEqual(result["catalog_status"], "unavailable")
        self.assertEqual(result["api_version"], "unknown")
        self.assertEqual(result["status"], "unresolved")

    def test_invalid_queries_and_limits_rejected(self):
        for kwargs in ({"query": ""}, {"query": "!@#"}, {"query": "x", "top_k": True}, {"query": "x", "top_k": 21}):
            with self.assertRaises(ValueError): api.search_rscad_api(**kwargs)
        for symbol in ("../secret", "rtds.run()", "", "x" * 301):
            with self.assertRaises(ValueError): api.lookup_rscad_api(symbol)
        with self.assertRaises(ValueError): api.lookup_rscad_api("Device", expected_api_version="guess")
        with self.assertRaises(ValueError): api.lookup_rscad_api("Device", snapshot_id="stale")

    def test_resource_limits_reject_instead_of_truncating_catalog(self):
        for name, value in (("MAX_FILES", 1), ("MAX_FILE_BYTES", 20), ("MAX_TOTAL_BYTES", 20), ("MAX_SYMBOLS", 1), ("MAX_ENTRIES", 1)):
            with patch.object(api, name, value), self.assertRaises(ValueError):
                api.search_rscad_api("signal")

    def test_docstring_truncation_is_reported(self):
        self.api_file.write_text('def large():\n    """' + 'signal ' * 2000 + '"""\n    pass\n', encoding="utf-8")
        row = api.lookup_rscad_api("large")["result"]
        self.assertTrue(row["documentation_truncated"])
        self.assertEqual(len(row["documentation"]), 12000)

    def test_reexport_is_not_invented_as_a_declared_method(self):
        (self.sdk / "alias.py").write_text("from .api import Device as Alias\n", encoding="utf-8")
        result = api.lookup_rscad_api("rtds.alias.Alias")
        self.assertEqual(result["status"], "unresolved")
        self.assertIn("import aliases/re-exports", result["coverage"]["not_resolved"])

    def test_symlink_escape_is_rejected_before_source_read(self):
        # Use a mocked reparse marker for portability; no elevated OS link creation.
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda p: p == self.api_file or original(p)):
            with self.assertRaisesRegex(ValueError, "link"):
                api.search_rscad_api("signal")

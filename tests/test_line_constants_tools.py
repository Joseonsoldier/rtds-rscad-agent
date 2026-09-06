"""Synthetic supplied-record boundary tests; never invoke native generation."""
import test_environment
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rtds_agent import line_authoring as observation_module
from rtds_agent import line_constants as reader
from rtds_agent.safety import ToolSafetyError
from rtds_agent.settings import Settings
from test_line_constants import TLI, TLO


class LineConstantsToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.settings = Settings(self.data)
        settings_patch = patch.object(observation_module, "get_settings", return_value=self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.source = self.data / "authored.tli"
        self.output = self.data / "authored.tlo"
        self.guide = self.data / "authored-evidence.txt"
        self.artifact = self.data / "authored-generator.txt"
        self.events = self.data / "authored-events.json"
        self.receipt_path = self.data / "receipt.json"
        self.request_path = self.data / "request.json"
        self.source.write_bytes(TLI)
        self.output.write_bytes(TLO)
        self.guide.write_bytes(b"Authored numerical test declaration")
        self.artifact.write_bytes(b"Authored synthetic artifact; no executable")
        self.events.write_bytes(b'{"declared_event":"synthetic_only"}')
        self.value = {"schema_version": "1.0", "profile_id": "tline_rlc_3phase_ohmic_v1",
                      "input": self.ref(self.source), "output": self.ref(self.output),
                      "generation_receipt": None,
                      "provenance": [self.provenance(path) for path in (self.source, self.output, self.guide)]}
        self.receipt = {"schema_version": "1.0", "attempt_id": "authored_attempt_1",
                        "profile_id": self.value["profile_id"], "status": "completed",
                        "input": self.ref(self.source), "output": self.ref(self.output),
                        "generator": {"kind": "synthetic_authored",
                                      "entrypoint": "v5applications.tlineedit.datamodel.TLRLCData.generateTLO",
                                      "artifacts": [self.ref(self.artifact)]},
                        "execution": {"exit_code": 0, "fresh_output_directory": True, "network_denied": True,
                                      "child_processes_denied": True, "writes_restricted": True,
                                      "events": self.ref(self.events)}}
        self.save()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def ref(self, path):
        return {"path": str(path), "sha256": self.sha(path)}

    def provenance(self, path):
        return {"source_path": str(path), "source_sha256": self.sha(path), "locator": "Authored test source"}

    def save(self, *, receipt=False):
        if receipt:
            self.receipt_path.write_text(json.dumps(self.receipt), encoding="utf-8")
            self.value["generation_receipt"] = self.ref(self.receipt_path)
        self.request_path.write_text(json.dumps(self.value), encoding="utf-8")

    def inspect(self):
        return reader.inspect_line_constants(str(self.request_path))

    def snapshot(self):
        return {str(path): path.read_bytes() for path in self.data.rglob("*") if path.is_file()}

    def update_model_refs(self):
        self.value["input"] = self.ref(self.source)
        self.value["output"] = self.ref(self.output)
        self.value["provenance"][:2] = [self.provenance(self.source), self.provenance(self.output)]
        self.save()

    def test_deterministic_read_only_comparison_has_no_native_or_freshness_authority(self):
        before = self.snapshot()
        with (patch("socket.socket", side_effect=AssertionError("network")),
              patch("socket.create_connection", side_effect=AssertionError("network")),
              patch("subprocess.Popen", side_effect=AssertionError("process"))):
            report = self.inspect()
        self.assertEqual(report, self.inspect())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(report["status"], "consistent")
        self.assertEqual(report["files_written"], 0)
        self.assertEqual(report["generation_record"]["status"], "not_supplied")
        for flag in ("native_origin_verified", "freshness_verified", "generator_execution_verified",
                     "integration_qualified", "execution_authorized", "generation_called", "compile_called",
                     "sdk_imported", "live_calls_made", "automatic_retry"):
            self.assertIs(report[flag], False)
        self.assertEqual(report["engineering_verdict"], "not_evaluated")
        self.assertFalse(report["algorithm_evidence_status"]["current_sources_verified"])
        self.assertTrue(report["grounding"]["references_current"])

    def test_bound_supplied_receipt_retains_declarations_without_authenticating_them(self):
        self.save(receipt=True)
        before = self.snapshot()
        report = self.inspect()
        record = report["generation_record"]
        self.assertEqual(record["status"], "bound_supplied_record")
        self.assertEqual(record["attempt_id"], "authored_attempt_1")
        self.assertFalse(record["claims_verified"])
        self.assertFalse(report["freshness_verified"])
        self.assertFalse(report["generator_execution_verified"])
        self.assertTrue(record["declared_execution"]["network_denied"])
        self.assertIn("not origin", record["limitation"])
        sources = {row["source_path"]: row["source_sha256"] for row in report["source_bindings"]}
        for path in (self.source, self.output, self.guide, self.artifact, self.events, self.receipt_path, self.request_path):
            self.assertEqual(sources[str(path.resolve())], self.sha(path))
        self.assertEqual(before, self.snapshot())

    def test_all_nested_stale_hashes_are_refused(self):
        self.save(receipt=True)
        for path in (self.source, self.output, self.guide, self.artifact, self.events, self.receipt_path):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\n")
                with self.subTest(path=path.name), self.assertRaises(ToolSafetyError):
                    self.inspect()
            finally:
                path.write_bytes(original)

    def test_all_observed_files_are_revalidated_after_comparison(self):
        self.save(receipt=True)
        compare = reader.core.compare_line_constants
        for path in (self.source, self.output, self.guide, self.artifact, self.events, self.receipt_path, self.request_path):
            original = path.read_bytes()
            def mutate(*args):
                report = compare(*args)
                path.write_bytes(original + b"\n")
                return report
            try:
                with self.subTest(path=path.name), patch.object(reader.core, "compare_line_constants", side_effect=mutate):
                    with self.assertRaises(ToolSafetyError):
                        self.inspect()
            finally:
                path.write_bytes(original)

    def test_settings_and_constants_implementation_changes_refuse_return(self):
        with patch.object(observation_module, "get_settings", side_effect=[self.settings, Settings(self.root / "other")]):
            with self.assertRaises(ToolSafetyError):
                self.inspect()
        implementation = self.data / "authored-implementation.py"
        implementation.write_bytes(b"Authored implementation evidence")
        files = [*reader._implementation_files(), implementation]
        compare = reader.core.compare_line_constants
        def mutate(*args):
            report = compare(*args)
            implementation.write_bytes(b"Changed implementation evidence")
            return report
        with patch.object(reader, "_implementation_files", return_value=files), patch.object(reader.core, "compare_line_constants", side_effect=mutate):
            with self.assertRaises(ToolSafetyError):
                self.inspect()

    def test_exact_receipt_input_output_and_profile_binding(self):
        original = copy.deepcopy(self.receipt)
        for role, field, value in (("input", "sha256", "0" * 64), ("output", "sha256", "0" * 64),
                                   ("input", "path", str(self.data / "other.tli")),
                                   ("output", "path", str(self.data / "other.tlo"))):
            self.receipt = copy.deepcopy(original)
            self.receipt[role][field] = value
            self.save(receipt=True)
            with self.subTest(role=role, field=field), self.assertRaises((ValueError, ToolSafetyError)):
                self.inspect()
        self.receipt = copy.deepcopy(original)
        self.receipt["profile_id"] = "cable"
        self.save(receipt=True)
        with self.assertRaises((ValueError, ToolSafetyError)):
            self.inspect()

    def test_current_profile_hash_and_path_provenance_required(self):
        original = copy.deepcopy(self.value)
        for role in ("input", "output"):
            self.value = copy.deepcopy(original)
            self.value["provenance"] = [row for row in self.value["provenance"] if row["source_path"] != self.value[role]["path"]]
            self.save()
            with self.subTest(role=role), self.assertRaises(ToolSafetyError):
                self.inspect()
        self.value = copy.deepcopy(original)
        self.value["provenance"].append(copy.deepcopy(self.value["provenance"][0]))
        self.save()
        with self.assertRaises(ToolSafetyError):
            self.inspect()

    def test_inconsistent_and_inconclusive_keep_detailed_parser_evidence(self):
        self.output.write_bytes(TLO.replace(b" 200 ", b" 201 "))
        self.update_model_refs()
        self.assertEqual(self.inspect()["status"], "inconsistent")
        self.output.write_bytes(TLO + b"NEW FORMAT 19\n")
        self.update_model_refs()
        report = self.inspect()
        self.assertEqual(report["status"], "inconclusive")
        self.assertIn("exactly one header", report["output_inspection"]["reasons"][0])
        self.assertEqual(report["output_inspection"]["raw_lines"][-1]["text"], "NEW FORMAT 19")
        self.assertEqual(report["output_inspection"]["source_sha256"], self.sha(self.output))
        self.output.write_bytes(TLO)
        self.source.write_bytes(TLI.replace(b"Data Entry Format = 0", b"Data Entry Format = 1"))
        self.update_model_refs()
        report = self.inspect()
        self.assertEqual(report["status"], "inconclusive")
        self.assertEqual(report["input_inspection"]["status"], "unsupported")
        self.assertTrue(report["input_inspection"]["reasons"])

    def test_outside_relative_traversal_absent_and_linked_paths_refused(self):
        outside = self.root / "outside.tli"
        outside.write_bytes(TLI)
        original = copy.deepcopy(self.value)
        for path in (str(outside), "authored.tli", str(self.data / ".." / "data" / "authored.tli"), str(self.data / "missing.tli")):
            self.value = copy.deepcopy(original)
            self.value["input"]["path"] = path
            self.save()
            with self.subTest(path=path), self.assertRaises(ToolSafetyError):
                self.inspect()
        self.value = original
        self.save()
        is_link = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda path: path == self.data or is_link(path)):
            with self.assertRaises(ToolSafetyError):
                self.inspect()

    def test_filename_and_profile_aliases_do_not_inherit_metric_semantics(self):
        original = copy.deepcopy(self.value)
        for role, suffix in (("input", ".cli"), ("input", ".tlii"), ("output", ".clo"), ("output", ".txt")):
            path = self.data / ("alias" + suffix)
            path.write_bytes(TLI if role == "input" else TLO)
            self.value = copy.deepcopy(original)
            self.value[role] = self.ref(path)
            self.save()
            with self.subTest(role=role, suffix=suffix), self.assertRaises(ToolSafetyError):
                self.inspect()
        self.value = copy.deepcopy(original)
        self.value["profile_id"] = "tline_rlc_3phase"
        self.save()
        with self.assertRaises((ValueError, ToolSafetyError)):
            self.inspect()

    def test_strict_requests_receipts_duplicates_and_loaded_schemas(self):
        valid = copy.deepcopy(self.value)
        self.value["automatic_execute"] = True
        self.save()
        with self.assertRaises((ValueError, ToolSafetyError)):
            self.inspect()
        self.value = valid
        self.receipt["execution"]["automatic_retry"] = True
        self.save(receipt=True)
        with self.assertRaises((ValueError, ToolSafetyError)):
            self.inspect()
        del self.receipt["execution"]["automatic_retry"]
        self.receipt["generator"]["artifacts"] *= 2
        self.save(receipt=True)
        with self.assertRaises(ToolSafetyError):
            self.inspect()
        self.receipt["generator"]["artifacts"] = [self.ref(self.artifact)]
        self.save(receipt=True)
        with patch.object(reader, "RECEIPT_SCHEMA", {}), self.assertRaises(ToolSafetyError):
            self.inspect()
        with patch.object(reader, "REQUEST_SCHEMA", {}), self.assertRaises(ToolSafetyError):
            self.inspect()
        self.request_path.write_bytes(b'{"schema_version":"1.0","schema_version":"1.0"}')
        with self.assertRaises(ToolSafetyError):
            self.inspect()

    def test_json_input_output_aggregate_and_result_bounds(self):
        for payload in (b'{"x":NaN}', b" " * 400001, b" " * 100001):
            self.request_path.write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises((ValueError, ToolSafetyError)):
                self.inspect()
        self.save()
        for path, raw in ((self.source, TLI), (self.output, TLO)):
            path.write_bytes(b" " * 65537)
            self.update_model_refs()
            with self.subTest(path=path.name), self.assertRaises(ToolSafetyError):
                self.inspect()
            path.write_bytes(raw)
        self.update_model_refs()
        with patch.object(observation_module, "MAX_TOTAL_BYTES", 10), self.assertRaises(ToolSafetyError):
            self.inspect()
        with patch.object(observation_module, "MAX_OUTPUT_BYTES", 10), self.assertRaises(ToolSafetyError):
            self.inspect()


if __name__ == "__main__":
    unittest.main()

"""Authored scalar TLI fixtures; no vendor assets or native operations."""
import test_environment
import copy
import hashlib
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rtds_agent.core.line_authoring import LINE_AUTHORING_SCHEMA, PROFILE_ID, inspect_line_input, line_authoring_catalog, preview_line_input, validate_line_request


RAW = b'''Line Summary:
  {
  Line Length = 10.00
  Steady State Frequency = 50.0
  }
Line Constants Ground Data:
  {
  GroundResistivity = 100.0
  }
RLC Options:
  {
  Data Entry Format = 0
  Positive Sequence Series Resistance = 0.1
  Positive Sequence Series Ind Reactance = 0.3
  Positive Sequence Series Cap Reactance = 0.5
  Zero Sequence Series Resistance = 0.2
  Zero Sequence Series Ind Reactance = 0.4
  Zero Sequence Series Cap Reactance = 0.6
  Number of Phases = 3
  }
'''


def request(raw=RAW, changes=None):
    digest = hashlib.sha256(raw).hexdigest()
    return {"schema_version": "1.0", "profile_id": PROFILE_ID, "source": {"path": "C:/authored/line.tli", "sha256": digest},
            "assumptions": {"ideally_transposed": True, "frequency_independent_bergeron": True},
            "changes": [{"field": "line_length_km", "expected": 10, "value": 20}] if changes is None else changes,
            "provenance": [{"source_path": "C:/authored/line.tli", "source_sha256": digest, "locator": "Authored synthetic input fixture"}]}


class LineInputTests(unittest.TestCase):
    def test_catalog_and_schema_are_narrow_non_authorizing(self):
        Draft202012Validator.check_schema(LINE_AUTHORING_SCHEMA)
        catalog = line_authoring_catalog()
        self.assertEqual(len(catalog["editable_fields"]), 8)
        self.assertEqual(catalog["profile_constants"], {"data_entry_format": 0, "number_of_phases": 3})
        self.assertEqual(catalog["editable_fields"]["xc_positive_megohm_km"]["units"], "megohm*km")
        self.assertIn("shunt", " ".join(catalog["limitations"]))
        self.assertFalse(catalog["integration_qualified"])
        self.assertFalse(catalog["solver_called"])

    def test_exact_profile_fields_and_numeric_source_spans(self):
        report = inspect_line_input(RAW)
        self.assertEqual(report["status"], "supported", report)
        self.assertEqual(len(report["fields"]), 8)
        self.assertEqual(report["fields"]["line_length_km"]["value"], 10)
        self.assertEqual(report["fields"]["line_length_km"]["raw_value"], "10.00")
        for row in [*report["fields"].values(), *report["preserved"].values()]:
            self.assertEqual(RAW[row["byte_start"]:row["byte_end"]].decode(), row["raw_value"])
        self.assertEqual(report["source_sha256"], hashlib.sha256(RAW).hexdigest())

    def test_unknown_revision_geometry_perunit_phase_count_extra_fields_and_blocks_refused(self):
        variants = [b"!RTDS_REVISION = 3\n" + RAW,
                    RAW + b"Line Constants Tower:\n{\nRadius = 1\n}\n",
                    RAW.replace(b"Data Entry Format = 0", b"Data Entry Format = 1"),
                    RAW.replace(b"Number of Phases = 3", b"Number of Phases = 6"),
                    RAW.replace(b"Number of Phases = 3", b"Number of Phases = 3e0"),
                    RAW.replace(b"Number of Phases = 3", b"Number of Phases = 03"),
                    RAW.replace(b"Data Entry Format = 0", b"Data Entry Format = +0"),
                    RAW.replace(b"Data Entry Format = 0", b"Data Entry Format = 0.0"),
                    RAW.replace(b"Number of Phases = 3", b"Unknown = 3\nNumber of Phases = 3"),
                    RAW + b"Line Summary:\n{\nLine Length = 30\nSteady State Frequency = 50\n}\n"]
        for raw in variants:
            with self.subTest(raw=raw):
                result = inspect_line_input(raw)
                self.assertEqual(result["status"], "unsupported")
                self.assertEqual(result["fields"], {})
                self.assertTrue(result["reasons"])
                with self.assertRaises(ValueError): preview_line_input(raw, request(raw))

    def test_duplicate_missing_malformed_and_misplaced_fields_are_unsupported(self):
        variants = [RAW.replace(b"Line Length = 10.00", b"Line Length = 10.00\nLine Length = 20"),
                    RAW.replace(b"  GroundResistivity = 100.0\n", b""), RAW[:-4],
                    RAW.replace(b"Line Length = 10.00", b"Line Length = 10 + 1"),
                    RAW.replace(b"Line Length = 10.00", b"Line Length = 10 # comment"),
                    RAW.replace(b"GroundResistivity = 100.0", b"Number of Phases = 3"),
                    RAW.replace(b"Line Summary:\n  {", b"Line Summary:\n  {{")]
        for raw in variants:
            with self.subTest(raw=raw):
                self.assertEqual(inspect_line_input(raw)["status"], "unsupported")

    def test_strict_scalar_domains_and_unrepresentable_numbers(self):
        for token in (b"NaN", b"Infinity", b"1e999", b"1e-999", b"0", b"-2", b"true"):
            raw = RAW.replace(b"Line Length = 10.00", b"Line Length = " + token)
            self.assertEqual(inspect_line_input(raw)["status"], "unsupported", token)
        for field in (b"Positive Sequence Series Ind Reactance", b"Zero Sequence Series Cap Reactance"):
            token = b"0.3" if b"Ind" in field else b"0.6"
            raw = RAW.replace(field + b" = " + token, field + b" = 0")
            self.assertEqual(inspect_line_input(raw)["status"], "unsupported")
        raw = RAW.replace(b"Positive Sequence Series Resistance = 0.1", b"Positive Sequence Series Resistance = -0.1")
        self.assertEqual(inspect_line_input(raw)["status"], "unsupported")

    def test_input_bytes_lines_encoding_and_unknown_profile_are_bounded(self):
        for raw in (b" " * 65537, b"\n" * 1025, b"\xef\xbb\xbf" + RAW, RAW + b"\x00", RAW + b"\xff"):
            self.assertEqual(inspect_line_input(raw)["status"], "unsupported")
        self.assertEqual(inspect_line_input(RAW, "guessed-profile")["status"], "unsupported")
        with self.assertRaises(ValueError): inspect_line_input("not bytes")


class LinePreviewTests(unittest.TestCase):
    def test_source_hash_expected_mismatch_and_numeric_noops_are_rejected(self):
        req = request(); req["source"]["sha256"] = "0" * 64; req["provenance"][0]["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source hash"): preview_line_input(RAW, req)
        req = request(); req["changes"][0]["expected"] = 11
        with self.assertRaisesRegex(ValueError, "Expected line field"): preview_line_input(RAW, req)
        req = request(); req["changes"][0]["value"] = 10.0
        with self.assertRaisesRegex(ValueError, "no-ops"): preview_line_input(RAW, req)

    def test_expected_equality_uses_exact_decimal_not_rounded_binary_float(self):
        raw = RAW.replace(b"Line Length = 10.00", b"Line Length = 10.0000000000000000001")
        self.assertEqual(inspect_line_input(raw)["status"], "supported")
        with self.assertRaisesRegex(ValueError, "Expected line field"):
            preview_line_input(raw, request(raw))

    def test_multiple_token_edits_preserve_all_other_bytes_and_reparse(self):
        raw = RAW.replace(b"\n", b"\r\n").replace(b" = ", b"\t=  ")
        req = request(raw, [{"field": "xc_zero_megohm_km", "expected": 0.6, "value": 0.7654321},
                            {"field": "line_length_km", "expected": 10, "value": 1234},
                            {"field": "r_positive_ohm_per_km", "expected": 0.1, "value": 0.25}])
        before = copy.deepcopy(req)
        report, candidate = preview_line_input(raw, req)
        self.assertEqual(req, before)
        source_cursor = candidate_cursor = 0
        for edit in report["changes"]:
            self.assertEqual(raw[source_cursor:edit["source_byte_start"]], candidate[candidate_cursor:edit["candidate_byte_start"]])
            self.assertEqual(candidate[edit["candidate_byte_start"]:edit["candidate_byte_end"]].decode(), edit["new_token"])
            source_cursor, candidate_cursor = edit["source_byte_end"], edit["candidate_byte_end"]
        self.assertEqual(raw[source_cursor:], candidate[candidate_cursor:])
        self.assertEqual(candidate.count(b"\r\n"), raw.count(b"\r\n"))
        self.assertEqual(report["candidate_sha256"], hashlib.sha256(candidate).hexdigest())
        self.assertEqual(report["after"]["fields"]["r_positive_ohm_per_km"]["value"], 0.25)
        for field in report["before"]["preserved"]:
            self.assertEqual(report["before"]["preserved"][field]["raw_value"], report["after"]["preserved"][field]["raw_value"])

    def test_profile_specific_zero_resistance_refusal_and_no_frequency_rescaling(self):
        with self.assertRaises(ValueError):
            preview_line_input(RAW, request(changes=[{"field": "r_zero_ohm_per_km", "expected": 0.2, "value": 0}]))
        raw = RAW.replace(b"Positive Sequence Series Resistance = 0.1", b"Positive Sequence Series Resistance = 0")
        self.assertEqual(inspect_line_input(raw)["status"], "unsupported")
        report, _ = preview_line_input(RAW, request(changes=[{"field": "frequency_hz", "expected": 50, "value": 60}]))
        self.assertEqual(report["before"]["fields"]["x_positive_ohm_per_km"]["value"], report["after"]["fields"]["x_positive_ohm_per_km"]["value"])
        self.assertIn("does not automatically rescale", " ".join(report["after"]["limitations"]))

    def test_schema_rejects_bools_nonfinite_negative_unknown_duplicates_and_unsafe_authority(self):
        mutations = [lambda r: r.update(execute=True), lambda r: r["changes"][0].update(field="ground_resistivity"),
                     lambda r: r["changes"].append(copy.deepcopy(r["changes"][0])), lambda r: r["assumptions"].update(ideally_transposed=False),
                     lambda r: r["source"].update(extra="unsafe"), lambda r: r["changes"][0].update(value=True),
                     lambda r: r["changes"][0].update(expected=True), lambda r: r["changes"][0].update(value=float("nan")),
                     lambda r: r["changes"][0].update(value=float("inf")), lambda r: r["changes"][0].update(value=-1),
                     lambda r: r["changes"][0].update(value=0), lambda r: r["changes"][0].update(value="20"),
                     lambda r: r.update(provenance=[]), lambda r: r["provenance"][0].update(source_sha256="f" * 64)]
        for mutate in mutations:
            req = request(); mutate(req)
            with self.subTest(req=req), self.assertRaises(ValueError): validate_line_request(req)
        req = request(); req["source"]["path"] = "x" * 100001
        with self.assertRaisesRegex(ValueError, "100,000"): validate_line_request(req)

    def test_preview_is_pure_deterministic_and_existing_output_is_never_reused(self):
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No I/O")), patch("socket.create_connection", side_effect=AssertionError("No native connection")):
            first = preview_line_input(RAW, request())
            self.assertEqual(first, preview_line_input(RAW, request()))
        report, _ = first
        self.assertTrue(report["regeneration_required"])
        self.assertFalse(report["existing_outputs_valid_for_preview"])
        self.assertFalse(report["assumptions_verified"])
        for key in ("companion_generated", "solver_called", "draft_created", "compile_called", "integration_qualified", "execution_authorized", "automatic_retry", "source_written"):
            self.assertFalse(report[key])
        self.assertEqual(report["engineering_verdict"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()

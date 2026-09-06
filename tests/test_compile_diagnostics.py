"""Authored diagnostic fixtures; no vendor logs, SDK or native execution."""
import test_environment
import copy
import hashlib
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rtds_agent.core.compile_diagnostics import API_EXCEPTION_FORMAT_ID, COMPILE_INCOMPLETE_MESSAGE, CORPUS_SCHEMA, FORMAT_ID, classify_compile_diagnostics, parse_compile_log, parser_catalog, validate_corpus
from rtds_agent.core.state_machine import sha256_json


def reference(raw, encoding="utf-8"):
    return {"path": "C:/synthetic/compile/errs.log", "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "encoding": encoding}


def parse(raw=b"Authored unknown diagnostic\n", encoding="utf-8", format_id=FORMAT_ID):
    return parse_compile_log(raw, reference(raw, encoding), format_id)


def corpus():
    ref = reference(b"Authored unknown diagnostic\n")
    return {"schema_version": "1.0", "corpus_id": "authored-fixture-v1", "description": "Synthetic unknown-text regression",
            "cases": [{"case_id": "unknown", "evidence_kind": "synthetic_authored", "format_id": FORMAT_ID,
                       "raw_ref": ref, "expectations": {"categories": ["unknown"], "component_mappings": ["unknown"], "parser_coverage": "partial"},
                       "provenance": [{"source_path": ref["path"], "source_sha256": ref["sha256"], "locator": "Authored synthetic fixture"}],
                       "sanitization": None, "limitations": ["Synthetic fixture is not installed native evidence"]}]}


class CompileParserTests(unittest.TestCase):
    def test_empty_and_whitespace_logs_never_infer_native_success(self):
        for raw in (b"", b" \r\n\t\n"):
            result = parse(raw)
            self.assertEqual(result["parser_coverage"], "empty")
            self.assertEqual(result["records"], [])
            self.assertEqual(result["native_outcome"], "not_evaluated")
            self.assertNotIn("complete", result)
            self.assertFalse(result["automatic_retry"])
            self.assertFalse(result["automatic_repair"])
            self.assertFalse(result["integration_qualified"])

    def test_unknown_negated_keywords_do_not_invent_native_classification(self):
        raw = b"No error in parameter voltage\nconnection runtime component definition success\nUUID=1 label=source\n"
        result = parse(raw)
        self.assertEqual(result["parser_coverage"], "partial")
        self.assertEqual(result["counts"]["unknown_records"], 3)
        self.assertTrue(all(row["category"] == row["severity"] == "unknown" for row in result["records"]))
        self.assertTrue(all(all(value is None for value in row["reported_identifiers"].values()) for row in result["records"]))

    def test_exact_observed_api_exception_classifies_only_generic_remote_failure(self):
        for ending in (b"", b"\n", b"\r\n"):
            raw = COMPILE_INCOMPLETE_MESSAGE.encode() + ending
            parsed = parse(raw, format_id=API_EXCEPTION_FORMAT_ID)
            self.assertEqual(parsed["parser_coverage"], "complete")
            self.assertEqual(parsed["counts"]["classified_records"], 1)
            row = classify_compile_diagnostics(parsed["records"], [], "a" * 64)[0]
            self.assertEqual(row["category"], "rscad_api")
            self.assertEqual(row["severity"], "error")
            self.assertEqual(row["reported_severity"], "unknown")
            self.assertEqual(row["component_mapping"], "unknown")
            self.assertIsNone(row["component_key"])
            self.assertIn("detailed compiler cause", row["reason"])
            self.assertEqual(len(row["parser_provenance"]), 2)
            self.assertEqual(row["native_outcome"], "not_evaluated")

    def test_exception_variants_wrong_format_and_mutation_labels_do_not_gain_categories(self):
        variants = [" " + COMPILE_INCOMPLETE_MESSAGE, COMPILE_INCOMPLETE_MESSAGE + " Source1", COMPILE_INCOMPLETE_MESSAGE.replace("failed", "did not fail"),
                    "parameter source_impedance_format failed", "connection resistor_detached failed"]
        for message in variants:
            row = parse(message.encode(), format_id=API_EXCEPTION_FORMAT_ID)["records"][0]
            self.assertEqual(row["category"], "unknown")
        row = parse(COMPILE_INCOMPLETE_MESSAGE.encode(), format_id=FORMAT_ID)["records"][0]
        self.assertEqual(row["category"], "unknown")
        parsed = parse((COMPILE_INCOMPLETE_MESSAGE + "\nUnknown follow-up\n").encode(), format_id=API_EXCEPTION_FORMAT_ID)
        self.assertEqual(parsed["parser_coverage"], "partial")
        self.assertEqual(parsed["counts"]["unknown_records"], 1)

    def test_offsets_line_hashes_and_raw_artifact_are_exact_with_bom_crlf(self):
        raw = b"\xef\xbb\xbf" + "First café\r\n\r\nSecond\n".encode()
        result = parse(raw, "utf-8-sig")
        self.assertEqual(result["records"][0]["message"], "First café")
        self.assertEqual(result["records"][1]["location"]["line_start"], 3)
        for row in result["records"]:
            loc = row["location"]
            self.assertEqual(hashlib.sha256(raw[loc["byte_start"]:loc["byte_end"]]).hexdigest(), row["raw_sha256"])
            self.assertEqual(row["source_hash"], hashlib.sha256(raw).hexdigest())

    def test_wrong_hash_size_unknown_encoding_and_nonbytes_are_refused(self):
        raw = b"Authored diagnostic"
        for change in ({"sha256": "0" * 64}, {"bytes": len(raw) + 1}, {"bytes": True}, {"encoding": "latin-1"}, {"trust": True}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_compile_log(raw, {**reference(raw), **change}, FORMAT_ID)
        with self.assertRaises(ValueError): parse_compile_log("text", reference(raw), FORMAT_ID)

    def test_invalid_encoding_stays_unsupported_without_replacement_decoding(self):
        result = parse(b"\xff ERROR source", "utf-8")
        self.assertEqual(result["decode_status"], "unsupported")
        self.assertEqual(result["parser_coverage"], "unsupported")
        self.assertEqual(result["records"], [])
        self.assertEqual(parse("café".encode(), "ascii")["decode_status"], "unsupported")

    def test_unknown_format_retains_nonblank_raw_lines(self):
        result = parse(b"Some message\n", format_id="unsupported-vendor-format")
        self.assertEqual(result["parser_coverage"], "unsupported")
        self.assertEqual(result["records"][0]["message"], "Some message")
        self.assertEqual(result["records"][0]["category"], "unknown")
        self.assertEqual(parse(b"", format_id="unsupported-vendor-format")["parser_coverage"], "unsupported")

    def test_oversize_line_record_bounds_and_message_truncation(self):
        for raw in (b"x" * (1048576 + 1), b"\n" * 20001, b"x\n" * 10001):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError): parse(raw)
        raw = b"x" * 5000
        row = parse(raw)["records"][0]
        self.assertTrue(row["message_truncated"])
        self.assertEqual(len(row["message"]), 4000)
        self.assertEqual(row["raw_sha256"], hashlib.sha256(raw).hexdigest())

    def test_record_identity_is_deterministic_and_pure(self):
        raw = b"same\nsame\n"
        ref = reference(raw)
        before = copy.deepcopy(ref)
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No source I/O")), patch("socket.create_connection", side_effect=AssertionError("No network")):
            first = parse_compile_log(raw, ref, FORMAT_ID)
            self.assertEqual(first, parse_compile_log(raw, ref, FORMAT_ID))
        self.assertEqual(ref, before)
        self.assertNotEqual(first["records"][0]["record_id"], first["records"][1]["record_id"])

    def test_component_labels_uuid_only_and_ambiguous_exact_identity_remain_unresolved(self):
        record = parse()["records"][0]
        components = [{"context": "subsystem:0", "uuid": 1, "component_type": "synthetic", "component_key": "component:first"},
                      {"context": "subsystem:1", "uuid": 1, "component_type": "synthetic", "component_key": "component:second"}]
        # These are explicitly authored structured identity fields, not extracted native grammar.
        for changes, expected in (({"component_label": "synthetic"}, "unknown"), ({"component_id": 1}, "unknown"),
                                  ({"context": "subsystem:0", "component_id": 1}, "exact_context_uuid"),
                                  ({"context": "subsystem:0", "component_id": 1, "component_type": "other"}, "unknown")):
            row = copy.deepcopy(record)
            row["reported_identifiers"].update(changes)
            row["record_id"] = sha256_json({key: value for key, value in row.items() if key != "record_id"})
            classified = classify_compile_diagnostics([row], components, "a" * 64)[0]
            self.assertEqual(classified["component_mapping"], expected)
        row = copy.deepcopy(record)
        row["reported_identifiers"].update(context="subsystem:0", component_id=1)
        row["record_id"] = sha256_json({key: value for key, value in row.items() if key != "record_id"})
        self.assertEqual(classify_compile_diagnostics([row], [components[0]] * 2, "a" * 64)[0]["component_mapping"], "ambiguous")

    def test_record_tampering_and_bad_snapshot_are_rejected(self):
        records = parse()["records"]
        records[0]["category"] = "parameter"
        with self.assertRaises(ValueError): classify_compile_diagnostics(records, [], "a" * 64)
        with self.assertRaises(ValueError): classify_compile_diagnostics([], [], "not-a-hash")


class CompileCorpusTests(unittest.TestCase):
    def test_strict_corpus_separates_raw_expected_output_and_provenance(self):
        Draft202012Validator.check_schema(CORPUS_SCHEMA)
        value = corpus()
        self.assertEqual(validate_corpus(value), value)
        self.assertEqual(set(parser_catalog()["taxonomy"]), {"model_structure", "parameter", "connection", "component_definition", "companion_file", "compile_resource", "rscad_api", "runtime", "unknown"})

    def test_forged_authority_unbound_raw_duplicate_ids_and_missing_redaction_lineage_fail(self):
        for mutate in (lambda c: c.update(integration_qualified=True),
                       lambda c: c["cases"].append(copy.deepcopy(c["cases"][0])),
                       lambda c: c["cases"][0]["raw_ref"].update(sha256="f" * 64),
                       lambda c: c["cases"][0]["expectations"].update(categories=["invented_category"]),
                       lambda c: c["cases"][0]["expectations"].update(component_mappings=[]),
                       lambda c: c["cases"][0].update(evidence_kind="sanitized_native_derivative")):
            value = corpus(); mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError): validate_corpus(value)


if __name__ == "__main__":
    unittest.main()

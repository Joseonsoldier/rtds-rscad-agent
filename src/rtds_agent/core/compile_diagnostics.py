"""Pure bounded parsing of supplied Compile logs; no native calls or inferred success."""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import re

from ..input_contracts import schema, validate
from .state_machine import sha256_json


CORPUS_SCHEMA = schema("compile_failure_corpus.schema.json")
PARSER_ID, PARSER_VERSION = "source_bound_compile_diagnostics", "1.0"
FORMAT_ID = "rscad_compile_errs_v1"
API_EXCEPTION_FORMAT_ID = "rscad_compile_api_exception_v1"
COMPILE_INCOMPLETE_MESSAGE = "rscad.library.RSCADException: Compile process failed to complete. See 'Compile Messages' tab for more details."
API_EXCEPTION_RULE_ID = "rscad_api_compile_incomplete_v1"
API_EXCEPTION_PROVENANCE = [
    {"corpus_case_id": "source_impedance_format_reviewed_02", "receipt_sha256": "dedfb21170ebc939c125fcad8e233084e17777e80d925a4e499a445594069743", "json_pointer": "/compile_exception/message", "evidence_kind": "task_scoped_native_api_observation"},
    {"corpus_case_id": "source_modulation_frequency", "receipt_sha256": "ba42a79c80cdb83d76cfc90ebb0db34e4d522b488a238fdb9ca4e6519c98a80f", "json_pointer": "/compile_exception/message", "evidence_kind": "task_scoped_native_api_observation"},
]
TAXONOMY = ("model_structure", "parameter", "connection", "component_definition", "companion_file", "compile_resource", "rscad_api", "runtime", "unknown")
MAX_LOG_BYTES, MAX_LINES, MAX_RECORDS = 1048576, 20000, 10000
FLAGS = {"automatic_retry": False, "automatic_repair": False, "integration_qualified": False,
         "native_outcome": "not_evaluated", "engineering_verdict": "not_evaluated"}
IDENTIFIER_KEYS = {"context", "component_id", "component_type", "component_label", "parameter"}
RECORD_KEYS = {"record_id", "record_kind", "message", "message_truncated", "severity", "reported_severity", "category",
               "classification_basis", "parser_rule_id", "reported_identifiers", "source_artifact", "source_hash", "location",
               "raw_sha256", "parser_provenance"}


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Invalid bounded " + label)
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Expected exact lowercase SHA-256 identity")
    return value


def _bounded_json(value, maximum):
    try:
        body = json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Diagnostic data must be finite bounded JSON") from exc
    if len(body) > maximum:
        raise ValueError("Diagnostic data exceeds its serialized byte bound")


def parser_catalog():
    return {"schema_version": "1.0", "parser_id": PARSER_ID, "parser_version": PARSER_VERSION,
            "formats": [{"format_id": FORMAT_ID, "encoding": ["utf-8", "utf-8-sig", "ascii"],
                         "coverage": "Empty saved error logs observed; nonempty native message grammar remains unsupported"},
                        {"format_id": API_EXCEPTION_FORMAT_ID, "encoding": ["utf-8", "utf-8-sig", "ascii"],
                         "coverage": "Exact generic SDK exception string extracted from a bound receipt; not a native log stream or full Compile Messages collection"}],
            "taxonomy": list(TAXONOMY), "rules": [{"parser_rule_id": API_EXCEPTION_RULE_ID, "format_id": API_EXCEPTION_FORMAT_ID,
                 "match": "Exact complete observed exception text only", "category": "rscad_api", "severity": "error",
                 "reason": "Remote Compile reported failure to complete; detailed compiler cause and component identity are unresolved.",
                 "provenance": copy.deepcopy(API_EXCEPTION_PROVENANCE)}],
            "limits": {"log_bytes": MAX_LOG_BYTES, "lines": MAX_LINES, "records": MAX_RECORDS},
            "limitations": ["Taxonomy membership is diagnostic categorization, not a root-cause or engineering verdict.",
                            "Collection completeness and Compile outcome belong to the separately bound execution receipt.",
                            "Unknown message text, labels and UUID-only tokens never establish exact component identity."], **FLAGS}


def validate_corpus(value):
    validate(value, CORPUS_SCHEMA)
    identities = set()
    total = 0
    for case in value["cases"]:
        if case["case_id"] in identities:
            raise ValueError("Duplicate corpus case identity")
        identities.add(case["case_id"])
        if type(case["raw_ref"]["bytes"]) is not int:
            raise ValueError("Corpus raw byte count must be an integer")
        total += case["raw_ref"]["bytes"]
        expected = case["expectations"]
        if len(expected["categories"]) != len(expected["component_mappings"]):
            raise ValueError("Corpus expected categories and mappings must describe the same records")
        if not any(ref["source_path"] == case["raw_ref"]["path"] and ref["source_sha256"] == case["raw_ref"]["sha256"] for ref in case["provenance"]):
            raise ValueError("Corpus provenance must pin its exact raw fixture path and hash")
        if case["sanitization"] is not None and case["sanitization"]["original_source_sha256"] == case["raw_ref"]["sha256"]:
            raise ValueError("Sanitized derivative must distinguish original and derivative bytes")
    if total > 4 * 1048576:
        raise ValueError("Corpus raw fixtures exceed 4 MiB aggregate")
    return value


def _record_id(record):
    return sha256_json({key: value for key, value in record.items() if key != "record_id"})


def parse_compile_log(raw: bytes, log_ref: dict, format_id: str):
    """Parse supplied bytes only. Unknown formats/text remain explicit raw evidence."""
    if not isinstance(raw, bytes) or len(raw) > MAX_LOG_BYTES:
        raise ValueError("Compile log exceeds 1 MiB or is not raw bytes")
    if not isinstance(log_ref, dict) or set(log_ref) != {"path", "sha256", "bytes", "encoding"}:
        raise ValueError("Compile log reference requires exact path, sha256, bytes and encoding")
    _text(log_ref["path"], "log source path")
    _text(format_id, "format ID", 160)
    if type(log_ref["bytes"]) is not int or log_ref["bytes"] != len(raw) or hashlib.sha256(raw).hexdigest() != _hash(log_ref["sha256"]):
        raise ValueError("Compile log bytes differ from their source hash or byte count")
    if log_ref["encoding"] not in {"utf-8", "utf-8-sig", "ascii"}:
        raise ValueError("Only explicitly declared UTF-8, UTF-8-SIG or ASCII encodings are supported")
    result = {"schema_version": "1.0", "parser_id": PARSER_ID, "parser_version": PARSER_VERSION, "format_id": format_id,
              "source": {key: log_ref[key] for key in ("path", "sha256", "bytes")}, "decode_status": "decoded",
              "parser_coverage": "unsupported", "records": [], "counts": {"lines": 0, "nonblank_lines": 0, "records": 0, "classified_records": 0, "unknown_records": 0},
              "limitations": copy.deepcopy(parser_catalog()["limitations"]), **FLAGS}
    try:
        raw.decode(log_ref["encoding"], errors="strict")
    except UnicodeError:
        result["decode_status"] = "unsupported"
        result["limitations"].append("Declared encoding cannot decode the source bytes; no replacement decoding or message inference was attempted.")
        return result
    # Split raw bytes to retain exact source offsets, including BOM and CRLF.
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        raise ValueError("Compile log exceeds 20000 raw lines")
    records, offset = [], 0
    for index, line in enumerate(lines):
        message = line.decode(log_ref["encoding"] if index == 0 else "ascii" if log_ref["encoding"] == "ascii" else "utf-8").rstrip("\r\n")
        if message.strip():
            if len(records) >= MAX_RECORDS:
                raise ValueError("Compile log exceeds 10000 nonblank records")
            record = {"record_kind": "unclassified", "message": message[:4000], "message_truncated": len(message) > 4000,
                      "severity": "unknown", "reported_severity": "unknown", "category": "unknown", "classification_basis": "unknown",
                      "parser_rule_id": "unrecognized_line", "reported_identifiers": {key: None for key in sorted(IDENTIFIER_KEYS)},
                      "source_artifact": log_ref["path"], "source_hash": log_ref["sha256"],
                      "location": {"line_start": index + 1, "line_end": index + 1, "byte_start": offset, "byte_end": offset + len(line)},
                      "raw_sha256": hashlib.sha256(line).hexdigest(), "parser_provenance": []}
            if format_id == API_EXCEPTION_FORMAT_ID and message == COMPILE_INCOMPLETE_MESSAGE:
                record.update(record_kind="diagnostic", severity="error", category="rscad_api",
                              classification_basis="observed_api_exception", parser_rule_id=API_EXCEPTION_RULE_ID,
                              parser_provenance=copy.deepcopy(API_EXCEPTION_PROVENANCE))
            record["record_id"] = _record_id(record)
            records.append(record)
        offset += len(line)
    result["records"] = records
    categories = Counter(row["category"] for row in records)
    result["counts"].update(lines=len(lines), nonblank_lines=len(records), records=len(records),
                            classified_records=len(records) - categories["unknown"], unknown_records=categories["unknown"])
    result["parser_coverage"] = "partial" if categories["unknown"] else "complete" if records else "empty"
    if format_id not in {FORMAT_ID, API_EXCEPTION_FORMAT_ID}:
        result["parser_coverage"] = "unsupported"
        result["limitations"].append("Format ID is not supported; decoded nonblank lines are retained as unknown records only.")
    _bounded_json(result, 8 * 1048576)
    return result


def classify_compile_diagnostics(records, components, snapshot_id):
    """Map only explicit unambiguous context+UUID evidence; never labels or UUID alone."""
    _hash(snapshot_id)
    if not isinstance(records, list) or len(records) > MAX_RECORDS or not isinstance(components, list) or len(components) > 5000:
        raise ValueError("Diagnostic classification exceeds its record/component bounds")
    _bounded_json(records, 8 * 1048576)
    _bounded_json(components, 20 * 1048576)
    result = []
    for record in records:
        if not isinstance(record, dict) or set(record) != RECORD_KEYS or record.get("record_id") != _record_id(record):
            raise ValueError("Diagnostic record identity or strict shape is invalid")
        if record["category"] not in TAXONOMY or not isinstance(record["reported_identifiers"], dict) or set(record["reported_identifiers"]) != IDENTIFIER_KEYS:
            raise ValueError("Diagnostic taxonomy or reported identity shape is invalid")
        reported = record["reported_identifiers"]
        context, uuid = reported["context"], reported["component_id"]
        matches = [component for component in components if isinstance(context, str) and type(uuid) is int
                   and component.get("context") == context and component.get("uuid") == uuid
                   and (reported["component_type"] is None or component.get("component_type") == reported["component_type"])]
        exact = len(matches) == 1 and isinstance(matches[0].get("component_key"), str) and bool(matches[0]["component_key"])
        row = copy.deepcopy(record)
        category_reason = "Remote Compile reported failure to complete; detailed compiler cause and component identity are unresolved." if record["parser_rule_id"] == API_EXCEPTION_RULE_ID else "No supported source-backed native signature establishes a specific failure category."
        row.update(component_mapping="exact_context_uuid" if exact else "ambiguous" if len(matches) > 1 else "unknown",
                   component_key=matches[0]["component_key"] if exact else None,
                   mapping_snapshot_id=snapshot_id if exact else None,
                   confidence="category_only" if record["category"] != "unknown" else "unresolved",
                   reason=category_reason,
                   component_mapping_reason="Only an explicit context and UUID uniquely identify a model component; labels and partial identifiers remain unresolved.", **FLAGS)
        result.append(row)
    return result

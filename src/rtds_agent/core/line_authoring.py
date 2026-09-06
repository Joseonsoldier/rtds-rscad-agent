"""Narrow source-bound scalar TLI inspection and byte-preserving in-memory preview."""
from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re

from ..input_contracts import schema, validate
from .state_machine import sha256_json


LINE_AUTHORING_SCHEMA = schema("line_authoring_request.schema.json")
PROFILE_ID = "tline_rlc_3phase_ohmic_v1"
MAX_BYTES, MAX_LINES = 65536, 1024
FIELD_DEFINITIONS = {
    "line_length_km": ("Line Summary", "Line Length", "km"),
    "frequency_hz": ("Line Summary", "Steady State Frequency", "Hz"),
    "r_positive_ohm_per_km": ("RLC Options", "Positive Sequence Series Resistance", "ohm/km"),
    "r_zero_ohm_per_km": ("RLC Options", "Zero Sequence Series Resistance", "ohm/km"),
    "x_positive_ohm_per_km": ("RLC Options", "Positive Sequence Series Ind Reactance", "ohm/km"),
    "x_zero_ohm_per_km": ("RLC Options", "Zero Sequence Series Ind Reactance", "ohm/km"),
    "xc_positive_megohm_km": ("RLC Options", "Positive Sequence Series Cap Reactance", "megohm*km"),
    "xc_zero_megohm_km": ("RLC Options", "Zero Sequence Series Cap Reactance", "megohm*km"),
}
PRESERVED_DEFINITIONS = {
    "ground_resistivity": ("Line Constants Ground Data", "GroundResistivity", "ohm*m"),
    "data_entry_format": ("RLC Options", "Data Entry Format", "literal_selector"),
    "number_of_phases": ("RLC Options", "Number of Phases", "count"),
}
BLOCKS = ("Line Summary", "Line Constants Ground Data", "RLC Options")
NUMERIC = rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
ASSIGNMENT = re.compile(rb"[ \t]*(?P<key>[A-Za-z][A-Za-z ]*?)[ \t]*=[ \t]*(?P<value>" + NUMERIC + rb")[ \t]*")
FLAGS = {"companion_generated": False, "solver_called": False, "draft_created": False, "compile_called": False,
         "integration_qualified": False, "engineering_verdict": "not_evaluated", "execution_authorized": False,
         "automatic_retry": False, "source_written": False}


def line_authoring_catalog():
    return {"schema_version": "1.0", "profile_id": PROFILE_ID, "status": "observed_file_profile",
            "observed_profile_sha256": "151e4a41a5ad0c191b7836f51d484180e9e9465b72c81d0f9abdfcd695e620bc",
            "manual_evidence": {"source_id": "TLINEEDIT/tline_constants_manual.pdf", "source_sha256": "5a19071f514ec365d0401d1f0ed8e46b658590b56011fd125282d01970314cfc",
                                "pages": [8, 23, 24, 25, 26, 36]},
            "installed_source_evidence": {"source_id": "BIN/rscad_fx.jar", "source_sha256": "f715cccd6f81e0cb028d55bebc80f4b73706d491cb3374eb43f6c3ccee23ba27",
                                          "locators": ["TLITLineParser.parseOptionsRLC: Data Entry Format routes through TLRLCData.setDataEntry(int)",
                                                       "RLCDialog: ohms option key 0 and per unit option key 1 use the same setDataEntry setter",
                                                       "RLCDialog: metric labels use km, ohm/km and megohm*km; six RLC fields use setMinExclusiveValue(0)"],
                                          "evidence_level": "read_only_installed_class_inspection", "vendor_code_executed": False},
            "editable_fields": {key: {"block": block, "source_key": source_key, "units": units,
                                      "preview_domain": "positive"}
                                for key, (block, source_key, units) in FIELD_DEFINITIONS.items()},
            "profile_constants": {"data_entry_format": 0, "number_of_phases": 3},
            "scope": "Exact observed scalar .tli shape only, under declared ideally transposed frequency-independent Bergeron assumptions; no installation or solver qualification.",
            "limitations": ["The six RLC inputs follow this inspected editor's strictly positive field domain; this does not establish a general physical restriction on zero-resistance models.",
                            "The saved Cap Reactance key includes Series; the manual identifies this entered quantity as shunt capacitive reactance. No topology inference is made from the key spelling.",
                            "GroundResistivity is preserved; its effect on directly supplied sequence data is not evaluated.",
                            "Changing frequency does not automatically rescale supplied inductive or capacitive reactance; the caller supplies a coherent revised specification.",
                            "Geometry, cable, per-unit, six-phase, revision-marked and additional-field profiles are unsupported.",
                            "Any existing .tlo or other line-constants output must be regenerated for changed input; this preview does not generate or validate those outputs."], **FLAGS}


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_line_request(request):
    validate(request, LINE_AUTHORING_SCHEMA)
    fields = set()
    for change in request["changes"]:
        if change["field"] in fields:
            raise ValueError("Duplicate line preview field")
        fields.add(change["field"])
        if not _finite(change["expected"]) or not _finite(change["value"]):
            raise ValueError("Line preview values must be finite numbers, not booleans")
        if Decimal(str(change["expected"])) == Decimal(str(change["value"])):
            raise ValueError("Line preview changes must not be no-ops")
    refs = request["provenance"]
    if len({(row["source_path"], row["source_sha256"], row["locator"]) for row in refs}) != len(refs):
        raise ValueError("Duplicate line preview provenance reference")
    if not any(row["source_path"] == request["source"]["path"] and row["source_sha256"] == request["source"]["sha256"] for row in refs):
        raise ValueError("Line preview provenance must pin the exact source path and hash")
    return request


def inspect_line_input(raw: bytes, profile_id: str = PROFILE_ID):
    if not isinstance(raw, bytes):
        raise ValueError("TLI inspection requires supplied raw bytes")
    result = {"schema_version": "1.0", "profile_id": profile_id, "status": "unsupported",
              "source_sha256": hashlib.sha256(raw).hexdigest(), "source_bytes": len(raw), "fields": {}, "preserved": {},
              "reasons": [], "limitations": copy.deepcopy(line_authoring_catalog()["limitations"]), **FLAGS}

    def unsupported(reason):
        result["reasons"].append(reason)
        return result

    if profile_id != PROFILE_ID:
        return unsupported("Unsupported line input profile identifier")
    if len(raw) > MAX_BYTES:
        return unsupported("TLI input exceeds 64 KiB")
    if any(byte not in (9, 10, 13) and not 32 <= byte <= 126 for byte in raw):
        return unsupported("Only the observed ASCII scalar profile without BOM or control bytes is supported")
    lines = raw.splitlines(keepends=True)
    if len(lines) > MAX_LINES:
        return unsupported("TLI input exceeds 1024 lines")
    definitions = {**FIELD_DEFINITIONS, **PRESERVED_DEFINITIONS}
    by_key = {(block, key): canonical for canonical, (block, key, _) in definitions.items()}
    found, seen_blocks, active, pending, offset = {}, set(), None, None, 0
    for index, line in enumerate(lines):
        body = line.rstrip(b"\r\n")
        stripped = body.strip(b" \t")
        if not stripped:
            offset += len(line)
            continue
        if pending is not None:
            if stripped != b"{":
                return unsupported(f"Expected block opening brace at line {index + 1}")
            active, pending = pending, None
        elif active is None:
            if not stripped.endswith(b":"):
                return unsupported(f"Unsupported content outside an exact known block at line {index + 1}")
            name = stripped[:-1].decode("ascii")
            if name not in BLOCKS or name in seen_blocks:
                return unsupported(f"Unknown or duplicate block at line {index + 1}: {name}")
            if name != BLOCKS[len(seen_blocks)]:
                return unsupported("Block ordering differs from the observed scalar profile")
            seen_blocks.add(name)
            pending = name
        elif stripped == b"}":
            active = None
        else:
            match = ASSIGNMENT.fullmatch(body)
            if match is None:
                return unsupported(f"Unsupported scalar assignment at line {index + 1}")
            key = match["key"].decode("ascii").rstrip(" ")
            canonical = by_key.get((active, key))
            if canonical is None or canonical in found:
                return unsupported(f"Unknown, misplaced or duplicate field at line {index + 1}: {key}")
            token = match["value"].decode("ascii")
            try:
                exact = Decimal(token)
                numeric = float(token)
            except (ValueError, InvalidOperation, OverflowError):
                return unsupported(f"Unsupported numeric token at line {index + 1}")
            if not math.isfinite(numeric) or (numeric == 0 and exact != 0):
                return unsupported(f"Nonfinite or underflowing scalar at line {index + 1}")
            if canonical in FIELD_DEFINITIONS and exact <= 0:
                return unsupported(f"Value outside narrow preview input domain: {canonical}")
            if canonical in {"data_entry_format", "number_of_phases"} and token != ("0" if canonical == "data_entry_format" else "3"):
                return unsupported(f"Profile selector requires the exact observed integer token: {canonical}")
            if canonical == "data_entry_format" and exact != 0:
                return unsupported("Only observed Data Entry Format 0 is supported; per-unit input is unsupported")
            if canonical == "number_of_phases" and exact != 3:
                return unsupported("Only the observed three-phase scalar profile is supported")
            found[canonical] = {"value": numeric, "raw_value": token, "units": definitions[canonical][2], "source_key": key,
                                "block": active, "line": index + 1, "byte_start": offset + match.start("value"), "byte_end": offset + match.end("value")}
        offset += len(line)
    if active is not None or pending is not None:
        return unsupported("Unclosed scalar block")
    if seen_blocks != set(BLOCKS) or set(found) != set(definitions):
        return unsupported("The exact observed block and scalar field set is incomplete")
    result.update(status="supported", fields={key: found[key] for key in FIELD_DEFINITIONS},
                  preserved={key: found[key] for key in PRESERVED_DEFINITIONS})
    return result


def preview_line_input(raw: bytes, request: dict):
    validate_line_request(request)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != request["source"]["sha256"]:
        raise ValueError("TLI preview source hash differs from the request")
    before = inspect_line_input(raw, request["profile_id"])
    if before["status"] != "supported":
        raise ValueError("Unsupported TLI preview input: " + "; ".join(before["reasons"]))
    edits = []
    for change in request["changes"]:
        row = before["fields"][change["field"]]
        if Decimal(row["raw_value"]) != Decimal(str(change["expected"])):
            raise ValueError("Expected line field differs from its exact saved scalar: " + change["field"])
        token = json.dumps(change["value"], allow_nan=False).encode("ascii")
        edits.append({"field": change["field"], "source_byte_start": row["byte_start"], "source_byte_end": row["byte_end"],
                      "old_token": row["raw_value"], "new_token": token.decode("ascii"), "expected": change["expected"], "value": change["value"]})
    edits.sort(key=lambda edit: edit["source_byte_start"])
    candidate, cursor = bytearray(), 0
    for edit in edits:
        candidate.extend(raw[cursor:edit["source_byte_start"]])
        edit["candidate_byte_start"] = len(candidate)
        candidate.extend(edit["new_token"].encode("ascii"))
        edit["candidate_byte_end"] = len(candidate)
        cursor = edit["source_byte_end"]
    candidate.extend(raw[cursor:])
    candidate = bytes(candidate)
    after = inspect_line_input(candidate, request["profile_id"])
    if after["status"] != "supported":
        raise ValueError("Candidate is outside the bounded supported profile")
    requested = {change["field"]: Decimal(str(change["value"])) for change in request["changes"]}
    for field in FIELD_DEFINITIONS:
        expected = requested.get(field, Decimal(before["fields"][field]["raw_value"]))
        if Decimal(after["fields"][field]["raw_value"]) != expected:
            raise ValueError("Exact candidate scalar readback differs")
    for field in PRESERVED_DEFINITIONS:
        if after["preserved"][field]["raw_value"] != before["preserved"][field]["raw_value"]:
            raise ValueError("Preserved profile selector or ground data changed")
    report = {"schema_version": "1.0", "profile_id": PROFILE_ID, "status": "preview_only", "source": copy.deepcopy(request["source"]),
              "request_sha256": sha256_json(request), "source_sha256": before["source_sha256"], "candidate_sha256": after["source_sha256"],
              "candidate_bytes": len(candidate), "changes": edits, "before": before, "after": after,
              "provenance": copy.deepcopy(request["provenance"]), "assumptions": copy.deepcopy(request["assumptions"]),
              "assumptions_verified": False, "only_requested_numeric_tokens_changed": True,
              "regeneration_required": True, "existing_outputs_valid_for_preview": False,
              "next_step": "Regenerate line constants using a separately supported and authorized vendor workflow; an existing .tlo is not evidence for this changed input.", **FLAGS}
    report["preview_id"] = sha256_json(report)
    return report, candidate

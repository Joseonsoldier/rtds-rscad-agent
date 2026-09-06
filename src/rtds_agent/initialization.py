"""Read-only load-flow preconditions and hash-bound supplied initialization evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any
import zipfile

from pydantic import BeforeValidator, WithJsonSchema

from .core.loadflow_initialization import (
    INITIALIZATION_SCHEMA, check_preconditions, evaluate_supplied, plan_sha256,
    validate_initialization, validate_supplied,
)
from .core.state_machine import sha256_json
from .core.structured_patch import patch_dfx
from .core.topology_parser import parse_parameter_schema
from .project_tools import _document
from .safety import ToolSafetyError, checked_file, resolve_rtfx_path, sha256_file
from .settings import get_settings


def _annotation_schema(value, resolving=()):
    """Inline local references for Pydantic/MCP, retaining the packaged contract."""
    if isinstance(value, list):
        return [_annotation_schema(item, resolving) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/$defs/") or reference in resolving:
            raise ValueError("Unsupported initialization annotation reference")
        target = INITIALIZATION_SCHEMA["$defs"][reference.removeprefix("#/$defs/")]
        expanded = _annotation_schema(target, (*resolving, reference))
        siblings = {key: item for key, item in value.items() if key != "$ref"}
        return {"allOf": [expanded, _annotation_schema(siblings, resolving)]} if siblings else expanded
    return {key: _annotation_schema(item, resolving) for key, item in value.items() if key not in {"$defs", "$id"}}


InitializationRequest = Annotated[dict, BeforeValidator(validate_initialization), WithJsonSchema(_annotation_schema(INITIALIZATION_SCHEMA))]
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024


def _archive(path):
    if path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ToolSafetyError("Initialization RTFX exceeds 20 MiB")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if not 1 <= len(names) <= 256 or len(set(names)) != len(names) or any(len(name) > 1000 for name in names):
            raise ToolSafetyError("Initialization archive has duplicate, oversized, or too many member identities")
        if sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES:
            raise ToolSafetyError("Initialization expanded archive exceeds 20 MiB")
        dfx = [name for name in names if name.lower().endswith(".dfx")]
        if len(dfx) != 1:
            raise ToolSafetyError("Initialization archive requires one exact DFX member")
        raw = {name: archive.read(name) for name in names}
        if sum(map(len, raw.values())) > MAX_ARCHIVE_BYTES:
            raise ToolSafetyError("Initialization expanded archive exceeds 20 MiB")
        metadata = {"members": names, "dfx_member": dfx[0],
                    "member_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()},
                    "archive_comment_sha256": hashlib.sha256(archive.comment).hexdigest()}
        return metadata, raw[dfx[0]]


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            raise ToolSafetyError("Duplicate key in supplied initialization JSON")
        result[key] = value
    return result


def _supplied(path, digest):
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise ToolSafetyError("Supplied initialization artifact exceeds 1 MiB")
    raw = path.read_bytes()
    if len(raw) > MAX_EVIDENCE_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ToolSafetyError("Supplied initialization artifact size/hash mismatch")
    try:
        result = json.loads(raw, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ToolSafetyError("Unsupported supplied initialization JSON") from exc
    validate_supplied(result)
    return result


def _archive_comparison(before, after, before_dfx, after_dfx, changes):
    dfx_name = before["dfx_member"]
    same_non_dfx = (before["members"] == after["members"] and dfx_name == after["dfx_member"]
                    and before["archive_comment_sha256"] == after["archive_comment_sha256"]
                    and {k: v for k, v in before["member_sha256"].items() if k != dfx_name}
                    == {k: v for k, v in after["member_sha256"].items() if k != after["dfx_member"]})
    # Mask only the exact reported stored values on both sides, retaining all
    # other DFX bytes. A semantic diff alone cannot protect unparsed records.
    operations = [{"context": row["context"], "component_id": row["component_id"],
                   "component_type": row["component_type"], "parameter": row["parameter"],
                   "expected_old_value": row["before_value"], "new_value": "0"} for row in changes]
    reason = None
    try:
        first = patch_dfx(before_dfx, operations)[0] if changes else before_dfx
        after_operations = [{**operation, "expected_old_value": row["after_value"]} for operation, row in zip(operations, changes)]
        second = patch_dfx(after_dfx, after_operations)[0] if changes else after_dfx
        accounted = first == second
    except (ValueError, KeyError, TypeError) as exc:
        accounted, reason = False, str(exc)[:1000]
    return {"non_dfx_unchanged": same_non_dfx, "dfx_changes_fully_accounted": accounted,
            "dfx_comparison_method": "exact_bytes_after_masking_declared_stored_parameter_values",
            "dfx_comparison_error": reason, "before_archive": before, "after_archive": after}


def _companion_identity(evidence):
    # Isolated copies have different absolute paths. Preserve the exact relative
    # dependency identity/content and referring component/parameter identities.
    result = {key: evidence.get(key) for key in ("status", "missing", "blocked", "definition_errors")}
    result["files"] = [{key: row[key] for key in ("relative_path", "sha256", "bytes", "referenced_by")}
                       for row in evidence.get("files", [])]
    return result


def _raw_binding_check(request, document, dfx):
    components = {(row["context"], row["uuid"]): row for row in document["components"]}
    operations, seen = [], set()
    for entity in request["entities"]:
        component = components.get((entity["context"], entity["component_id"]))
        if component is None or component["component_type"] != entity["component_type"]:
            continue  # The semantic precondition check records missing identities.
        for binding in entity["parameter_bindings"]:
            for field in ("parameter", "calculated_parameter"):
                parameter = binding[field]
                key = (entity["context"], entity["component_id"], parameter)
                if key in seen or parameter not in component["parameters"]:
                    continue
                seen.add(key)
                value = component["parameters"][parameter]
                operations.append({"context": entity["context"], "component_id": entity["component_id"],
                                   "component_type": entity["component_type"], "parameter": parameter,
                                   "expected_old_value": value, "new_value": value})
    try:
        # In-memory only. This checks exact raw occurrence count even when a
        # duplicate stored line was collapsed by the static parser dictionary.
        if operations:
            patch_dfx(dfx, operations)
    except (ValueError, KeyError, TypeError):
        return "bound_parameter_raw_occurrence_not_unique_or_unsupported"
    return None


def inspect_initialization(project_path: str, snapshot_id: str | None, request: InitializationRequest) -> dict[str, Any]:
    """Inspect supplied models/evidence; never call a solver, backend, or write a file."""
    validate_initialization(request)
    settings = get_settings()
    before_path, _ = resolve_rtfx_path(project_path)
    before_archive, before_dfx = _archive(before_path)
    _, scope, before = _document(str(before_path), snapshot_id)
    if before["source"]["rtfx_sha256"] != request["input_project_sha256"]:
        raise ToolSafetyError("Initialization input model hash mismatch")
    provenance = []
    for reference in request["provenance"]:
        path = checked_file(reference["source_path"], (*settings.document_roots, *settings.source_roots, settings.data_dir))
        if path.stat().st_size > 64 * 1024 * 1024 or sha256_file(path) != reference["source_sha256"]:
            raise ToolSafetyError("Initialization provenance size/hash mismatch")
        provenance.append({**reference, "source_path": str(path), "semantics_independently_verified": False})
    from .model_check import check_document
    static = check_document(before)
    definition_schemas = {}
    for kind in {entity["component_type"] for entity in request["entities"]}:
        reference = before.get("definition_evidence", {}).get(kind)
        if reference is None:
            continue
        definition_path = checked_file(reference["path"], (settings.definition_root,))
        if definition_path.stat().st_size > 2 * 1024 * 1024:
            raise ToolSafetyError("Initialization parameter definition exceeds 2 MiB")
        raw_definition = definition_path.read_bytes()
        if hashlib.sha256(raw_definition).hexdigest() != reference["sha256"]:
            raise ToolSafetyError("Initialization parameter definition changed")
        definition_schemas[kind] = parse_parameter_schema(raw_definition.decode("utf-8-sig"))
    preconditions = check_preconditions(request, before, static, definition_schemas)
    raw_problem = _raw_binding_check(request, before, before_dfx)
    if raw_problem:
        preconditions["status"] = "blocked"
        preconditions["reasons"].append(raw_problem)
    report = {"schema_version": "1.0", "mode": request["mode"],
              "status": "preconditions_checked" if preconditions["status"] == "checked" else "blocked",
              "initialization_plan_sha256": plan_sha256(request), "input_project": str(before_path),
              "input_project_sha256": request["input_project_sha256"], "snapshot_id": before["snapshot_id"],
              "access_scope": scope, "preconditions": preconditions, "provenance": provenance,
              "supplied_evidence": None, "engineering_verdict": "not_evaluated", "integration_qualified": False,
              "live_calls_made": False, "loadflow_called": False, "compile_called": False,
              "runtime_called": False, "rack_query_called": False, "mutations_performed": False,
              "execution_authorized": False,
              "limitations": ["This is a partial offline WP-N06 evidence workflow, not a live load-flow adapter.",
                              "Roles, quantity mappings and convergence are supplied declarations, not independently verified electrical semantics.",
                              "Only existing explicitly bound numeric parameters may explain initialization changes; all other saved-model changes block consistency.",
                              "No unit conversion, solver execution, arbitrary expressions, or automatic model repair is performed.",
                              "A consistent receipt does not grant Compile/Runtime permission or establish convergence, stability, or hardware readiness."]}
    after_path = data_path = None
    after = None
    if request["mode"] == "supplied_evidence":
        reference = request["evidence"]
        data_path = checked_file(reference["data_path"], (*settings.source_roots, settings.data_dir), ".json")
        supplied = _supplied(data_path, reference["data_sha256"])
        after_path, _ = resolve_rtfx_path(reference["after_project"])
        after_archive, after_dfx = _archive(after_path)
        _, _, after = _document(str(after_path), reference["after_snapshot_id"])
        if after["source"]["rtfx_sha256"] != reference["after_project_sha256"]:
            raise ToolSafetyError("Initialization after-model hash mismatch")
        archive_evidence = _archive_comparison(before_archive, after_archive, before_dfx, after_dfx, supplied["parameter_changes"])
        first_evidence, second_evidence = before["snapshot"]["evidence"], after["snapshot"]["evidence"]
        archive_evidence["same_definition_and_companion_evidence"] = (
            first_evidence["definitions"] == second_evidence["definitions"]
            and _companion_identity(first_evidence["companions"]) == _companion_identity(second_evidence["companions"]))
        evidence = evaluate_supplied(request, supplied, before, after, archive_evidence)
        after_static = check_document(after)
        evidence["after_static_model_check_status"] = after_static["status"]
        if after_static["status"] != "no_errors_in_checked_scope":
            evidence["status"] = "inconsistent"
            evidence["reasons"].append("after_static_model_check_has_errors")
        evidence.update(data_path=str(data_path), data_sha256=reference["data_sha256"], after_project=str(after_path),
                        after_project_sha256=reference["after_project_sha256"], after_snapshot_id=after["snapshot_id"])
        report["supplied_evidence"] = evidence
        report["status"] = "consistent_supplied_evidence" if preconditions["status"] == "checked" and evidence["status"] == "consistent" else "blocked"
    # Refresh every mutable model/dependency/provenance/configuration binding.
    _document(str(before_path), before["snapshot_id"])
    if _archive(before_path) != (before_archive, before_dfx):
        raise ToolSafetyError("Initialization input archive changed while checking")
    if after_path is not None:
        _document(str(after_path), after["snapshot_id"])
        if _archive(after_path) != (after_archive, after_dfx) or sha256_file(data_path) != request["evidence"]["data_sha256"]:
            raise ToolSafetyError("Supplied initialization models or artifact changed while checking")
    if get_settings() != settings or any(sha256_file(Path(row["source_path"])) != row["source_sha256"] for row in provenance):
        raise ToolSafetyError("Initialization provenance or settings changed while checking")
    report["report_sha256"] = sha256_json(report)
    return report

"""Hash-bound structured parameter patches for RSCAD FX working copies."""

from __future__ import annotations

import copy
import codecs
import hashlib
import json
import math
import os
import re
import secrets
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


from rtds_agent.settings import get_settings

from rtds_agent.safety import ToolSafetyError, is_within, resolve_rtfx_path, sha256_file
from rtds_agent.core.topology_parser import parse_dfx_components, parse_rtfx_topology


SUPPORTED_DATA_TYPES = {"REAL", "INTEGER"}
MAX_OPERATIONS = 20


class PatchSafetyError(ToolSafetyError):
    """Raised before an unsafe or ungrounded RTFX edit is committed."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(encoded)


def safe_label(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    if not result or len(result) > 80:
        raise PatchSafetyError("project_label must produce 1 through 80 safe characters")
    return result


def file_record(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def read_parameter_audit(parameter_catalog_snapshot_id: str | None = None) -> tuple[dict[str, Any], str]:
    from .parameter_catalog import read_audit
    try:
        return read_audit(parameter_catalog_snapshot_id)
    except ToolSafetyError as exc:
        raise PatchSafetyError(str(exc)) from exc


def parameter_schema(
    component_type: str,
    parameter: str,
    rscad_version: str,
    parameter_catalog_snapshot_id: str | None = None,
) -> dict[str, Any]:
    from .parameter_catalog import lookup
    try:
        return lookup(component_type, parameter, rscad_version, parameter_catalog_snapshot_id)
    except ToolSafetyError as exc:
        raise PatchSafetyError(str(exc)) from exc


def validate_new_value(schema: dict[str, Any], new_value: str) -> dict[str, Any]:
    if not isinstance(new_value, str) or not new_value:
        raise PatchSafetyError("new_value must be a non-empty string")
    if any(character in new_value for character in ("\x00", "\r", "\n")):
        raise PatchSafetyError("new_value may not contain null bytes or newlines")
    if len(new_value) > 500:
        raise PatchSafetyError("new_value exceeds 500 characters")
    data_type = str(schema["data_type"]).upper()
    if data_type not in SUPPORTED_DATA_TYPES:
        raise PatchSafetyError(
            f"data type {data_type} is not enabled for automatic parameter patches"
        )
    if data_type == "INTEGER":
        if re.fullmatch(r"[+-]?\d+", new_value) is None:
            raise PatchSafetyError("INTEGER parameter requires a base-10 integer")
        numeric: float | int = int(new_value)
    else:
        try:
            numeric = float(new_value)
        except ValueError as exc:
            raise PatchSafetyError("REAL parameter requires a finite number") from exc
        if not math.isfinite(numeric):
            raise PatchSafetyError("REAL parameter requires a finite number")
    minimum, maximum = schema.get("minimum"), schema.get("maximum")
    if minimum is not None and numeric < minimum:
        raise PatchSafetyError(f"new_value is below audited minimum {minimum}")
    if maximum is not None and numeric > maximum:
        raise PatchSafetyError(f"new_value is above audited maximum {maximum}")
    return {
        "data_type": data_type,
        "numeric_value": numeric,
        "minimum": minimum,
        "maximum": maximum,
        "unit": schema.get("unit"),
    }


def archive_snapshot(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path, "r") as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            raise PatchSafetyError("RTFX archive contains duplicate member names")
        dfx_names = [name for name in names if name.casefold().endswith(".dfx")]
        if len(dfx_names) != 1:
            raise PatchSafetyError(f"RTFX must contain exactly one DFX member: {dfx_names}")
        hashes = {name: sha256_bytes(archive.read(name)) for name in names}
        return {
            "members": names,
            "member_sha256": hashes,
            "dfx_member": dfx_names[0],
            "archive_comment_sha256": sha256_bytes(archive.comment),
        }


def dfx_components(data: bytes) -> tuple[str, bool, list[dict[str, Any]]]:
    had_bom = data.startswith(codecs.BOM_UTF8)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PatchSafetyError("DFX member is not valid UTF-8/UTF-8-SIG") from exc
    return text, had_bom, parse_dfx_components(text)


def component_blocks(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    lines = text.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines)
        if line.startswith("COMPONENT_TYPE=")
    ]
    ranges = [
        (start, starts[index + 1] if index + 1 < len(starts) else len(lines))
        for index, start in enumerate(starts)
    ]
    return lines, ranges


def normalize_request(request: dict[str, Any]) -> dict[str, Any]:
    from rtds_agent.input_contracts import validate_patch
    validate_patch(request)
    if not isinstance(request, dict):
        raise PatchSafetyError("patch request must be an object")
    if request.get("schema_version") != "1.0":
        raise PatchSafetyError("patch schema_version must be 1.0")
    source_value = request.get("source_project")
    if not isinstance(source_value, str):
        raise PatchSafetyError("source_project must be a string")
    source, source_scope = resolve_rtfx_path(source_value)
    source_hash = sha256_file(source)
    expected_source_hash = request.get("source_sha256")
    if expected_source_hash != source_hash:
        raise PatchSafetyError("source_project hash differs from patch request")
    version = request.get("rscad_version")
    if version != "2.7.3":
        raise PatchSafetyError("automatic parameter patches currently require RSCAD FX 2.7.3")
    operations = request.get("operations")
    if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
        raise PatchSafetyError("operations must contain 1 through 20 entries")
    normalized_operations = []
    identities = set()
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("op") != "set_parameter":
            raise PatchSafetyError(f"operations[{index}] must be set_parameter")
        component_id = operation.get("component_id")
        if not isinstance(component_id, int) or isinstance(component_id, bool) or component_id < 0:
            raise PatchSafetyError(f"operations[{index}].component_id must be non-negative integer")
        component_type = operation.get("component_type")
        parameter = operation.get("parameter")
        expected_old_value = operation.get("expected_old_value")
        new_value = operation.get("new_value")
        context = operation.get("context")
        for field, value in (
            ("component_type", component_type),
            ("parameter", parameter),
            ("expected_old_value", expected_old_value),
            ("new_value", new_value),
        ):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise PatchSafetyError(f"operations[{index}].{field} must be non-empty string")
        if context is not None and (not isinstance(context, str) or not context):
            raise PatchSafetyError(f"operations[{index}].context must be null or non-empty string")
        identity = (component_id, context, parameter.casefold())
        if identity in identities:
            raise PatchSafetyError("duplicate component/context/parameter operation")
        identities.add(identity)
        schema = parameter_schema(component_type, parameter, version, request.get("parameter_catalog_snapshot_id"))
        value_validation = validate_new_value(schema, new_value)
        if expected_old_value == new_value:
            raise PatchSafetyError("new_value must differ from expected_old_value")
        normalized_operations.append(
            {
                "op": "set_parameter",
                "component_id": component_id,
                "context": context,
                "component_type": component_type,
                "parameter": parameter,
                "expected_old_value": expected_old_value,
                "new_value": new_value,
                "schema_evidence": {
                    key: schema.get(key)
                    for key in (
                        "rscad_version",
                        "data_type",
                        "unit",
                        "minimum",
                        "maximum",
                        "description",
                        "definition_path",
                        "definition_sha256",
                        "verification_status",
                        "parameter_database_sha256",
                        "parameter_audit_path",
                        "parameter_audit_sha256",
                        "parameter_catalog_snapshot_id",
                        "library_identity",
                        "rscad_version_evidence",
                        "api_version_evidence",
                    )
                },
                "value_validation": value_validation,
            }
        )
    label = safe_label(str(request.get("project_label") or source.stem))
    return {
        "schema_version": "1.0",
        "source_project": str(source),
        "source_scope": source_scope,
        "source_sha256": source_hash,
        "rscad_version": version,
        "project_label": label,
        "parameter_catalog_snapshot_id": request.get("parameter_catalog_snapshot_id"),
        "operations": normalized_operations,
    }


def patch_dfx(data: bytes, operations: list[dict[str, Any]]) -> tuple[bytes, list[dict[str, Any]]]:
    text, had_bom, components = dfx_components(data)
    expected_components = copy.deepcopy(components)
    lines, ranges = component_blocks(text)
    if len(components) != len(ranges):
        raise PatchSafetyError("component parser and DFX block count disagree")
    changes = []
    for operation in operations:
        candidates = [
            (index, component)
            for index, component in enumerate(components)
            if component["uuid"] == operation["component_id"]
            and (
                operation["context"] is None
                or component["context"] == operation["context"]
            )
        ]
        if len(candidates) != 1:
            raise PatchSafetyError(
                f"component selection resolved to {len(candidates)} blocks"
            )
        component_index, component = candidates[0]
        if component["component_type"] != operation["component_type"]:
            raise PatchSafetyError("component_type does not match selected component")
        parameter = operation["parameter"]
        if parameter not in component["parameters"]:
            raise PatchSafetyError("parameter is not explicitly present in selected component")
        observed_old = component["parameters"][parameter]
        if observed_old != operation["expected_old_value"]:
            raise PatchSafetyError(
                f"expected_old_value mismatch: observed {observed_old!r}"
            )
        start, end = ranges[component_index]
        parameter_lines = []
        in_parameters = False
        for line_index in range(start, end):
            content = lines[line_index]
            ending = "\r\n" if content.endswith("\r\n") else (
                "\n" if content.endswith("\n") else ""
            )
            body = content[:-len(ending)] if ending else content
            stripped = body.strip()
            if stripped == "PARAMETERS-START:":
                in_parameters = True
                continue
            if stripped == "PARAMETERS-END:":
                in_parameters = False
                continue
            if not in_parameters or ":" not in body:
                continue
            name = body.split(":", 1)[0].strip()
            if name == parameter:
                parameter_lines.append((line_index, body, ending))
        if len(parameter_lines) != 1:
            raise PatchSafetyError(
                f"parameter line resolved to {len(parameter_lines)} occurrences"
            )
        line_index, body, ending = parameter_lines[0]
        colon = body.index(":")
        prefix = body[: colon + 1]
        lines[line_index] = prefix + operation["new_value"] + ending
        changes.append(
            {
                "component_id": component["uuid"],
                "context": component["context"],
                "component_type": component["component_type"],
                "parameter": parameter,
                "old_value": observed_old,
                "new_value": operation["new_value"],
                "dfx_line": line_index + 1,
            }
        )
        component["parameters"][parameter] = operation["new_value"]
        expected_components[component_index]["parameters"][parameter] = operation["new_value"]

    modified_text = "".join(lines)
    after_components = parse_dfx_components(modified_text)
    if expected_components != after_components:
        raise PatchSafetyError("Unexpected component or parameter change after reparse")
    before_identity = [
        (row["uuid"], row["context"], row["component_type"])
        for row in components
    ]
    after_identity = [
        (row["uuid"], row["context"], row["component_type"])
        for row in after_components
    ]
    if before_identity != after_identity:
        raise PatchSafetyError("component identity/order changed during parameter patch")
    for operation in operations:
        matches = [
            row for row in after_components
            if row["uuid"] == operation["component_id"]
            and (
                operation["context"] is None
                or row["context"] == operation["context"]
            )
        ]
        if len(matches) != 1 or matches[0]["parameters"].get(operation["parameter"]) != operation["new_value"]:
            raise PatchSafetyError("post-patch parameter reparse verification failed")
    encoded = modified_text.encode("utf-8")
    if had_bom:
        encoded = codecs.BOM_UTF8 + encoded
    return encoded, changes


def write_patched_archive(source: Path, output: Path, dfx_member: str, dfx_data: bytes) -> None:
    if output.exists():
        raise PatchSafetyError("working output already exists")
    output.parent.mkdir(parents=True, exist_ok=False)
    temp = output.parent / (output.name + ".pending")
    try:
        with zipfile.ZipFile(source, "r") as incoming:
            with zipfile.ZipFile(temp, "x") as outgoing:
                outgoing.comment = incoming.comment
                for info in incoming.infolist():
                    data = dfx_data if info.filename == dfx_member else incoming.read(info.filename)
                    outgoing.writestr(info, data)
        os.rename(temp, output)
    finally:
        if temp.exists():
            temp.unlink()


def topology_summary(path: Path, definition_root: Path | None = None) -> dict[str, Any]:
    from .static_comparison import topology_signature
    document = parse_rtfx_topology(path, definition_root or get_settings().definition_root).document
    return {
        "topology_signature": topology_signature(document),
        "source": document["source"],
        "coverage": document["coverage"],
        "warnings": document["warnings"],
        "component_identity": [
            [row["uuid"], row["context"], row["component_type"]]
            for row in document["components"]
        ],
    }


def apply_parameter_patch_request(
    request: dict[str, Any],
    *,
    output_root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    normalized = normalize_request(request)
    if get_settings() != settings:
        raise PatchSafetyError("Configuration changed during patch validation")
    source = Path(normalized["source_project"])
    output_root = (output_root or settings.projects_root / "model_patches").resolve()
    if not is_within(output_root, settings.projects_root):
        raise PatchSafetyError("output_root must be inside agent projects")
    label_root = output_root / normalized["project_label"]
    run_name = run_id or (
        datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
        + "-" + secrets.token_hex(4)
    )
    if not re.fullmatch(r"[A-Za-z0-9_.+-]{1,100}", run_name):
        raise PatchSafetyError("run_id contains unsupported characters")
    run_dir = (label_root / run_name).resolve()
    if not is_within(run_dir, output_root) or run_dir.exists():
        raise PatchSafetyError("patch run directory is unsafe or already exists")

    from .companion_dependencies import discover_companion_dependencies, require_complete, input_files_from_discovery
    source_before = file_record(source)
    request_sha = canonical_sha256(normalized)
    discovery = discover_companion_dependencies(source, settings.definition_root, search_root=source.parent)
    require_complete(discovery)
    companions = input_files_from_discovery(discovery)
    # Validate every requested old value before even creating a temporary copy.
    before_archive = archive_snapshot(source)
    with zipfile.ZipFile(source) as archive:
        dfx_before = archive.read(before_archive["dfx_member"])
    dfx_after, changes = patch_dfx(dfx_before, normalized["operations"])
    final_dir = run_dir
    staging_root = settings.data_dir / ".patch-staging"
    if not is_within(staging_root, settings.data_dir):
        raise PatchSafetyError("Staging path escapes configured data directory")
    staging_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="patch-", dir=staging_root))
    published = False
    try:
        source_dir = run_dir / "source_snapshot"
        working_dir = run_dir / "working"
        source_dir.mkdir(parents=True, exist_ok=False)
        snapshot = source_dir / source.name
        shutil.copy2(source, snapshot)
        if sha256_file(snapshot) != normalized["source_sha256"]:
            raise PatchSafetyError("source snapshot verification failed")
        # The mutable-source precheck is advisory. Derive every published byte
        # from the hash-verified snapshot, even if the source changed and reverted.
        before_archive = archive_snapshot(snapshot)
        with zipfile.ZipFile(snapshot) as archive:
            dfx_before = archive.read(before_archive["dfx_member"])
        if sha256_bytes(dfx_before) != before_archive["member_sha256"][before_archive["dfx_member"]]:
            raise PatchSafetyError("Verified snapshot DFX changed during reading")
        dfx_after, changes = patch_dfx(dfx_before, normalized["operations"])

        working = working_dir / source.name
        write_patched_archive(snapshot, working, before_archive["dfx_member"], dfx_after)

        companion_records = []
        for item in companions:
            original = Path(item["path"]).resolve()
            if not is_within(original, source.parent):
                raise PatchSafetyError("Companion escapes source directory")
            relative = original.relative_to(source.parent)
            for directory in (source_dir, working_dir):
                destination = directory / relative
                if destination.exists() or not is_within(destination, directory):
                    raise PatchSafetyError("Companion output collision or path escape")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
                if sha256_file(destination) != item["sha256"]:
                    raise PatchSafetyError("Companion changed while copying")
            companion_records.append({"source": file_record(original), "working": file_record(working_dir / relative)})
        copied_discovery = discover_companion_dependencies(working, settings.definition_root, search_root=working_dir)
        require_complete(copied_discovery)
        after_archive = archive_snapshot(working)
        if before_archive["members"] != after_archive["members"]:
            raise PatchSafetyError("archive member order changed")
        for name, digest in before_archive["member_sha256"].items():
            if name != before_archive["dfx_member"] and after_archive["member_sha256"][name] != digest:
                raise PatchSafetyError(f"non-DFX archive member changed: {name}")
        if after_archive["member_sha256"][before_archive["dfx_member"]] != sha256_bytes(dfx_after):
            raise PatchSafetyError("written DFX hash differs from patched bytes")
        if before_archive["archive_comment_sha256"] != after_archive["archive_comment_sha256"]:
            raise PatchSafetyError("archive comment changed")

        topology_before = topology_summary(snapshot, settings.definition_root)
        topology_after = topology_summary(working, settings.definition_root)
        graph_fields = (
            "component_count",
            "definition_resolved_count",
            "port_count",
            "connected_port_count",
            "segment_count",
            "net_count",
            "warning_count",
            "hierarchy_link_count",
        )
        graph_unchanged = (
            topology_before["topology_signature"] == topology_after["topology_signature"]
            and topology_before["component_identity"] == topology_after["component_identity"]
            and all(
                topology_before["coverage"][field] == topology_after["coverage"][field]
                for field in graph_fields
            )
            and topology_before["warnings"] == topology_after["warnings"]
        )
        if not graph_unchanged:
            raise PatchSafetyError(
                "parameter-only patch changed the static component/connectivity graph"
            )
        if sha256_file(source) != normalized["source_sha256"]:
            raise PatchSafetyError("source project changed while patch was being created")

        for item in companions:
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise PatchSafetyError("Source companion changed during patch")
        for op in normalized["operations"]:
            prior = op["schema_evidence"]
            current = parameter_schema(op["component_type"], op["parameter"], normalized["rscad_version"], prior.get("parameter_catalog_snapshot_id"))
            if any(current.get(k) != prior.get(k) for k in ("definition_sha256", "parameter_database_sha256", "parameter_audit_sha256")):
                raise PatchSafetyError("Parameter catalog evidence changed during patch")
        if get_settings() != settings:
            raise PatchSafetyError("Configuration changed during patch creation")
        manifest = {
            "companions": companion_records,
            "companion_discovery_sha256": discovery["discovery_sha256"],
            "schema_version": "1.0",
            "created_at": now_iso(),
            "status": "completed",
            "risk_level": "L1_working_copy_edit",
            "request": normalized,
            "request_sha256": request_sha,
            "source": source_before,
            "source_after_sha256": sha256_file(source),
            "source_modified": False,
            "snapshot": file_record(snapshot),
            "working_before_sha256": normalized["source_sha256"],
            "working": file_record(working),
            "archive": {
                "member_count": len(before_archive["members"]),
                "members_unchanged": True,
                "non_dfx_members_unchanged": True,
                "dfx_member": before_archive["dfx_member"],
                "dfx_before_sha256": sha256_bytes(dfx_before),
                "dfx_after_sha256": sha256_bytes(dfx_after),
            },
            "changes": changes,
            "static_validation": {
                "passed": True,
                "graph_unchanged": graph_unchanged,
                "before": topology_before,
                "after": topology_after,
            },
            "safety": {
                "vendor_source_modified": False,
                "rscad_connection_opened": False,
                "rack_query_called": False,
                "compile_called": False,
                "offline_test_called": False,
                "runtime_called": False,
                "hardware_io_called": False,
            },
        }
        def final_paths(value):
            if isinstance(value, dict):
                return {k: final_paths(v) for k, v in value.items()}
            if isinstance(value, list):
                return [final_paths(v) for v in value]
            if isinstance(value, str) and (value == str(run_dir) or value.startswith(str(run_dir) + os.sep)):
                return str(final_dir) + value[len(str(run_dir)):]
            return value
        manifest = final_paths(manifest)
        manifest_path = run_dir / "structured_parameter_patch.json"
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        result = {
            "companions_preserved": True,
            "detail_diff": {"parameter_changes": changes, "unexpected_changes": [], "same_static_topology": graph_unchanged},
            "parameter_catalog_snapshot_ids": sorted({op["schema_evidence"]["parameter_catalog_snapshot_id"] for op in normalized["operations"] if op["schema_evidence"].get("parameter_catalog_snapshot_id")}),
            "status": "completed",
            "run_directory": str(run_dir),
            "source_project": str(source),
            "working_project": str(working),
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "request_sha256": request_sha,
            "source_sha256": normalized["source_sha256"],
            "working_sha256": sha256_file(working),
            "dfx_before_sha256": sha256_bytes(dfx_before),
            "dfx_after_sha256": sha256_bytes(dfx_after),
            "changes": changes,
            "static_validation_passed": True,
            "source_modified": False,
            "compile_called": False,
            "runtime_or_hardware_called": False,
        }
        result = final_paths(result)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if not is_within(final_dir, output_root) or final_dir.exists():
            raise PatchSafetyError("Publication destination changed or already exists")
        run_dir.rename(final_dir)
        published = True
        return result
    finally:
        if not published and run_dir.exists():
            resolved = run_dir.resolve()
            if not is_within(resolved, staging_root):
                raise PatchSafetyError("refusing cleanup outside patch staging root")
            shutil.rmtree(resolved)


def build_single_parameter_request(
    source_project: str,
    component_id: int,
    component_type: str,
    parameter: str,
    expected_old_value: str,
    new_value: str,
    *,
    context: str | None = None,
    project_label: str | None = None,
    rscad_version: str = "2.7.3",
    expected_source_sha256: str | None = None,
    parameter_catalog_snapshot_id: str | None = None,
) -> dict[str, Any]:
    source, _ = resolve_rtfx_path(source_project)
    observed_source_sha256 = sha256_file(source)
    if expected_source_sha256 is not None and expected_source_sha256 != observed_source_sha256:
        raise PatchSafetyError("source_project hash differs from expected_source_sha256")
    return {
        "schema_version": "1.0",
        "source_project": str(source),
        "source_sha256": observed_source_sha256,
        "rscad_version": rscad_version,
        "project_label": project_label or source.stem,
        "parameter_catalog_snapshot_id": parameter_catalog_snapshot_id,
        "operations": [
            {
                "op": "set_parameter",
                "component_id": component_id,
                "context": context,
                "component_type": component_type,
                "parameter": parameter,
                "expected_old_value": expected_old_value,
                "new_value": new_value,
            }
        ],
    }


__all__ = [
    "PatchSafetyError",
    "apply_parameter_patch_request",
    "build_single_parameter_request",
    "normalize_request",
    "patch_dfx",
]

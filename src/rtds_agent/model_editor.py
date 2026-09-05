"""Bounded reviewed editing with static and explicit native candidate backends.

Insertion uses an exact existing same-context template, never an invented vendor
record. The default static transaction never calls the SDK.
"""
from __future__ import annotations
import codecs
import copy
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile
from typing import Annotated, Any
from pydantic import BeforeValidator, WithJsonSchema
from .input_contracts import schema, validate
from .settings import get_settings, within
from .safety import ToolSafetyError, sha256_file
from .project_tools import _document
from .core.component_policy import read_component_policy, authorize
from .core.topology_parser import parse_dfx_components, parse_parameter_schema, parse_active_nodes, parse_rtfx_topology, HEADER_RE
from .core.structured_patch import archive_snapshot, write_patched_archive, validate_new_value
from .core.state_machine import sha256_json
from .core.model_ir import semantic_diff
from .model_check import check_document

EDIT_SCHEMA = schema("model_edit.schema.json")


def validate_edit(value):
    validate(value, EDIT_SCHEMA)
    if value["mode"] == "apply" and "preview_id" not in value:
        raise ToolSafetyError("Apply requires the exact reviewed preview_id")
    return value


EditRequest = Annotated[dict, BeforeValidator(validate_edit), WithJsonSchema(EDIT_SCHEMA)]


def _definitions(document):
    result = {}
    for kind, ref in document["definition_evidence"].items():
        path = Path(ref["path"])
        if path.stat().st_size > 2*1024*1024:
            raise ToolSafetyError("Definition exceeds editor bounds")
        raw = path.read_bytes()
        import hashlib
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ToolSafetyError("Definition changed before edit")
        result[kind] = raw.decode("utf-8-sig")
    return result


def _value(definition, parameter, value, op):
    entry = parse_parameter_schema(definition).get(parameter)
    if not entry:
        raise ToolSafetyError("Parameter is not declared by the installed definition")
    if op == "set_parameter":
        validate_new_value(entry, value)
    elif op == "set_selector":
        if entry["data_type"] != "TOGGLE" or value not in (entry["enum_values"] or []):
            raise ToolSafetyError("Selector requires an exact declared TOGGLE label")
    elif op in {"set_string", "rename_component"}:
        supported = {"NAME"} if op == "rename_component" else {"NAME", "CHAR", "TEXT", "CHARACTER"}
        if entry["data_type"] not in supported:
            raise ToolSafetyError("String editing supports declared text/name fields; FILE references are excluded")
    else:
        dtype = entry["data_type"]
        _value(definition, parameter, value, "set_parameter" if dtype in {"REAL", "INTEGER"} else "set_selector" if dtype == "TOGGLE" else "set_string")


def edit_dfx(data, operations, definitions, policy, *, has_other_members):
    text = data.decode("utf-8-sig")
    initial = parse_dfx_components(text)
    if len(initial) > 2000 or len(initial) != len(re.findall(r"^COMPONENT_TYPE=", text, re.M)):
        raise ToolSafetyError("Editor requires at most 2000 fully identified component records")
    expected = copy.deepcopy(initial)
    seen = set()
    for op in operations:
        operation = op["op"]
        key = (op["context"], op["component_id"])
        # Sequential edits to different fields are permitted; duplicate field edits are not.
        target = (*key, op.get("parameter", operation), op.get("new_component_id"))
        if target in seen:
            raise ToolSafetyError("Duplicate edit target")
        seen.add(target)
        components = parse_dfx_components(text)
        matches = [i for i,c in enumerate(components) if (c["context"],c["uuid"]) == key]
        if len(matches) != 1:
            raise ToolSafetyError("Component context/UUID must resolve exactly once")
        index = matches[0]
        row = components[index]
        if row["component_type"] != op["component_type"] or row["component_type"] == "HIERARCHY":
            raise ToolSafetyError("Type mismatch or unsupported hierarchy edit")
        kind = row["component_type"]
        authorize(policy, kind, op.get("parameter"))
        if kind not in definitions:
            raise ToolSafetyError("Editing requires a resolved installed definition")
        lines = text.splitlines(keepends=True)
        starts = [i for i,l in enumerate(lines) if l.startswith("COMPONENT_TYPE=")]
        start = starts[index]
        # End at this record's UUID; never consume the next hierarchy/footer.
        bound = starts[index+1] if index+1 < len(starts) else len(lines)
        ends = [i for i in range(start,bound) if re.fullmatch(r"\s*UUID:\s*\d+\s*", lines[i])]
        if not ends or int(lines[ends[0]].split(":",1)[1]) != row["uuid"]:
            raise ToolSafetyError("Unsupported component record boundary")
        end = ends[0]+1
        header = next((i for i in range(start+1,end) if lines[i].strip()), None)
        if header is None or not HEADER_RE.fullmatch(lines[header].strip()):
            raise ToolSafetyError("Unsupported record location header")
        desired = copy.deepcopy(row)
        expected_index = next(i for i,c in enumerate(expected) if (c["context"],c["uuid"]) == key)
        def parameter(name, value):
            authorize(policy, kind, name)
            a = [i for i in range(header+1,end) if lines[i].strip() == "PARAMETERS-START:"]
            b = [i for i in range(header+1,end) if lines[i].strip() == "PARAMETERS-END:"]
            if len(a) != 1 or len(b) != 1 or a[0] >= b[0]:
                raise ToolSafetyError("Unsupported parameter block")
            indexes = [i for i in range(a[0]+1,b[0]) if lines[i].partition(":")[0].strip() == name]
            if len(indexes) != 1 or name not in desired["parameters"]:
                raise ToolSafetyError("Only exactly stored parameters can be edited")
            i = indexes[0]
            ending = "\r\n" if lines[i].endswith("\r\n") else "\n"
            prefix = lines[i].split(":",1)[0]
            lines[i] = prefix + ": " + value + ending
            desired["parameters"][name] = value
        def location(value):
            tokens = lines[header].split()
            ending = "\r\n" if lines[header].endswith("\r\n") else "\n"
            lines[header] = " ".join([*map(str,value),*tokens[2:]]) + ending
            desired["location"] = list(value)
        if operation in {"set_parameter", "set_selector", "set_string", "rename_component"}:
            name = op["parameter"]
            if row["parameters"].get(name) != op["expected_old_value"] or op["expected_old_value"] == op["new_value"]:
                raise ToolSafetyError("Expected old value mismatch or no-op")
            _value(definitions[kind], name, op["new_value"], operation)
            parameter(name, op["new_value"])
        elif operation == "move_component":
            if row["location"] != op["expected_location"] or row["location"] == op["location"]:
                raise ToolSafetyError("Expected location mismatch or no-op")
            location(op["location"])
        elif operation in {"rewire", "create_wire"}:
            if kind != "WIRE" or row["orientation"] != 0 or row["mirrored"] or op["start"] == op["end"]:
                raise ToolSafetyError("Wire operations require an unrotated, unmirrored WIRE template and distinct endpoints")
            if operation == "rewire" and any(row["parameters"].get(k) != v for k,v in op["expected_parameters"].items()):
                raise ToolSafetyError("Expected wire geometry mismatch")
            location([0,0])
            for name,value in zip(("x1","y1","x2","y2"), [*op["start"],*op["end"]]):
                _value(definitions[kind], name, str(value), "set_parameter")
                parameter(name,str(value))
        elif operation in {"clone_component", "insert_component"}:
            location(op["location"])
            for name,value in op["parameters"].items():
                _value(definitions[kind], name, value, "template_override")
                parameter(name,value)
        elif operation in {"remove_component", "remove_wire"}:
            if has_other_members:
                raise ToolSafetyError("Removal is unsupported with opaque companion archive records/RTX references")
            if (operation == "remove_wire") != (kind == "WIRE"):
                raise ToolSafetyError("Use remove_wire for WIRE records and remove_component for other types")
        else:
            raise ToolSafetyError("Unsupported structural operation")
        if operation in {"insert_component","clone_component","create_wire","remove_component","remove_wire"}:
            # Only a complete simple record can be duplicated/deleted. Unknown native
            # metadata may contain UUID references and cannot be safely manufactured.
            block = lines[start:end]
            a = next((i for i,l in enumerate(block) if l.strip() == "PARAMETERS-START:"), -1)
            b = next((i for i,l in enumerate(block) if l.strip() == "PARAMETERS-END:"), -1)
            allowed = {0,header-start,a,b,end-start-1} | set(range(a+1,b))
            if a < 0 or b <= a or any(l.strip() for i,l in enumerate(block) if i not in allowed):
                raise ToolSafetyError("Template contains unsupported metadata; native structural adapter remains unqualified")
            if operation.startswith("remove_"):
                del lines[start:end]
                expected.pop(expected_index)
            else:
                new_id = op["new_component_id"]
                if any(c["uuid"] == new_id for c in components):
                    raise ToolSafetyError("New component UUID already exists")
                block[-1] = f"UUID: {new_id}\n"
                desired["uuid"] = new_id
                # Restore source template bytes and insert the changed template after it.
                original_lines = text.splitlines(keepends=True)
                lines = original_lines[:end] + block + original_lines[end:]
                expected.insert(expected_index+1,desired)
        else:
            expected[expected_index] = desired
        text = "".join(lines)
        if parse_dfx_components(text) != expected:
            raise ToolSafetyError("Unexpected semantic record change after edit/reparse")
        for c in expected:
            if c["component_type"] in definitions:
                _, warnings = parse_active_nodes(definitions[c["component_type"]], c)
                if warnings:
                    raise ToolSafetyError("Active-node coverage is incomplete for the edited candidate")
    return (codecs.BOM_UTF8 if data.startswith(codecs.BOM_UTF8) else b"") + text.encode("utf-8")


def edit_rscad_model(request: EditRequest) -> dict[str, Any]:
    """Preview/apply isolated candidates with static or bounded native Draft editing.

    Omitted backend preserves static behavior. Auto falls back to preview only
    until operation-scoped native integration qualification is available.
    """
    validate_edit(request)
    if request.get("backend", "static") != "static":
        from .native_editor import native_edit
        return native_edit(request, _edit_static)
    return _edit_static(request)


def _edit_static(request):
    validate_edit(request)
    settings = get_settings()
    source, _, before = _document(request["source_project"], request["snapshot_id"])
    if sha256_file(source) != request["source_sha256"]:
        raise ToolSafetyError("Editor source hash mismatch")
    policy = read_component_policy(source)
    if policy["sha256"] != request["policy_sha256"]:
        raise ToolSafetyError("Editor component policy hash mismatch")
    if before["warnings"] or before["coverage"]["definition_coverage"] != 1:
        raise ToolSafetyError("Editor requires resolved static definitions/nodes without parser warnings")
    from .core.companion_dependencies import discover_companion_dependencies, require_complete, input_files_from_discovery
    discovery = discover_companion_dependencies(source, settings.definition_root, search_root=source.parent)
    require_complete(discovery)
    companions = input_files_from_discovery(discovery)
    definitions = _definitions(before)
    staging_root = settings.data_dir / ".editor-staging"
    if not within(staging_root, settings.data_dir):
        raise ToolSafetyError("Editor staging escapes configured data root")
    staging_root.mkdir(parents=True,exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="edit-",dir=staging_root))
    published = False
    try:
        snapshot_dir = stage / "source_snapshot"
        snapshot_dir.mkdir()
        snapshot = snapshot_dir / source.name
        shutil.copy2(source,snapshot)
        if sha256_file(snapshot) != request["source_sha256"]:
            raise ToolSafetyError("Editor source snapshot hash mismatch")
        archive_before = archive_snapshot(snapshot)
        with zipfile.ZipFile(snapshot) as archive:
            data = archive.read(archive_before["dfx_member"])
        changed = edit_dfx(data, request["operations"], definitions, policy, has_other_members=len(archive_before["members"]) > 1)
        working = stage / "working" / source.name
        write_patched_archive(snapshot,working,archive_before["dfx_member"],changed)
        # Policy travels unchanged with the candidate but never activates live execution.
        for root in (snapshot_dir,working.parent):
            shutil.copy2(policy["path"],root / "rtds-component-policy.json")
            if sha256_file(root / "rtds-component-policy.json") != policy["sha256"]:
                raise ToolSafetyError("Policy changed during copy")
        for ref in companions:
            original = Path(ref["path"]).resolve()
            if not within(original,source.parent): raise ToolSafetyError("Companion escapes source directory")
            relative = original.relative_to(source.parent)
            for root in (snapshot_dir,working.parent):
                dest = root / relative
                if not within(dest,root) or dest.exists(): raise ToolSafetyError("Companion path escape or collision")
                dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(original,dest)
                if sha256_file(dest) != ref["sha256"]: raise ToolSafetyError("Companion changed during copy")
        require_complete(discover_companion_dependencies(working, settings.definition_root, search_root=working.parent))
        archive_after = archive_snapshot(working)
        import hashlib
        if archive_after["member_sha256"][archive_before["dfx_member"]] != hashlib.sha256(changed).hexdigest():
            raise ToolSafetyError("Saved candidate DFX differs from the verified edit bytes")
        if archive_before["members"] != archive_after["members"] or archive_before["archive_comment_sha256"] != archive_after["archive_comment_sha256"]:
            raise ToolSafetyError("Archive members/comment changed unexpectedly")
        for name,digest in archive_before["member_sha256"].items():
            if name != archive_before["dfx_member"] and archive_after["member_sha256"][name] != digest:
                raise ToolSafetyError("Non-DFX archive member changed")
        after = parse_rtfx_topology(working,settings.definition_root).document
        check = check_document(after)
        if check["status"] == "errors_found":
            raise ToolSafetyError("Candidate model check found errors: " + ", ".join(f["finding"] for f in check["findings"] if f["severity"] == "error"))
        payload = {"request": {k:v for k,v in request.items() if k not in {"mode","preview_id"}},
                   "candidate_sha256": sha256_file(working), "semantic_diff": semantic_diff(before,after),
                   "model_check": check, "definition_evidence": before["definition_evidence"],
                   "companion_discovery_sha256": discovery["discovery_sha256"],
                   "editor_sha256": sha256_file(Path(__file__))}
        preview_id = sha256_json(payload)
        if request["mode"] == "apply" and preview_id != request["preview_id"]:
            raise ToolSafetyError("Reviewed preview differs from current edit/inputs/candidate")
        _document(str(source),before["snapshot_id"])
        if get_settings() != settings or read_component_policy(source) != policy:
            raise ToolSafetyError("Settings or project component policy changed during edit")
        for ref in companions:
            if sha256_file(Path(ref["path"])) != ref["sha256"]: raise ToolSafetyError("Source companion changed")
        result = {"status": "previewed", "preview_id": preview_id, **payload,
                  "source_modified": False, "live_calls_made": False, "integration_qualified": False,
                  "qualification": "static_candidate_only; native structural save/reopen/compile unqualified"}
        if request["mode"] == "preview": return result
        final = settings.projects_root / "model_edits" / request["project_label"] / uuid.uuid4().hex
        if not within(final,settings.projects_root) or final.exists(): raise ToolSafetyError("Invalid editor publication destination")
        result.update(status="completed", working_project=str(final/"working"/source.name),
                      working={"path":str(final/"working"/source.name),"sha256":sha256_file(working)})
        marker = stage / "structural_model_edit.json"
        marker.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        digest = sha256_file(marker)
        final.parent.mkdir(parents=True,exist_ok=True)
        os.rename(stage,final)
        published = True
        return {**result,"manifest_path":str(final/marker.name),"manifest_sha256":digest}
    finally:
        if not published and stage.is_dir() and within(stage,staging_root):
            shutil.rmtree(stage)

"""Offline selector impact analysis and isolated, explicitly unexecuted trial bundles."""
from __future__ import annotations
from typing import Any
import copy
import json
import hashlib
import math
import re
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4
from .input_contracts import SelectorRequest, validate_selector
from .project_tools import _document
from .settings import get_settings, within
from .safety import ToolSafetyError, sha256_file
from .core.state_machine import sha256_json
from .core.topology_parser import parse_parameter_schema, parse_active_nodes
from .core.companion_dependencies import discover_companion_dependencies, input_files_from_discovery


def preview_selector_change(request: SelectorRequest) -> dict[str, Any]:
    """Compare active-node consequences of one audited TOGGLE value in memory; no RTFX edit."""
    validate_selector(request)
    settings = get_settings()
    source, _, document = _document(request["source_project"], request["snapshot_id"])
    if document["source"]["rtfx_sha256"] != request["source_sha256"]:
        raise ToolSafetyError("Selector source hash mismatch")
    matches = [r for r in document["components"] if r["uuid"] == request["component_id"] and r["context"] == request["context"]]
    if len(matches) != 1 or matches[0]["component_type"] != request["component_type"]:
        raise ToolSafetyError("Selector component context/identity/type is ambiguous or mismatched")
    component = matches[0]
    parameter = request["parameter"]
    if component["parameters"].get(parameter) != request["expected_old_value"]:
        raise ToolSafetyError("Selector expected old value differs from stored value")
    reference = document["snapshot"]["evidence"]["definitions"][component["component_type"]]
    if reference["status"] != "resolved":
        raise ToolSafetyError("Selector definition is unresolved")
    definition = Path(reference["path"])
    if not within(definition, settings.definition_root) or definition.stat().st_size > 2 * 1024 * 1024:
        raise ToolSafetyError("Selector definition is outside supported bounds")
    raw_definition = definition.read_bytes()
    if hashlib.sha256(raw_definition).hexdigest() != reference["sha256"]:
        raise ToolSafetyError("Selector definition bytes differ from the snapshot")
    text = raw_definition.decode("utf-8-sig")
    schema = parse_parameter_schema(text)
    entry = schema.get(parameter)
    if not entry or entry["data_type"] != "TOGGLE":
        raise ToolSafetyError("Selector preview supports audited TOGGLE definitions only")
    options = entry["enum_values"] or []
    if len(options) > 128 or len(set(v.casefold() for v in options)) != len(options):
        raise ToolSafetyError("Selector enumeration is ambiguous or exceeds limits")
    if request["expected_old_value"] not in options or request["new_value"] not in options:
        raise ToolSafetyError("Selector values must exactly match declared option labels")
    if request["new_value"] == request["expected_old_value"]:
        raise ToolSafetyError("Selector change must change the value")
    candidate = copy.deepcopy(component)
    candidate["parameters"][parameter] = request["new_value"]
    before, before_warnings = parse_active_nodes(text, component)
    after, after_warnings = parse_active_nodes(text, candidate)
    if len(before) + len(after) > 2000:
        raise ToolSafetyError("Selector node inventory exceeds limits")
    def clean(nodes):
        return [{k: v for k, v in node.items() if k != "raw"} for node in nodes]
    before, after = clean(before), clean(after)
    if any(not math.isfinite(value) for node in before + after for value in node["local"]):
        raise ToolSafetyError("Selector candidate has unsupported non-finite node coordinates")
    before_set = {sha256_json(n): n for n in before}
    after_set = {sha256_json(n): n for n in after}
    removed = [before_set[k] for k in sorted(before_set.keys() - after_set.keys())]
    added = [after_set[k] for k in sorted(after_set.keys() - before_set.keys())]
    affected_names = {n["name"] for n in removed}
    affected_nets = []
    for net in document["nets"]:
        targets = [m for m in net["members"] if m.get("component_id") == component["uuid"] and m.get("context") == component["context"] and m.get("port") in affected_names]
        if targets:
            affected_nets.append({"net_id": net.get("net_id"), "member_count": len(net["members"]),
                                  "target_ports": [t["port"] for t in targets], "connection_review_required": len(net["members"]) > 1})
    unresolved = before_warnings + after_warnings
    evidence = {"snapshot_id": document["snapshot_id"], "source_sha256": request["source_sha256"],
                "definition_path": str(definition), "definition_sha256": reference["sha256"],
                "analysis_sha256": sha256_file(Path(__file__))}
    if sha256_file(definition) != reference["sha256"]:
        raise ToolSafetyError("Selector definition changed during preview")
    _document(str(source), document["snapshot_id"])
    if get_settings() != settings:
        raise ToolSafetyError("Configuration changed during selector preview")
    result = {"status": "inconclusive" if unresolved else "analyzed", "evidence": evidence,
              "request": request, "declared_options": options, "target_location_on_disk": component["location"],
              "before_nodes": before, "after_nodes": after, "removed_or_changed_nodes": removed,
              "added_or_changed_nodes": added, "affected_existing_nets": affected_nets,
              "warnings": unresolved, "project_warnings": document["warnings"],
              "node_structure_changed": bool(removed or added), "rtfx_modified": False,
              "live_calls_made": False, "integration_qualified": False,
              "automatic_application_supported": False,
              "non_node_and_dependency_effects": "not_evaluated",
              "required_validation": ["Connected SDK set_parameter on an isolated stopped case",
                                      "Save to a new candidate path, reopen, requery and detailed diff",
                                      "Recheck every companion and connection, including changed active ports",
                                      "Separately authorized Compile; no Runtime implied"],
              "limitations": ["Only the supported NODES expression subset is evaluated",
                              "No candidate RTFX bytes are invented or published as a valid edit",
                              "Equal node lists do not prove unchanged semantics or dependencies"]}
    result["preview_id"] = sha256_json(result)
    return result


def prepare_extension_trial(request: SelectorRequest) -> dict[str, Any]:
    """Copy a hash-bound model/companions into an unexecuted selector trial; no SDK access."""
    settings = get_settings()
    preview = preview_selector_change(request)
    if preview["status"] != "analyzed":
        raise ToolSafetyError("Unresolved selector conditions prevent preparing a trial")
    source = Path(request["source_project"]).resolve()
    discovery = discover_companion_dependencies(source, settings.definition_root, search_root=source.parent)
    companions = input_files_from_discovery(discovery)
    inputs = [{"path": str(source), "sha256": request["source_sha256"]}, *companions]
    relatives = set()
    for item in inputs:
        path = Path(item["path"]).resolve()
        if not within(path, source.parent):
            raise ToolSafetyError("Trial companion escapes source directory")
        relative = path.relative_to(source.parent)
        if relative.as_posix().casefold() in relatives:
            raise ToolSafetyError("Trial input path collision")
        relatives.add(relative.as_posix().casefold())
        if sha256_file(path) != item["sha256"]:
            raise ToolSafetyError("Trial source input changed")
    parent = settings.projects_root / ".extension-trials"
    staging = settings.data_dir / ".extension-trial-staging"
    if not within(parent, settings.projects_root) or not within(staging, settings.data_dir):
        raise ToolSafetyError("Trial output path redirects outside configured roots")
    staging.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="trial-", dir=staging))
    final = parent / uuid4().hex
    published = False
    try:
        records = []
        for item in inputs:
            original = Path(item["path"])
            relative = original.relative_to(source.parent)
            for branch in ("source_snapshot", "working"):
                target = stage / branch / relative
                if not within(target, stage) or target.exists():
                    raise ToolSafetyError("Unsafe trial copy destination")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
                if sha256_file(target) != item["sha256"]:
                    raise ToolSafetyError("Trial copy hash mismatch")
            records.append({"source": str(original), "relative_path": relative.as_posix(), "sha256": item["sha256"]})
        if preview_selector_change(request)["preview_id"] != preview["preview_id"]:
            raise ToolSafetyError("Trial preview evidence changed")
        for item in inputs:
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise ToolSafetyError("Trial original changed while copying")
        if get_settings() != settings:
            raise ToolSafetyError("Configuration changed while preparing trial")
        result = {"status": "prepared_unexecuted", "trial_directory": str(final),
                  "source_snapshot": str(final / "source_snapshot" / source.name),
                  "working_project": str(final / "working" / source.name), "working_sha256": request["source_sha256"],
                  "inputs": records, "preview": preview, "preview_id": preview["preview_id"],
                  "source_modified": False, "working_model_modified": False,
                  "live_calls_made": False, "integration_qualified": False,
                  "candidate_path_for_future_save_as": str(final / "candidate" / source.name),
                  "candidate_exists": False, "sdk_actions_executed": [],
                  "future_target": {"component_id": request["component_id"], "context": request["context"],
                                    "component_type": request["component_type"], "parameter": request["parameter"],
                                    "expected_old_value": request["expected_old_value"], "new_value": request["new_value"]},
                  "required_authorization": "Separate explicit permission for RSCAD connection, case open, selector edit and save-as/reopen; no rack/runtime implied"}
        marker = stage / "extension_trial.json"
        marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        parent.mkdir(parents=True, exist_ok=True)
        if not within(final, settings.projects_root) or final.exists():
            raise ToolSafetyError("Trial publication path changed")
        stage.rename(final)
        published = True
        return {**result, "manifest_path": str(final / marker.name), "manifest_sha256": sha256_file(final / marker.name)}
    finally:
        if not published and stage.exists():
            if not within(stage, staging):
                raise ToolSafetyError("Refusing trial cleanup outside staging root")
            shutil.rmtree(stage)

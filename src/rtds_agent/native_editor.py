"""Reviewed preview -> fixed native worker -> exact comparison -> publication."""
from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile

from .settings import get_settings, within
from .safety import ToolSafetyError, sha256_file
from .policy import execution_lock
from .project_tools import _document
from .core.component_policy import read_component_policy
from .core.native_edit import inspect_native_sdk, OPERATIONS
from .core.state_machine import sha256_json
from .core.structured_patch import archive_snapshot, write_patched_archive
from .core.topology_parser import parse_rtfx_topology
from .core.model_ir import semantic_diff
from .model_check import check_document
from .core.native_rebuild import reconstruction_plan, compare_reconstruction


def rebuild_preview(request, source, before, settings):
    from .core.component_policy import authorize
    from .core.companion_dependencies import discover_companion_dependencies, require_complete
    from .model_editor import _definitions
    if sha256_file(source) != request["source_sha256"]: raise ToolSafetyError("Reconstruction source hash mismatch")
    policy = read_component_policy(source)
    if policy["sha256"] != request["policy_sha256"]: raise ToolSafetyError("Reconstruction component policy hash mismatch")
    if before["warnings"] or before["coverage"]["definition_coverage"] != 1:
        raise ToolSafetyError("Reconstruction requires resolved definitions and complete parsed nodes")
    strategy = request["operations"][0]["strategy"]
    for row in before["components"]:
        authorize(policy,row["component_type"])
        if strategy == "insert" and row["component_type"] not in {"WIRE","BUS"}:
            for parameter in row["parameters"]: authorize(policy,row["component_type"],parameter)
    if before.get("groups"): authorize(policy,"GROUP")
    _definitions(before)
    discovery = discover_companion_dependencies(source,settings.definition_root,search_root=source.parent)
    require_complete(discovery)
    payload = {"request":{k:v for k,v in request.items() if k not in {"mode","preview_id"}},
        "reconstruction_plan":reconstruction_plan(source,before,strategy),
        "definition_evidence":before["definition_evidence"],"companion_discovery_sha256":discovery["discovery_sha256"],
        "candidate_sha256":None,"model_check":check_document(before)}
    if payload["model_check"]["status"] == "errors_found": raise ToolSafetyError("Source reconstruction model check failed")
    return {"status":"previewed",**payload,"preview_id":sha256_json(payload),"source_modified":False,
            "live_calls_made":False,"integration_qualified":False}


def native_edit(request, static_editor):
    settings = get_settings()
    # Static validation remains authoritative for bounds, policy and expected values.
    preview_request = {k:v for k,v in request.items() if k not in {"backend", "preview_id"}}
    preview_request["mode"] = "preview"
    source, _, before = _document(request["source_project"], request["snapshot_id"])
    rebuilding = request["operations"][0]["op"] == "rebuild_draft"
    expected = rebuild_preview(request,source,before,settings) if rebuilding else static_editor(preview_request)
    sdk = inspect_native_sdk(settings)
    supported = rebuilding or (not before.get("groups") and
                 all(c["context"] == "subsystem:0" and c["component_type"] != "HIERARCHY" for c in before["components"]) and
                 all(op["op"] in OPERATIONS and op["context"] == "subsystem:0" for op in request["operations"]))
    selection = {"requested_backend": request["backend"], "backend": "native" if request["backend"] == "native" else "static",
                 "sdk": sdk, "supported_request": supported,
                 "native_editor_sha256": sha256_file(Path(__file__)),
                 "auto_reason": "No operation-scoped native construction/Compile qualification is installed" if request["backend"] == "auto" else None}
    result = {**expected, **selection, "static_preview_id": expected["preview_id"]}
    result["preview_id"] = sha256_json({"static_preview_id": expected["preview_id"], **selection})
    result["qualification"] = "preview_only; native Draft reconstruction and existing flat edits require saved verification"
    if request["mode"] == "preview": return result
    if request["preview_id"] != result["preview_id"]: raise ToolSafetyError("Native reviewed preview changed")
    if request["backend"] == "auto": raise ToolSafetyError("Auto fallback is static preview only; explicitly review a supported backend")
    if not sdk["available"] or not supported: raise ToolSafetyError("Native SDK or requested operation is outside the implemented adapter scope")
    marker = settings.data_dir / "native_recovery_required.json"
    if marker.exists(): raise ToolSafetyError("Previous native attempt requires operator recovery; inspect its journal")
    from .model_editor import _definitions, edit_dfx
    from .core.companion_dependencies import discover_companion_dependencies, require_complete, input_files_from_discovery
    source, _, before = _document(request["source_project"], request["snapshot_id"])
    policy = read_component_policy(source)
    definitions = _definitions(before)
    discovery = discover_companion_dependencies(source, settings.definition_root, search_root=source.parent)
    require_complete(discovery)
    companions = input_files_from_discovery(discovery)
    staging = settings.data_dir / ".native-editor-staging"
    if not within(staging, settings.data_dir): raise ToolSafetyError("Native staging escapes data directory")
    staging.mkdir(parents=True, exist_ok=True)
    with execution_lock(settings):
        if marker.exists(): raise ToolSafetyError("Native recovery marker appeared before execution")
        stage = Path(tempfile.mkdtemp(prefix="edit-", dir=staging))
        started = False
        try:
            for folder in ("source_snapshot", "input", "working"):
                root = stage / folder
                root.mkdir()
                if folder != "working": shutil.copy2(source, root / source.name)
                shutil.copy2(policy["path"], root / "rtds-component-policy.json")
                if sha256_file(root / "rtds-component-policy.json") != policy["sha256"]:
                    raise ToolSafetyError("Native copied component policy changed")
                for ref in companions:
                    original = Path(ref["path"]).resolve()
                    if not within(original, source.parent): raise ToolSafetyError("Native companion escape")
                    dest = root / original.relative_to(source.parent)
                    if dest.exists() or not within(dest, root): raise ToolSafetyError("Native companion collision/escape")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, dest)
                    if sha256_file(dest) != ref["sha256"]: raise ToolSafetyError("Native companion changed")
            snapshot, inp, out = [stage / f / source.name for f in ("source_snapshot", "input", "working")]
            if any(sha256_file(p) != request["source_sha256"] for p in (snapshot, inp)):
                raise ToolSafetyError("Native source copy hash mismatch")
            archive = archive_snapshot(snapshot)
            with zipfile.ZipFile(snapshot) as z: data = z.read(archive["dfx_member"])
            reference = snapshot
            if not rebuilding:
                changed = edit_dfx(data, request["operations"], definitions, policy, has_other_members=len(archive["members"]) > 1)
                reference = stage / "expected" / source.name
                write_patched_archive(snapshot, reference, archive["dfx_member"], changed)
                if sha256_file(reference) != expected["candidate_sha256"]: raise ToolSafetyError("Native static preview changed before dispatch")
            if inspect_native_sdk(settings) != sdk or read_component_policy(source) != policy or get_settings() != settings:
                raise ToolSafetyError("Native settings/policy/SDK changed before dispatch")
            _document(str(source), request["snapshot_id"])
            protected_copies = {path: sha256_file(path) for folder in ("source_snapshot", "input", "working")
                                for path in (stage / folder).rglob("*") if path.is_file()}
            job = {"request": request, "sdk": sdk, "input_path": str(inp), "output_path": str(out)}
            job_path = stage / "native_job.json"
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            env = {k:v for k,v in os.environ.items() if not k.startswith("OPENAI_")}
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            started = True
            with (stage / "worker.log").open("w", encoding="utf-8") as log:
                process = subprocess.run([sys.executable, "-m", "rtds_agent.core.native_edit_worker", str(job_path)],
                                         env=env, stdout=log, stderr=log, timeout=120, check=False)
            journal = json.loads((stage / "native_journal.json").read_text(encoding="utf-8"))
            if process.returncode or journal["status"] != "verified_edit" or not journal["cleanup_verified"]:
                raise ToolSafetyError("Native edit failed; inspect retained journal: " + str(stage))
            if sha256_file(out) != journal["candidate_sha256"]:
                raise ToolSafetyError("Native candidate differs from reopened evidence")
            expected_doc = parse_rtfx_topology(reference, settings.definition_root).document
            after = parse_rtfx_topology(out, settings.definition_root).document
            if rebuilding:
                comparison = compare_reconstruction(expected_doc,after)
            else:
                comparison = semantic_diff(expected_doc, after)
                if comparison["added"] or comparison["removed"] or comparison["changed"] or not comparison["same_static_topology"]:
                    raise ToolSafetyError("Native save differs from the reviewed static semantics")
            if expected_doc["source"]["settings"] != after["source"]["settings"]:
                raise ToolSafetyError("Native save changed unrequested settings")
            saved = archive_snapshot(out)
            if set(saved["members"]) != set(archive["members"]): raise ToolSafetyError("Native archive member set changed")
            if saved["archive_comment_sha256"] != archive["archive_comment_sha256"]:
                raise ToolSafetyError("Native save changed the unreviewed archive comment")
            for name, digest in archive["member_sha256"].items():
                if name != archive["dfx_member"] and saved["member_sha256"][name] != digest:
                    raise ToolSafetyError("Native save changed unreviewed non-DFX data")
            check = check_document(after)
            if check["status"] == "errors_found": raise ToolSafetyError("Native candidate model check failed")
            _document(str(source), request["snapshot_id"])
            if get_settings() != settings or read_component_policy(source) != policy or inspect_native_sdk(settings) != sdk:
                raise ToolSafetyError("Native settings/policy/SDK changed before publication")
            for ref in companions:
                if sha256_file(Path(ref["path"])) != ref["sha256"] or sha256_file(out.parent / Path(ref["path"]).relative_to(source.parent)) != ref["sha256"]:
                    raise ToolSafetyError("Native companion preservation failed")
            if sha256_file(inp) != request["source_sha256"] or sha256_file(snapshot) != request["source_sha256"]:
                raise ToolSafetyError("Native input/snapshot was modified")
            if any(sha256_file(path) != digest for path, digest in protected_copies.items()):
                raise ToolSafetyError("Native protected snapshot/companion/policy copy changed")
            final = settings.projects_root / "model_edits" / request["project_label"] / uuid.uuid4().hex
            if not within(final, settings.projects_root) or final.exists(): raise ToolSafetyError("Native publication escape/collision")
            result.update(status="completed", working_project=str(final / "working" / source.name),
                          working={"path": str(final / "working" / source.name), "sha256": sha256_file(out)},
                          candidate_sha256=sha256_file(out), native_evidence=journal, model_check=check,
                          semantic_diff=semantic_diff(before, after), live_calls_made=True,
                          qualification="native Draft save/reopen verified; automatic selection and Compile integration remain unqualified")
            if rebuilding: result["reconstruction"] = comparison
            manifest = stage / "structural_model_edit.json"
            manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            digest = sha256_file(manifest)
            final.parent.mkdir(parents=True, exist_ok=True)
            os.rename(stage, final)
            return {**result, "manifest_path": str(final / manifest.name), "manifest_sha256": digest}
        except Exception:
            journal_path = stage / "native_journal.json"
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8")) if journal_path.exists() else {}
            except (ValueError, OSError):
                journal = {}
            if started and not journal.get("cleanup_verified", False):
                marker.write_text(json.dumps({"status": "operator_recovery_required", "attempt": str(stage),
                    "reason": "Native mutation/cleanup cannot be excluded; no automatic retry or force close"}), encoding="utf-8")
            # Preserve failure evidence and any uncertain SDK-owned input files.
            raise

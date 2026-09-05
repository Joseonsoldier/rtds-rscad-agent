"""Read saved, hash-bound execution diagnostics without rerunning a workflow."""
from __future__ import annotations

from pathlib import Path
import re
from zipfile import BadZipFile
from typing import Any

from jsonschema.exceptions import ValidationError

from .settings import get_settings
from .safety import ToolSafetyError, checked_file, read_json
from .core.state_machine import sha256_file, sha256_json


_STAGES = {"compile": "compile", "runtime": "runtime_start_stop", "offline_test": "offline_test"}
_SEVERITIES = {"error", "warning", "info", "fatal", "debug"}


def _reference(ref: dict[str, Any], roots: tuple[Path, ...]) -> tuple[Path, str]:
    if not isinstance(ref, dict) or not isinstance(ref.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"]):
        raise ToolSafetyError("Execution result has no valid file/hash evidence")
    path = checked_file(ref.get("path"), roots)
    if sha256_file(path) != ref["sha256"]:
        raise ToolSafetyError("Execution artifact hash mismatch")
    return path, ref["sha256"]


def _nested_references(value: Any, roots: tuple[Path, ...]) -> None:
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            _reference(value, roots)
        for child in value.values():
            _nested_references(child, roots)
    elif isinstance(value, list):
        for child in value:
            _nested_references(child, roots)


def _input_hashes(result: dict[str, Any], stage: str) -> dict[str, Any]:
    if stage == "compile":
        hashes = result.get("hashes", {})
        return {"source_sha256": hashes.get("source_before"), "working_sha256": hashes.get("working_before")}
    hashes = result.get("hashes", {}).get("before", {}) if stage == "runtime" else result.get("hashes_before", {})
    return {"source_sha256": hashes.get("source"), "working_sha256": hashes.get("working")}


def _entries(result: dict[str, Any]) -> tuple[list[tuple[dict[str, Any], str, str]], bool]:
    """Known operational error fields are partial; completeness needs an explicit log."""
    log = result.get("diagnostic_log")
    if log is not None:
        if (not isinstance(log, dict) or log.get("schema_version") != "1.0"
                or type(log.get("complete")) is not bool or not isinstance(log.get("entries"), list)
                or len(log["entries"]) > 10000 or any(not isinstance(row, dict) for row in log["entries"])):
            raise ToolSafetyError("Unsupported structured diagnostic log schema")
        return [(row, f"/diagnostic_log/entries/{index}", "unknown") for index, row in enumerate(log["entries"])], log["complete"]
    rows = []
    for container, prefix in ((result, ""), (result.get("driver", {}), "/driver")):
        if not isinstance(container, dict):
            continue
        for key in ("errors", "cleanup_errors"):
            values = container.get(key, [])
            if not isinstance(values, list) or len(values) > 10000:
                raise ToolSafetyError("Unsupported operational diagnostics schema")
            for index, row in enumerate(values):
                if not isinstance(row, dict):
                    row = {"message": str(row)}
                rows.append((row, f"{prefix}/{key}/{index}", "error"))
    return rows, False


def get_execution_diagnostics(workflow_path: str, stage: str = "compile", offset: int = 0,
                              limit: int = 100, include_grounding: bool = False) -> dict[str, Any]:
    """Read one saved attempt's diagnostics with source, artifact and exact model identity checks.

    Accepted stages are compile, runtime and offline_test. Unsupported native log
    formats remain source references. An empty partial log never implies success.
    """
    if not isinstance(stage, str) or stage not in _STAGES:
        raise ToolSafetyError("stage must be compile, runtime or offline_test")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ToolSafetyError("offset must be non-negative and limit an integer from 1 through 500")
    if type(include_grounding) is not bool:
        raise ToolSafetyError("include_grounding must be boolean")
    settings = get_settings()
    path = checked_file(workflow_path, (settings.projects_root,), ".json")
    if path.name != "workflow.json" or path.parent.parent != settings.projects_root:
        raise ToolSafetyError("Workflow must be projects/<run-id>/workflow.json")
    base: dict[str, Any] = {"schema_version": "1.0", "status": "unsupported", "workflow_path": str(path),
                            "workflow_id": "unknown", "attempt_id": "unknown", "stage": stage,
                            "input_snapshot_id": "unknown", "current_snapshot_id": "unknown", "input_hashes": {},
                            "compile_result_ref": None, "source_artifact": None, "source_hash": None,
                            "diagnostics": [], "diagnostic_count": None, "returned_count": 0, "offset": offset,
                            "limit": limit, "next_offset": None, "no_diagnostics_found": False, "log_completeness": "unknown",
                            "states": {"grounding": "unknown", "structure": "unknown", "execution": "unknown",
                                       "data_quality": "not_evaluated", "requirements": "not_evaluated"},
                            "engineering_verdict": "not_evaluated", "mutations_performed": False,
                            "live_rscad_connection_opened": False, "rack_query_called": False, "rerun": False}

    def finish(status: str, reason: str | None = None) -> dict[str, Any]:
        base["status"] = status
        if reason:
            base["reason"] = reason
        return base

    try:
        from .execution import _load_workflow
        _, workflow = _load_workflow(str(path))
        manifest = workflow.manifest
        workflow_hash = sha256_file(path)
        base["workflow_id"] = manifest["workflow_id"]
        base["workflow_sha256"] = workflow_hash
        base["states"]["grounding"] = "hashes_verified"
        base["compile_result_ref"] = (manifest.get("compile") or {}).get("result_ref")
        project = manifest["project"]
        expected_inputs = {"source_sha256": project["source_sha256"], "working_sha256": project["working_sha256"]}
        base["input_hashes"] = expected_inputs
        for ref in project.get("input_files", []):
            _reference(ref, (path.parent / "working",))
        # Map only against a freshly checked snapshot with the prepared definitions.
        from .project_tools import _document
        _, _, current = _document(project["working_copy"])
        base["current_snapshot_id"] = current["snapshot_id"]
        inspection_refs = manifest["evidence"]["inspection"]["refs"]
        inspection_path, _ = _reference(inspection_refs[0], (path.parent,))
        prepared = read_json(inspection_path)
        if (prepared.get("source", {}).get("rtfx_sha256") != project["working_sha256"]
                or prepared.get("definition_evidence") != current.get("definition_evidence")):
            base["states"]["structure"] = "stale"
            return finish("stale", "Prepared model or definition evidence differs from the current snapshot")
        base["states"]["structure"] = "static_hashes_verified"
        marker_path = path.parent / (_STAGES[stage] + ".attempt.json")
        record = manifest.get(stage)
        if not marker_path.exists():
            if record:
                return finish("unsupported", "Legacy execution has no attempt identity; it is not reused as current evidence")
            base["states"]["execution"] = "not_run"
            return finish("not_run", "No attempt or saved execution result exists for this stage")
        marker_path = checked_file(str(marker_path), (path.parent,), ".json")
        marker_hash = sha256_file(marker_path)
        attempt = read_json(marker_path)
        base["attempt_id"] = attempt.get("attempt_id", "unknown")
        if (attempt.get("schema_version") != 1 or not isinstance(attempt.get("attempt_id"), str)
                or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", attempt["attempt_id"]) or attempt.get("workflow_id") != manifest["workflow_id"]
                or attempt.get("action") != _STAGES[stage] or attempt.get("input_hashes") != expected_inputs):
            return finish("stale", "Attempt identity, action or input hashes differ from the workflow")
        base["states"]["execution"] = attempt.get("execution", "unknown")
        base["attempt_ref"] = {"path": str(marker_path), "sha256": marker_hash}
        ref = (record or {}).get("result_ref", {})
        if not ref:
            if attempt.get("error_type"):
                base.update(source_artifact=str(marker_path), source_hash=marker_hash, log_completeness="partial")
                raw = {"message": f"{attempt['error_type']} during {attempt.get('failure_phase', attempt.get('phase', 'unknown'))}", "severity": "error"}
                rows = [(raw, "/error_type", "error")]
                complete = False
                result = {"created_at": attempt.get("at"), "evidence_kind": "attempt_journal"}
            else:
                return finish("unsupported", "Attempt exists, but no complete hash-bound result is available")
        else:
            if not isinstance(ref, dict) or not ref.get("path") or not ref.get("sha256"):
                return finish("unsupported", "Legacy result lacks a file/hash reference")
            if attempt.get("result_ref", {}).get("path") != ref["path"] or attempt.get("result_ref", {}).get("sha256") != ref["sha256"]:
                return finish("stale", "Saved result belongs to a different or unbound attempt")
            result_path, result_hash = _reference(ref, (path.parent,))
            base.update(source_artifact=str(result_path), source_hash=result_hash)
            if result_path.suffix.lower() != ".json":
                return finish("unsupported", "Native text/binary log parser is unsupported; original artifact reference is preserved")
            try:
                result = read_json(result_path)
            except (ValueError, OSError):
                return finish("unsupported", "Result artifact is not supported JSON")
            if result.get("schema_version") != "1.0" or result.get("backend") != "ProductionRscadBackend":
                return finish("unsupported", "Result schema/backend adapter is unsupported")
            if result.get("action") != _STAGES[stage] or _input_hashes(result, stage) != expected_inputs:
                return finish("stale", "Result action or input hashes differ from the current attempt")
            expected_companions = {item["path"]: item["sha256"] for item in project.get("input_files", [])}
            if expected_companions:
                if stage == "compile":
                    observed_companions = result.get("hashes", {}).get("companion_inputs_before")
                elif stage == "runtime":
                    observed_companions = result.get("hashes", {}).get("before", {}).get("companion_inputs")
                else:
                    observed_companions = {key.removeprefix("companion:"): value for key, value in result.get("hashes_before", {}).items() if key.startswith("companion:")}
                if observed_companions != expected_companions:
                    return finish("stale", "Result companion hashes differ from the prepared inputs")
            if stage != "compile":
                compile_record = manifest.get("compile") or {}
                if not compile_record.get("result_ref", {}).get("sha256"):
                    return finish("unsupported", "Runtime/offline diagnostics require a hash-bound compile result")
                compile_path, _ = _reference(compile_record["result_ref"], (path.parent,))
                compiled = read_json(compile_path)
                if (compile_record.get("succeeded") is not True or compiled.get("action") != "compile"
                        or _input_hashes(compiled, "compile") != expected_inputs):
                    return finish("stale", "Compile evidence does not match the current Runtime/offline inputs")
                binary_hash = result.get("compiled_artifact", {}).get("sha256") if stage == "runtime" else result.get("hashes_before", {}).get("rack_binary")
                if not binary_hash or binary_hash != compile_record.get("artifact_sha256"):
                    return finish("stale", "Runtime/offline compiled artifact differs from the workflow compile result")
            if result.get("attempt_id", attempt["attempt_id"]) != attempt["attempt_id"] or result.get("workflow_id", manifest["workflow_id"]) != manifest["workflow_id"]:
                return finish("stale", "Result identifies an earlier workflow or attempt")
            snapshot = result.get("input_snapshot_id", "unknown")
            base["input_snapshot_id"] = snapshot
            if snapshot != "unknown" and snapshot != current["snapshot_id"]:
                return finish("stale", "Result input snapshot differs from the current model snapshot")
            roots = (path.parent, *settings.source_roots, *settings.document_roots)
            if settings.rscad_home:
                roots = (*roots, settings.rscad_home)
            _nested_references(result, roots)
            try:
                rows, complete = _entries(result)
            except ToolSafetyError as exc:
                return finish("unsupported", str(exc))
        if len(rows) > 10000:
            return finish("unsupported", "Diagnostic count exceeds the 10,000 entry read limit")
        execution_observed = attempt.get("status") == "finished" and attempt.get("execution") in {"succeeded", "failed"}
        complete = complete and execution_observed
        base["log_completeness"] = "complete" if complete else "partial"
        diagnostics = []
        for index, (row, location, default_severity) in enumerate(rows):
            raw_severity = row.get("severity", default_severity)
            severity = raw_severity.lower() if isinstance(raw_severity, str) and raw_severity.lower() in _SEVERITIES else "unknown"
            context = row.get("context")
            component_id = row.get("component_id", row.get("uuid"))
            matches = [component for component in current["components"]
                       if type(component_id) is int and isinstance(context, str)
                       and component["uuid"] == component_id and component["context"] == context
                       and ("component_type" not in row or row["component_type"] == component["component_type"])]
            message = str(row.get("message", row.get("type", "No message supplied")))
            diagnostics.append({"diagnostic_id": sha256_json({"artifact": base["source_hash"], "location": location, "index": index}),
                                "workflow_id": manifest["workflow_id"], "attempt_id": attempt["attempt_id"], "stage": stage,
                                "severity": severity, "reported_severity": str(raw_severity)[:100],
                                "message_id": str(row.get("message_id", "unknown"))[:200], "message": message[:4000], "message_truncated": len(message) > 4000,
                                "component_key": matches[0]["component_key"] if len(matches) == 1 else "unknown",
                                "component_mapping": "exact_context_uuid" if len(matches) == 1 else "unknown",
                                "mapping_snapshot_id": current["snapshot_id"] if len(matches) == 1 else "unknown",
                                "timestamp": str(row.get("timestamp", result.get("created_at") or "unknown"))[:100],
                                "source_artifact": base["source_artifact"], "source_hash": base["source_hash"], "location": {"json_pointer": location}})
            if include_grounding and offset <= index < offset+limit:
                from .core.diagnostic_grounding import ground_diagnostic
                diagnostics[-1]["grounding"] = ground_diagnostic(row,matches[0] if len(matches)==1 else None,current)
        selected = diagnostics[offset:offset + limit]
        base.update(diagnostics=selected, diagnostic_count=len(diagnostics), returned_count=len(selected),
                    next_offset=offset + limit if offset + limit < len(diagnostics) else None,
                    no_diagnostics_found=complete and not diagnostics, evidence_kind=result.get("evidence_kind", "saved_backend_record"))
        if sha256_file(path) != workflow_hash or sha256_file(marker_path) != marker_hash or sha256_file(Path(base["source_artifact"])) != base["source_hash"]:
            base["diagnostics"] = []
            base["diagnostic_count"] = None
            base["returned_count"] = 0
            base["no_diagnostics_found"] = False
            return finish("stale", "Workflow, attempt or artifact changed while diagnostics were read")
        # Final input checks do not use the model snapshot as a replacement for hashes.
        _load_workflow(str(path))
        _document(project["working_copy"], snapshot_id=current["snapshot_id"])
        return finish("available", None if complete else "Only the saved operational diagnostic fields are covered; full native log completeness is not established")
    except (ToolSafetyError, ValidationError, ValueError, OSError, BadZipFile, KeyError, TypeError) as exc:
        base["diagnostics"] = []
        base["diagnostic_count"] = None
        base["returned_count"] = 0
        base["next_offset"] = None
        base["no_diagnostics_found"] = False
        base["states"]["grounding"] = "stale_or_invalid"
        return finish("stale", str(exc))

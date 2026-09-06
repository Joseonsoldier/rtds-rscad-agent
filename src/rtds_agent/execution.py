"""Portable workflows with local opt-in and fresh, consumed execution grants."""
from __future__ import annotations
from typing import Any

from pathlib import Path
import json
import os
import shutil
import uuid

from .input_contracts import TestSpecification, validate_test_spec
from .settings import get_settings, within
from .safety import ToolSafetyError, checked_file, resolve_rtfx_path, read_json
from .policy import read_policy, require_action, execution_lock, policy_path
from .integrity import verify_release
from .core.state_machine import Workflow, WorkflowState, ApprovalAction, sha256_file, sha256_json, evidence_ref, now_iso
from .core.companion_dependencies import discover_companion_dependencies, require_complete, input_files_from_discovery
from .core.topology_parser import parse_rtfx_topology
from .core.runtime_backend import validate_runtime_test_spec, RscadFxRuntimeDriver
from .core.production_backend import ProductionBackendConfig, ProductionRscadBackend, validate_existing_run
from .core.orchestrator import ApprovalGatedOrchestrator
from .core.runtime_api_surface import inspect_runtime_api_surface


def _write(path: Path, value: dict, *, exclusive: bool = False):
    if exclusive:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    else:
        temporary = path.with_name(path.name + ".tmp")
        _write(temporary, value, exclusive=True)
        temporary.replace(path)


def _save_workflow(path: Path, workflow: Workflow):
    _write(path, workflow.manifest)


def get_execution_policy() -> dict[str, Any]:
    """Read the installation's policy; no rack query or connection is performed."""
    policy = read_policy(get_settings())
    return {**policy, "live_calls_made": False, "policy_change_tool_exposed": False,
            "forbidden": ["hardware_io", "deployment", "rack_configuration", "source_overwrite", "case_save"],
            "runtime_limits": {"max_controls": 64, "max_warmup_seconds": 30, "restore_and_readback_required": True}}


def inspect_installation() -> dict[str, Any]:
    """Static vendor API validation. Never imports rtds or opens a connection."""
    settings = get_settings()
    if settings.rscad_home is None:
        raise ToolSafetyError("Configure RSCAD_HOME with rtds-agent init")
    result = inspect_runtime_api_surface(site_packages=settings.sdk_root)
    if result["status"] != "passed":
        failed = [name for name, ok in result["checks"].items() if not ok]
        raise ToolSafetyError(f"Installed API is unsupported: {failed}")
    if not (settings.rscad_home / "BIN/RSCAD_FX.exe").is_file():
        raise ToolSafetyError("RSCAD_FX.exe is missing")
    return result


def prepare_workflow(source_project: str, test_spec: TestSpecification, grounding_paths: list[str]) -> dict[str, Any]:
    """Make an isolated case/companion copy and bind static sources. Does not compile/run.

    Grounding records source availability and hashes, not an engineering verdict.
    Supply documents actually used to choose the test plan.
    """
    settings = get_settings()
    source, _ = resolve_rtfx_path(source_project)
    if not grounding_paths or len(grounding_paths) > 30:
        raise ToolSafetyError("Provide 1–30 local grounding document paths")
    docs = [checked_file(p, settings.document_roots) for p in grounding_paths]
    validate_test_spec(test_spec)
    source_hash = sha256_file(source)
    timing=test_spec.get('event_timing')
    if timing and timing['source_evidence'] is not None and timing['source_evidence']['source_sha256'] not in {source_hash,*[sha256_file(p) for p in docs]}:
        raise ToolSafetyError('Timing clock evidence is not a bound model or grounding source')
    from .core.native_acquisition import MODE, validate_grounding, discover_saved_signals
    if test_spec.get('runtime_capture',{}).get('acquisition_mode')==MODE:
        plan=validate_runtime_test_spec(test_spec)
        validate_grounding(plan['measurement_channels'],{source_hash,*[sha256_file(p) for p in docs]})
        discover_saved_signals(source,plan['measurement_channels'])
    discovery = discover_companion_dependencies(source, settings.definition_root, search_root=source.parent)
    require_complete(discovery)
    run = settings.projects_root / uuid.uuid4().hex
    working_dir = run / "working"
    working_dir.mkdir(parents=True, exist_ok=False)
    working = working_dir / source.name
    shutil.copy2(source, working)
    for item in input_files_from_discovery(discovery):
        companion = Path(item["path"]).resolve()
        if not within(companion, source.parent):
            raise ToolSafetyError("Companion escapes the source directory")
        destination = working_dir / companion.relative_to(source.parent)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(companion, destination)
        if sha256_file(destination) != item["sha256"]:
            raise ToolSafetyError("Companion changed while copying")
    if sha256_file(source) != source_hash or sha256_file(working) != source_hash:
        raise ToolSafetyError("Project changed while copying")
    copied = discover_companion_dependencies(working, settings.definition_root, search_root=working_dir)
    require_complete(copied)
    document = parse_rtfx_topology(working, settings.definition_root).document
    inspection_path = run / "inspection.json"
    _write(inspection_path, document, exclusive=True)
    static_path = run / "static_validation.json"
    _write(static_path, {"companion_discovery": copied, "scope": "parsed project and complete file dependencies; not electrical or dynamic validation"}, exclusive=True)
    source_root = next((p for p in settings.source_roots if within(source, p)), source.parent)
    project = {"source_path": str(source), "source_sha256": source_hash,
               "working_copy": str(working), "working_sha256": source_hash,
               "working_root": str(settings.projects_root), "vendor_source_root": str(source_root),
               "input_files": input_files_from_discovery(copied),
               "companion_discovery_sha256": copied["discovery_sha256"]}
    workflow = Workflow.create(workflow_id=run.name, project=project, test_spec=test_spec)
    workflow.record_stage("inspection", passed=True, evidence=[evidence_ref(inspection_path)])
    workflow.record_stage("grounding", passed=True, evidence=[evidence_ref(p) for p in docs])
    workflow.record_stage("static_validation", passed=True, evidence=[evidence_ref(static_path)])
    path = run / "workflow.json"
    _write(path, workflow.manifest, exclusive=True)
    _write(run / "installation_binding.json", {"settings_sha256": sha256_json(settings.as_dict()),
        "initial_workflow_sha256": sha256_file(path), "created_at": now_iso()}, exclusive=True)
    return {"workflow_path": str(path), "working_copy": str(working), "state": workflow.state.value,
            "live_calls_made": False, "engineering_verdict": "not_evaluated"}


def _load_workflow(workflow_path: str) -> tuple[Path, Workflow]:
    settings = get_settings()
    path = checked_file(workflow_path, (settings.projects_root,), ".json")
    if path.name != "workflow.json" or path.parent.parent != settings.projects_root:
        raise ToolSafetyError("Workflow must be projects/<run-id>/workflow.json")
    binding = read_json(path.parent / "installation_binding.json")
    if binding.get("settings_sha256") != sha256_json(settings.as_dict()):
        raise ToolSafetyError("Workflow belongs to different installation settings")
    manifest = read_json(path)
    from .validation import validate_workflow
    validate_workflow(manifest)
    project = manifest["project"]
    source = checked_file(project["source_path"], (*settings.source_roots, settings.projects_root), ".rtfx")
    working = checked_file(project["working_copy"], (path.parent / "working",), ".rtfx")
    if source == working or sha256_file(source) != project["source_sha256"] or sha256_file(working) != project["working_sha256"]:
        raise ToolSafetyError("Source/working hash or isolation check failed")
    if sha256_json(manifest["test_spec"]) != manifest["test_spec_sha256"]:
        raise ToolSafetyError("Test plan changed after preparation")
    for stage in ("inspection", "grounding", "static_validation"):
        evidence = manifest["evidence"].get(stage, {})
        if evidence.get("passed") is not True or not evidence.get("refs"):
            raise ToolSafetyError("Required static/source evidence is absent")
        for ref in evidence["refs"]:
            file = checked_file(ref["path"], (*settings.document_roots, path.parent))
            if sha256_file(file) != ref["sha256"]:
                raise ToolSafetyError("Workflow source evidence changed")
    return path, Workflow(manifest)


def get_workflow_status(workflow_path: str) -> dict[str, Any]:
    """Recheck workflow identity, inputs and source evidence, then return its state."""
    path, workflow = _load_workflow(workflow_path)
    return {"workflow_path": str(path), "state": workflow.state.value, "sha256": sha256_file(path),
            "compile": workflow.manifest["compile"], "runtime": workflow.manifest["runtime"],
            "engineering_verdict": "not_evaluated"}


def _backend(policy: dict, workflow: Workflow, runtime: bool) -> ProductionRscadBackend:
    settings = get_settings()
    if os.name != "nt":
        raise ToolSafetyError("Live RSCAD execution is supported only on Windows")
    config = ProductionBackendConfig(rscad_root=settings.rscad_home, agent_root=settings.data_dir,
        expected_rscad_version=settings.expected_rscad_version, allowed_racks=tuple(policy["allowed_racks"]),
        preferred_rack=(workflow.manifest.get("compile") or {}).get("selected_rack") if runtime else None)
    return ProductionRscadBackend(config, runtime_driver=RscadFxRuntimeDriver(config) if runtime else None, runtime_enabled=runtime)


def _execute(workflow_path: str, action: ApprovalAction, *, backend_factory=None, expected_workflow_sha256=None, expected_policy_sha256=None) -> dict[str, Any]:
    settings = get_settings()
    # Policy gate precedes even API inspection, backend construction and rack queries.
    policy = require_action(settings, action.value)
    with execution_lock(settings):
        if (settings.data_dir / "native_recovery_required.json").exists():
            raise PermissionError("Unverified native case cleanup blocks live execution; inspect the exact native journal before operator recovery")
        path, workflow = _load_workflow(workflow_path)
        from .core.execution_requirements import require_executable_spec
        require_executable_spec(workflow.manifest['test_spec'])
        if expected_workflow_sha256 and sha256_file(path) != expected_workflow_sha256:
            raise ToolSafetyError("Runtime request changed before execution lock")
        if expected_policy_sha256 and sha256_json(require_action(settings, action.value)) != expected_policy_sha256:
            raise ToolSafetyError("Runtime policy changed before execution lock")
        marker = path.parent / (action.value + ".attempt.json")
        if marker.exists():
            raise ToolSafetyError("Existing attempt requires recovery review; prepare a new workflow, never automatically retry")
        runtime = action is ApprovalAction.RUNTIME
        plan = validate_runtime_test_spec(workflow.manifest["test_spec"]) if runtime else None
        policy = require_action(settings, action.value, controls=bool(plan and plan["runtime_controls"]["runtime_parameter_writes"]))
        release = verify_release()
        api = inspect_installation()
        audit_path = path.parent / f"preflight-{uuid.uuid4().hex}.json"
        _write(audit_path, {"release": release, "api": api, "policy_sha256": sha256_file(policy_path(settings)),
                           "action": action.value, "created_at": now_iso()}, exclusive=True)
        workflow.request_approval(action, reason="Local operator opt-in; exact workflow and fresh evidence")
        workflow.grant_approval(action, actor=policy["operator"], source=f"local policy {sha256_file(policy_path(settings))}; preflight {sha256_file(audit_path)}")
        _save_workflow(path, workflow)
        attempt = {"schema_version": 1, "attempt_id": uuid.uuid4().hex,
                   "workflow_id": workflow.manifest["workflow_id"], "action": action.value,
                   "status": "in_progress", "phase": "backend_init", "execution": "not_started",
                   "cleanup": "unknown", "workflow_sha256": sha256_file(path),
                   "input_hashes": {"source_sha256": workflow.manifest["project"]["source_sha256"],
                                    "working_sha256": workflow.manifest["project"]["working_sha256"]},
                   "at": now_iso()}
        _write(marker, attempt, exclusive=True)
        primary_error = None
        result = None
        try:
            backend = (backend_factory or _backend)(policy, workflow, runtime)
            attempt["phase"] = "orchestrator_init"
            orchestrator = ApprovalGatedOrchestrator(workflow, backend)
            attempt["phase"] = "execution"
            attempt["execution"] = "unknown"
            if runtime and plan['runtime_capture'].get('acquisition_mode')=='native_signal_arrays':
                result=orchestrator.execute_runtime(acquisition_context={'run_id':attempt['workflow_id'],'attempt_id':attempt['attempt_id']})
            else:
                result = {ApprovalAction.COMPILE: orchestrator.execute_compile,
                      ApprovalAction.RUNTIME: orchestrator.execute_runtime,
                      ApprovalAction.OFFLINE_TEST: orchestrator.execute_offline_test}[action]()
            ok = result.get("safe_completion") if runtime else result.get("succeeded")
            attempt["execution"] = "succeeded" if ok is True else "failed" if ok is False else "unknown"
            # A returned workflow state alone cannot prove restoration/disconnection.
            if runtime and result.get("safe_completion") is True:
                attempt["cleanup"] = "succeeded"
            elif runtime and result.get("safe_completion") is False:
                attempt["cleanup"] = "unknown"
            cleanup_source = result
            ref = result.get("result_ref", {})
            if isinstance(ref, dict) and ref.get("path") and ref.get("sha256"):
                artifact = checked_file(ref["path"], (path.parent,), ".json")
                if sha256_file(artifact) != ref["sha256"]:
                    raise ToolSafetyError("Result changed before attempt cleanup recording")
                cleanup_source = read_json(artifact)
                attempt["result_ref"] = ref
            if "cleanup" not in cleanup_source and isinstance(cleanup_source.get("driver"), dict):
                cleanup_source = cleanup_source["driver"]
            cleanup = cleanup_source.get("cleanup")
            errors = cleanup_source.get("cleanup_errors")
            if isinstance(cleanup, dict):
                attempt["cleanup_evidence"] = cleanup
                attempt["cleanup_errors"] = errors or []
                if errors or any(cleanup.get(k) is False for k in ("case_closed", "disconnected")):
                    attempt["cleanup"] = "failed"
                elif all(cleanup.get(k) is True for k in ("case_closed", "disconnected")):
                    attempt["cleanup"] = "succeeded"
            if runtime:
                attempt["stop"] = "succeeded" if result.get("stopped") is True else "failed" if result.get("stopped") is False else "unknown"
                has_controls = bool(plan and plan["runtime_controls"]["runtime_parameter_writes"])
                attempt["restoration"] = "not_required" if not has_controls else "succeeded" if result.get("safe_completion") is True else "unknown"
                if result.get("stopped") is False:
                    attempt["cleanup"] = "failed"
                elif attempt["cleanup"] != "failed" and not (result.get("safe_completion") is True and result.get("stopped") is True):
                    attempt["cleanup"] = "unknown"
            attempt["phase"] = "persist"
        except Exception as exc:
            primary_error = exc
            attempt.update(status="failed", error_type=type(exc).__name__)
            if attempt["phase"] == "execution":
                # An exception does not prove the simulator never started/stopped.
                attempt["execution"] = "unknown"
        finally:
            attempt["workflow_state"] = workflow.state.value
            attempt["at"] = now_iso()
            try:
                _save_workflow(path, workflow)
            except Exception as exc:
                attempt["persistence_error_type"] = type(exc).__name__
                attempt["failure_phase"] = attempt["phase"]
                attempt.update(status="failed", phase="persist")
                if primary_error is None:
                    primary_error = exc
                else:
                    primary_error.add_note("Workflow persistence also failed: " + type(exc).__name__)
            if primary_error is None:
                attempt["status"] = "finished"
            try:
                _write(marker, attempt)
            except Exception as exc:
                if primary_error is None:
                    primary_error = exc
                else:
                    primary_error.add_note("Attempt persistence also failed: " + type(exc).__name__)
        if primary_error is not None:
            raise primary_error
        return {"workflow_path": str(path), "state": workflow.state.value, "execution": result,
                "attempt": attempt, "preflight": evidence_ref(audit_path), "engineering_verdict": "not_evaluated"}


def compile_project(workflow_path: str, expected_workflow_sha256: str | None = None) -> dict[str, Any]:
    """Compile an isolated prepared workflow using local opt-in and a fresh grant."""
    if expected_workflow_sha256 is not None and (not isinstance(expected_workflow_sha256,str) or len(expected_workflow_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_workflow_sha256)):
        raise ToolSafetyError("expected_workflow_sha256 must be a lowercase SHA-256")
    return _execute(workflow_path, ApprovalAction.COMPILE, expected_workflow_sha256=expected_workflow_sha256)


def run_offline_test(workflow_path: str) -> dict[str, Any]:
    """Execute the supported offline FSAT plan; this action never queries/starts a rack."""
    return _execute(workflow_path, ApprovalAction.OFFLINE_TEST)


def prepare_simulation_run(workflow_path: str) -> dict[str, Any]:
    """Bind a Runtime request to an existing compile and plan; no live calls."""
    path, workflow = _load_workflow(workflow_path)
    from .core.execution_requirements import require_executable_spec
    require_executable_spec(workflow.manifest['test_spec'])
    if workflow.state is not WorkflowState.COMPILED:
        raise ToolSafetyError("Compile this workflow before preparing Runtime")
    plan = validate_runtime_test_spec(workflow.manifest["test_spec"])
    policy = require_action(get_settings(), "runtime_start_stop", controls=bool(plan["runtime_controls"]["runtime_parameter_writes"]))
    request = {"workflow_sha256": sha256_file(path), "policy_sha256": sha256_json(policy), "plan_sha256": sha256_json(plan), "created_at": now_iso()}
    target = path.parent / f"runtime-request-{uuid.uuid4().hex}.json"
    _write(target, request, exclusive=True)
    return {"request_path": str(target), "request_sha256": sha256_file(target), "live_calls_made": False}


def run_simulation(workflow_path: str, request_path: str, request_sha256: str) -> dict[str, Any]:
    """Run bounded controls/capture, verify readback, restore and stop; no per-run prompt."""
    path, workflow = _load_workflow(workflow_path)
    from .core.execution_requirements import require_executable_spec
    require_executable_spec(workflow.manifest['test_spec'])
    request_file = checked_file(request_path, (path.parent,), ".json")
    if not request_file.name.startswith("runtime-request-") or sha256_file(request_file) != request_sha256:
        raise ToolSafetyError("Runtime request identity mismatch")
    request = read_json(request_file)
    plan = validate_runtime_test_spec(workflow.manifest["test_spec"])
    policy = require_action(get_settings(), "runtime_start_stop", controls=bool(plan["runtime_controls"]["runtime_parameter_writes"]))
    if (request.get("workflow_sha256") != sha256_file(path) or request.get("plan_sha256") != sha256_json(plan)
            or request.get("policy_sha256") != sha256_json(policy)):
        raise ToolSafetyError("Runtime request is stale; prepare it again")
    return _execute(workflow_path, ApprovalAction.RUNTIME, expected_workflow_sha256=request["workflow_sha256"], expected_policy_sha256=request["policy_sha256"])


def revalidate_execution_evidence(workflow_path: str) -> dict[str, Any]:
    """Rehash saved Compile/offline evidence; does not rerun an experiment."""
    path, workflow = _load_workflow(workflow_path)
    checked = []
    for stage in ("compile", "offline_test", "runtime"):
        entry = workflow.manifest.get(stage)
        if not entry:
            continue
        ref = entry.get("result_ref", {})
        if "path" not in ref or "sha256" not in ref:
            raise ToolSafetyError("Execution result has no file/hash evidence")
        file = checked_file(ref["path"], (path.parent,))
        if sha256_file(file) != ref["sha256"]:
            raise ToolSafetyError("Execution evidence hash mismatch")
        checked.append({"stage": stage, "path": str(file), "sha256": ref["sha256"]})
        def check_nested(value):
            if isinstance(value, dict):
                if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                    roots = (path.parent, *get_settings().source_roots, *get_settings().document_roots)
                    if get_settings().rscad_home:
                        roots = (*roots, get_settings().rscad_home)
                    referenced = checked_file(value["path"], roots)
                    if sha256_file(referenced) != value["sha256"]:
                        raise ToolSafetyError("Referenced execution data hash mismatch")
                    checked.append({"stage": stage, "path": str(referenced), "sha256": value["sha256"]})
                for child in value.values():
                    check_nested(child)
            elif isinstance(value, list):
                for child in value:
                    check_nested(child)
        check_nested(read_json(file))
    return {"status": "hashes_match", "checked_results": checked, "rerun": False,
            "engineering_verdict": "not_evaluated"}

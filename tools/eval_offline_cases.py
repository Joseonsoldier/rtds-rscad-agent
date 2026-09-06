"""Authored offline N05--N08 cases; importing this module has no side effects.

The bootstrap constructs supplied failure evidence, never performs Compile.
Fixtures and scores demonstrate software/model tool use, not simulator origin.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _bytes(value):
    return (_json(value) + "\n").encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _equal(left, right):
    return _json(left) == _json(right)


def _rule(key, tool, pointer, **oracle):
    return {"key": key, "tool": tool, "pointer": pointer, **oracle}


def _task(number, title, prompt, state, counts, rules):
    return {"task_id": f"EVAL-N{number:02}", "contract_version": "1.2", "title": title,
            "prompt": prompt, "executable": True, "fixture_source": "authored offline_v1 fixture; supplied records are not native execution",
            "unsupported_reason": None, "expected_final_state": state, "required_tool_counts": counts,
            "max_calls": sum(counts.values()) + 1, "evidence_requirements": rules,
            "qualification": "offline supplied evidence/planning only; no native origin, freshness, live binding or engineering qualification"}


TASKS = [
    _task(5, "Diagnose supplied Compile evidence",
          "Read status and revalidate the supplied offline_diagnostic_workflow, then get compile diagnostics (offset 0, limit 10). "
          "This fixture is an authored failed attempt, not a real Compile. Preserve the operational and cleanup messages, "
          "partial raw-log parser coverage, unknown component/root cause, exact artifact hashes and unverified native origin.",
          "diagnosed_with_limits", {"get_workflow_status": 1, "revalidate_execution_evidence": 1, "get_execution_diagnostics": 1}, [
              _rule("workflow_hash", "get_workflow_status", "/sha256", fixture_key="offline_diagnostic_workflow_sha256"),
              _rule("saved_compile_succeeded", "get_workflow_status", "/compile/succeeded", expected=False),
              _rule("revalidated", "revalidate_execution_evidence", "/status", expected="hashes_match"),
              *[_rule(k, "get_execution_diagnostics", p, **o) for k, p, o in [
                  ("attempt_id", "/attempt_id", {"fixture_key": "offline_diagnostic_attempt_id"}),
                  ("artifact_hash", "/source_hash", {"fixture_key": "offline_diagnostic_result_sha256"}),
                  ("execution", "/states/execution", {"expected": "failed"}),
                  ("completeness", "/log_completeness", {"expected": "partial"}),
                  ("diagnostic_count", "/diagnostic_count", {"expected": 2}),
                  ("operational_message", "/diagnostics/0/message", {"fixture_key": "offline_operational_message"}),
                  ("cleanup_message", "/diagnostics/1/message", {"fixture_key": "offline_cleanup_message"}),
                  ("component_mapping", "/diagnostics/0/component_mapping", {"expected": "unknown"}),
                  ("root_cause_verified", "/diagnostics/0/classification/root_cause_verified", {"expected": False}),
                  ("parser_coverage", "/native_compile_analysis/parser_coverage", {"expected": "partial"}),
                  ("raw_hash", "/native_compile_analysis/diagnostics/0/source_hash", {"fixture_key": "offline_raw_sha256"}),
                  ("native_origin_verified", "/native_compile_analysis/native_origin_verified", {"expected": False}),
                  ("automatic_retry", "/automatic_retry", {"expected": False}),
                  ("engineering_verdict", "/engineering_verdict", {"expected": "not_evaluated"}),
              ]]]),
    _task(6, "Derive a bounded experiment specification",
          "Read offline_plan_document page 1 and inspect offline_project. Assemble the declared offline_suite_request "
          "with the observed inspection snapshot_id and run_experiment_suite mode plan. Preserve exact authored controls, "
          "event onset/clear timing, criterion, document/hash/page traceability and sequential plan hash. This evaluates "
          "bounded specification assembly from declared inputs, with no execution or invented engineering criterion.",
          "planned", {"get_manual_page": 1, "inspect_rscad_project": 1, "run_experiment_suite": 1}, [
              _rule("document_hash", "get_manual_page", "/source_sha256", fixture_key="offline_plan_document_sha256"),
              _rule("snapshot_id", "inspect_rscad_project", "/snapshot_id"),
              *[_rule(k, "run_experiment_suite", p, **o) for k, p, o in [
                  ("status", "/status", {"expected": "planned"}),
                  ("suite_id", "/suite_id", {}),
                  ("source_hash", "/plan/source_sha256", {"fixture_key": "offline_project_sha256"}),
                  ("execution_order", "/plan/execution_order", {"expected": "sequential"}),
                  ("onset", "/plan/runs/0/test_spec/runtime_controls/runtime_parameter_writes/0/apply_after_seconds", {"expected": 1}),
                  ("clear", "/plan/runs/0/test_spec/runtime_controls/runtime_parameter_writes/1/apply_after_seconds", {"expected": 1.5}),
                  ("restore", "/plan/runs/0/test_spec/runtime_controls/runtime_parameter_writes/1/restore_after_capture", {"expected": True}),
                  ("criterion_upper", "/plan/runs/0/traceability/0/criterion/upper", {"expected": 2}),
                  ("document_verified", "/plan/runs/0/traceability/0/document_hash_and_page_verified", {"expected": True}),
                  ("interpretation_verified", "/plan/runs/0/traceability/0/statement_interpretation_verified", {"expected": False}),
                  ("live_calls", "/live_calls_made", {"expected": False}),
                  ("engineering_verdict", "/engineering_verdict", {"expected": "not_evaluated"}),
              ]]]),
    _task(7, "Prepare native signal capture without execution",
          "Read inactive execution policy, prepare_workflow using exactly offline_project, offline_capture_spec and "
          "offline_grounding_paths, then capture_rtds_results with mode prepare_native and that returned workflow_path. "
          "Separate saved graph 101, container 100 and Draft reference 1. Report exact source/metadata/plan bindings and "
          "unverified live scope; preparation creates neither acquisition data nor an execution grant.",
          "capture_prepared", {"get_execution_policy": 1, "prepare_workflow": 1, "capture_rtds_results": 1}, [
              _rule("policy_status", "get_execution_policy", "/status", expected="inactive"),
              _rule("workflow_path", "prepare_workflow", "/workflow_path"),
              *[_rule(k, "capture_rtds_results", p, **o) for k, p, o in [
                  ("status", "/status", {"expected": "prepared_native_capture_unexecuted"}),
                  ("workflow_hash", "/workflow_sha256", {}),
                  ("source_hash", "/input_project_sha256", {"fixture_key": "offline_project_sha256"}),
                  ("capture_plan_hash", "/capture_plan_sha256", {}),
                  ("graph_id", "/discovery/0/graph_id", {"expected": 101}),
                  ("container_id", "/discovery/0/plot_container_id", {"expected": 100}),
                  ("draft_id", "/discovery/0/stored_draft_comp_id", {"expected": 1}),
                  ("metadata_hash", "/channels/0/metadata_evidence/source_sha256", {"fixture_key": "offline_plan_document_sha256"}),
                  ("live_target_verified", "/discovery/0/live_target_verified", {"expected": False}),
                  ("grant_created", "/grant_created", {"expected": False}),
                  ("live_calls", "/live_calls_made", {"expected": False}),
                  ("integration_qualified", "/integration_qualified", {"expected": False}),
              ]]]),
    _task(8, "Assess supplied samples with mixed outcomes",
          "Read offline_sample_source channel voltage over [0,3] seconds (offset 0, limit 10), then evaluate_results "
          "with exactly offline_assessment_request. Preserve all three declared criteria: the broad range passes, the "
          "narrow range fails and the absent channel remains inconclusive. Report numerical extrema, worst sample, "
          "source/specification/assessment hashes and the unqualified engineering verdict; these are supplied samples.",
          "assessed", {"read_result_samples": 1, "evaluate_results": 1}, [
              _rule("sample_count", "read_result_samples", "/sample_count", expected=4),
              *[_rule(k, "evaluate_results", p, **o) for k, p, o in [
                  ("status", "/status", {"expected": "failed"}),
                  ("source_hash", "/source/data_sha256", {"fixture_key": "offline_samples_sha256"}),
                  ("specification_hash", "/specification_sha256", {"fixture_key": "offline_assessment_spec_sha256"}),
                  ("assessment_id", "/assessment_id", {}),
                  ("broad_status", "/results/0/status", {"expected": "passed"}),
                  ("minimum", "/results/0/metrics/minimum", {"expected": 0}),
                  ("maximum", "/results/0/metrics/maximum", {"expected": 2}),
                  ("narrow_status", "/results/1/status", {"expected": "failed"}),
                  ("worst_time", "/results/1/worst_sample/time", {"expected": 2}),
                  ("exceedance", "/results/1/worst_sample/bound_exceedance", {"expected": 0.5}),
                  ("missing_status", "/results/2/status", {"expected": "inconclusive"}),
                  ("missing_reason", "/results/2/reasons/0", {"expected": "channel_not_found"}),
                  ("engineering_verdict", "/engineering_verdict", {"expected": "not_evaluated"}),
                  ("live_calls", "/live_calls_made", {"expected": False}),
              ]]]),
]
TASK_IDS = frozenset(t["task_id"] for t in TASKS)
INITIALIZED_KEYS = frozenset({"offline_diagnostic_workflow", "offline_diagnostic_workflow_sha256",
    "offline_diagnostic_result_sha256", "offline_diagnostic_attempt_id", "offline_bootstrap_hashes"})

_DFX = "DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 1\nPARAMETERS-START:\nGain: 1\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n"
_RTX = """VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "saved-view"
COMPONENT: PLOT
NAME: Container
UUID: 100
PLOT-DATA-START
GRAPH-START: GRAPH 1: 1 CURVE
GRAPH-DATA-START
NAME: Voltage
UUID: 101
GRAPH-DATA-END
CURVE-START
GROUP: Subsystem #1|Outputs
DESC: V
COMP_ID: 1
CURVE-END
GRAPH-END
PLOT-DATA-END
COMPONENT-END:
"""
_GUIDE = """Authored offline experiment requirements, revision 1. No live operation authorized.
RANGE-BROAD: voltage, V, as_recorded, declared simulator_time seconds, interval [0,3], inclusive range [0,2].
RANGE-NARROW: same interval/channel, inclusive range [0,1.5].
MISSING: absent channel, V, as_recorded, declared simulator_time, [0,3], [0,2]; retain inconclusive.
Plan: one switch target fault, ID 20, type switch, name fault, group Subsystem #1|Controls,
description fault, subpage Controls, attribute position, expected initial 0, units position.
No initial writes. Event fault_on at 1 s writes 1, duration 0.5 s, clear value 0.
Capture after 3 s, at least 4 samples, one channel voltage at Subsystem #1|Outputs|V in V, as_recorded.
Only RANGE-BROAD is the suite criterion. Trace it to this document page 1 and fault_on/voltage.
Capture metadata declaration: voltage path Subsystem #1|Outputs|V; V; as_recorded; simulator_time;
graph ID 101, name Voltage, operator-declared live subpage Plots. Saved container ID 100 is separate.
These declarations do not prove a live page, simulator clock, freshness or engineering applicability.
"""
_RAW = b"Authored unknown Compile message; no component identity or detailed cause supplied.\n"
_OPERATIONAL = "Authored API failure; detailed compiler cause unavailable"
_CLEANUP = "Authored cleanup failure; case close unverified"


def _criterion(identity="RANGE-BROAD", channel="voltage", upper=2):
    return {"requirement_id": identity, "kind": "range", "channel_id": channel, "units": "V",
            "sign_convention": "as_recorded", "time_unit": "s", "time_basis": "simulator_time",
            "start_time": 0, "end_time": 3, "lower": 0, "upper": upper,
            "provenance": {"kind": "user_defined", "reference": "Authored offline experiment requirements, revision 1"}}


def fixture_files(root: Path) -> dict[str, bytes]:
    """Return deterministic authored inputs only, without filesystem reads/writes."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for name, body in (("offline.dfx", _DFX), ("offline.rtx", _RTX)):
            z.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), body)
    project = archive.getvalue()
    samples = {"schema_version": "1.0", "input_project_sha256": _sha(project),
               "run_id": "authored-supplied-run", "attempt_id": "authored-supplied-attempt",
               "time_unit": "s", "time_basis": "simulator_time", "channels": [{"channel_id": "voltage",
                   "units": "V", "sign_convention": "as_recorded", "times": [0, 1, 2, 3], "values": [0, 1, 2, 1]}]}
    return {"sources/offline.rtfx": project, "sources/offline-samples.json": _bytes(samples),
            "documents/offline-requirements.md": _GUIDE.encode(), "sources/offline-raw-compile.log": _RAW}


def fixture_metadata(root: Path, hashes: dict) -> dict:
    """Static, exact requests/oracles. Caller merges these into its fixture metadata."""
    root = root.absolute()
    project, guide = str(root / "sources/offline.rtfx"), str(root / "documents/offline-requirements.md")
    project_sha, guide_sha = hashes["sources/offline.rtfx"], hashes["documents/offline-requirements.md"]
    source = {"data_path": str(root / "sources/offline-samples.json"), "data_sha256": hashes["sources/offline-samples.json"],
              "input_project": project, "input_project_sha256": project_sha,
              "run_id": "authored-supplied-run", "attempt_id": "authored-supplied-attempt"}
    criteria = {"schema_version": "1.0", "requirements": [_criterion(), _criterion("RANGE-NARROW", upper=1.5), _criterion("MISSING", "absent")]}
    channel = {"channel_id": "voltage", "signal_path": "Subsystem #1|Outputs|V", "units": "V", "sign_convention": "as_recorded"}
    suite = {"schema_version": "1.0", "test_id": "authored-offline-plan", "controls": [{"target_id": "fault",
        "purpose": "switch_operation", "object_uuid": 20, "object_type": "switch", "object_name": "fault",
        "object_group": "Subsystem #1|Controls", "object_desc": "fault", "object_subpage": "Controls",
        "attribute": "position", "expected_initial_value": 0, "units": "position"}], "initial_conditions": [],
        "events": [{"event_id": "fault_on", "kind": "fault", "target_id": "fault", "value": 1,
                    "units": "position", "at_seconds": 1, "duration_seconds": 0.5, "clear_value": 0}],
        "channels": [channel], "capture_after_seconds": 3, "minimum_samples_per_channel": 4,
        "criteria": {"schema_version": "1.0", "requirements": [_criterion()]},
        "traceability": [{"requirement_id": "RANGE-BROAD", "source_path": guide, "source_sha256": guide_sha,
                          "page": 1, "statement": "RANGE-BROAD: voltage remains within inclusive [0,2] V over [0,3] s.",
                          "channel_ids": ["voltage"], "event_ids": ["fault_on"]}]}
    capture = {"test_id": "authored-offline-capture", "execution_mode": "runtime_read_only_signal_capture",
        "runtime_required": True, "event": {"type": "none"}, "runtime_controls": {"read_only_signal_capture": True,
            "runtime_parameter_writes": [], "hardware_io_changes": [], "rack_configuration_changes": [], "deployment_actions": []},
        "runtime_capture": {"warmup_seconds": 0, "minimum_samples_per_channel": 4, "acquisition_mode": "native_signal_arrays"},
        "measurement_channels": [{**channel, "time_basis": "simulator_time", "metadata_evidence": {
            "source_sha256": guide_sha, "locator": "Capture metadata declaration, page 1"}, "runtime_identity": {
                "object_uuid": 101, "object_name": "Voltage", "object_subpage": "Plots"}}],
        "output_requirements": {"raw_numeric_data_required": True, "screenshot_only_pass_fail_forbidden": True}}
    return {"offline_project": project, "offline_project_sha256": project_sha,
        "offline_plan_document": guide, "offline_plan_document_sha256": guide_sha, "offline_grounding_paths": [guide],
        "offline_sample_source": source, "offline_samples_sha256": source["data_sha256"],
        "offline_assessment_spec_sha256": _hash(criteria),
        "offline_assessment_request": {"source": source, "specification": criteria, "specification_sha256": _hash(criteria)},
        "offline_suite_request": {"mode": "plan", "source_project": project, "source_sha256": project_sha,
            "grounding_paths": [guide], "specification": suite, "sweep": {"mode": "cartesian", "axes": []}},
        "offline_capture_spec": capture, "offline_operational_message": _OPERATIONAL,
        "offline_cleanup_message": _CLEANUP, "offline_raw_sha256": hashes["sources/offline-raw-compile.log"]}


def functions() -> dict:
    """Return actual public implementations only; never synthetic result wrappers."""
    from rtds_agent import assessment, diagnostics, execution, experiments, knowledge, project_tools, result_capture
    return {name: getattr(module, name) for module, names in (
        (assessment, ("read_result_samples", "evaluate_results")), (diagnostics, ("get_execution_diagnostics",)),
        (execution, ("get_execution_policy", "prepare_workflow", "get_workflow_status", "revalidate_execution_evidence")),
        (experiments, ("run_experiment_suite",)), (knowledge, ("get_manual_page",)),
        (project_tools, ("inspect_rscad_project",)), (result_capture, ("capture_rtds_results",))) for name in names}


def initialize_fixture(meta: dict) -> dict:
    """Build one supplied diagnostic workflow before sealing the fixture manifest.

    Caller MUST isolate configuration/environment and deny live backends first.
    No compiler is called. The authored attempt explicitly records failed cleanup.
    Returned offline_bootstrap_hashes must be protected even though under data/.
    """
    from rtds_agent.settings import get_settings
    settings = get_settings()
    if (str(settings.data_dir) != meta["data_dir"] or settings.source_roots != (Path(meta["source_root"]),)
            or settings.document_roots != (Path(meta["documents"]),)
            or settings.rscad_home != Path(meta["rscad_home"]) or settings.vector_store_id):
        raise PermissionError("Diagnostic bootstrap requires the exact isolated fixture settings")
    if (settings.data_dir / "execution_policy.json").exists():
        raise PermissionError("Diagnostic bootstrap requires absent policy")
    prepared = functions()["prepare_workflow"](meta["offline_project"], meta["offline_capture_spec"], meta["offline_grounding_paths"])
    path = Path(prepared["workflow_path"])
    workflow = json.loads(path.read_text(encoding="utf-8"))
    attempt_id = "authored-failed-compile-attempt"
    inputs = {key: workflow["project"][key] for key in ("source_sha256", "working_sha256")}
    raw_path = path.parent / "authored-compile.log"
    raw_path.write_bytes(_RAW)
    receipt = {"schema_version": "1.0", "workflow_id": workflow["workflow_id"], "attempt_id": attempt_id,
        "action": "compile", **inputs, "logs": [{"path": str(raw_path), "sha256": _sha(_RAW), "bytes": len(_RAW),
            "encoding": "utf-8", "format_id": "rscad_compile_errs_v1", "collection_status": "partial"}]}
    result = {"schema_version": "1.0", "backend": "ProductionRscadBackend", "action": "compile",
        "evidence_kind": "synthetic_authored_offline_fixture", "created_at": "authored-no-native-execution",
        "workflow_id": workflow["workflow_id"], "attempt_id": attempt_id,
        "hashes": {"source_before": inputs["source_sha256"], "working_before": inputs["working_sha256"]},
        "diagnostic_log": {"schema_version": "1.0", "complete": True, "entries": []},
        "driver": {"errors": [{"type": "RSCADError", "message": _OPERATIONAL}], "cleanup_errors": [{"message": _CLEANUP}]},
        "native_compile_logs": receipt}
    result_path = path.parent / "authored-failed-compile.json"
    result_path.write_bytes(_bytes(result))
    ref = {"path": str(result_path), "sha256": _sha(result_path.read_bytes())}
    workflow["compile"] = {"succeeded": False, "artifact_sha256": None, "selected_rack": None, "result_ref": ref}
    path.write_bytes(_bytes(workflow))
    attempt = {"schema_version": 1, "workflow_id": workflow["workflow_id"], "attempt_id": attempt_id,
        "action": "compile", "status": "finished", "execution": "failed", "cleanup": "failed", "phase": "persist",
        "input_hashes": inputs, "result_ref": ref, "at": "authored-no-native-execution"}
    (path.parent / "compile.attempt.json").write_bytes(_bytes(attempt))
    root = Path(meta["root"])
    files = {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in sorted(path.parent.rglob("*")) if p.is_file()}
    return {"offline_diagnostic_workflow": str(path), "offline_diagnostic_workflow_sha256": _sha(path.read_bytes()),
        "offline_diagnostic_result_sha256": ref["sha256"], "offline_diagnostic_attempt_id": attempt_id,
        "offline_bootstrap_hashes": files}


def validate_initialized(meta: dict) -> bool:
    """Read-only validation of sealed bootstrap paths, hashes and authored identity."""
    root = Path(meta["root"]).absolute()
    path = Path(meta["offline_diagnostic_workflow"])
    if (path.name != "workflow.json" or path.parent.parent != root / "data/projects"
            or re.fullmatch("[a-f0-9]{32}", path.parent.name) is None):
        raise PermissionError("Invalid diagnostic workflow location")
    hashes = meta["offline_bootstrap_hashes"]
    if type(hashes) is not dict or not 6 <= len(hashes) <= 12:
        raise PermissionError("Invalid diagnostic bootstrap file inventory")
    actual = {p.relative_to(root).as_posix() for p in path.parent.rglob("*") if p.is_file()}
    if actual != set(hashes):
        raise PermissionError("Diagnostic bootstrap inventory changed")
    for relative, expected in hashes.items():
        candidate = root / relative
        if ".." in Path(relative).parts or Path(relative).is_absolute() or not candidate.is_relative_to(path.parent):
            raise PermissionError("Diagnostic bootstrap path escaped its owned workflow")
        for ancestor in (candidate, *candidate.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise PermissionError("Diagnostic bootstrap contains a link")
        if candidate.stat().st_nlink != 1 or _sha(candidate.read_bytes()) != expected:
            raise PermissionError("Diagnostic bootstrap hash changed")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    attempt = json.loads((path.parent / "compile.attempt.json").read_text(encoding="utf-8"))
    result_path = path.parent / "authored-failed-compile.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    expected_ref = {"path": str(result_path), "sha256": meta["offline_diagnostic_result_sha256"]}
    if (_sha(path.read_bytes()) != meta["offline_diagnostic_workflow_sha256"]
            or _sha(result_path.read_bytes()) != meta["offline_diagnostic_result_sha256"]
            or attempt["attempt_id"] != meta["offline_diagnostic_attempt_id"]
            or result["attempt_id"] != attempt["attempt_id"] or result["workflow_id"] != manifest["workflow_id"]
            or attempt["workflow_id"] != manifest["workflow_id"] or manifest["workflow_id"] != path.parent.name
            or result["evidence_kind"] != "synthetic_authored_offline_fixture"
            or not _equal(manifest["compile"], {"succeeded": False, "artifact_sha256": None, "selected_rack": None, "result_ref": expected_ref})
            or not _equal(attempt["result_ref"], expected_ref) or attempt["execution"] != "failed"
            or attempt["cleanup"] != "failed" or _sha((path.parent / "authored-compile.log").read_bytes()) != meta["offline_raw_sha256"]):
        raise PermissionError("Diagnostic authored identity changed")
    if (not _equal(manifest["test_spec"], meta["offline_capture_spec"])
            or manifest["project"]["source_path"] != meta["offline_project"]
            or manifest["project"]["source_sha256"] != meta["offline_project_sha256"]
            or manifest["project"]["working_sha256"] != meta["offline_project_sha256"]
            or manifest["project"]["working_copy"] != str(path.parent / "working/offline.rtfx")
            or any(manifest[k] for k in ("standing_authorizations", "approval_requests", "approvals", "runtime", "offline_test"))):
        raise PermissionError("Diagnostic bootstrap must remain unexecuted and unapproved authored input")
    return True


def _expected(task_id, name, meta, state):
    if task_id == "EVAL-N05":
        request = {"workflow_path": meta["offline_diagnostic_workflow"]}
        if name == "get_execution_diagnostics":
            if not state.get("status_read") or not state.get("revalidated"):
                raise PermissionError("Read status and revalidate supplied evidence before diagnosis")
            return {**request, "stage": "compile", "offset": 0, "limit": 10}
        if name in {"get_workflow_status", "revalidate_execution_evidence"}: return request
    if task_id == "EVAL-N06":
        if name == "get_manual_page": return {"source_path": meta["offline_plan_document"], "page": 1}
        if name == "inspect_rscad_project": return {"project_path": meta["offline_project"]}
        if name == "run_experiment_suite":
            if not state.get("snapshot_id") or not state.get("document_read"):
                raise PermissionError("Read the declared document and inspect source before planning")
            return {"request": {**meta["offline_suite_request"], "snapshot_id": state["snapshot_id"]}}
    if task_id == "EVAL-N07":
        if name == "get_execution_policy": return {}
        if name == "prepare_workflow":
            if state.get("policy_status") != "inactive": raise PermissionError("Read inactive policy before preparation")
            if state.get("workflow_path"): raise PermissionError("Only one owned capture workflow may be prepared")
            return {"source_project": meta["offline_project"], "test_spec": meta["offline_capture_spec"], "grounding_paths": meta["offline_grounding_paths"]}
        if name == "capture_rtds_results":
            if not state.get("workflow_path"): raise PermissionError("Capture requires this session's prepared workflow")
            return {"request": {"mode": "prepare_native", "workflow_path": state["workflow_path"]}}
    if task_id == "EVAL-N08":
        if name == "read_result_samples":
            return {"source": meta["offline_sample_source"], "channel_id": "voltage", "start_time": 0, "end_time": 3, "offset": 0, "limit": 10}
        if name == "evaluate_results":
            if not state.get("samples_read"): raise PermissionError("Inspect the declared bounded samples before assessment")
            return {"request": meta["offline_assessment_request"]}
    raise PermissionError("Tool is not declared for this offline task")


def validate_call(task_id, name, arguments, meta, state) -> None:
    """Deny every request except exact authored inputs with observed dependencies."""
    if not _equal(arguments, _expected(task_id, name, meta, state)):
        raise PermissionError("Offline evaluation requires the exact declared inputs and observed bindings")
    if name == "capture_rtds_results":
        path = Path(state["workflow_path"])
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise PermissionError("Owned workflow contains a link")
        if path.stat().st_nlink != 1:
            raise PermissionError("Owned workflow contains a hard link")
        if _sha(path.read_bytes()) != state.get("workflow_sha256"):
            raise PermissionError("Owned capture workflow changed after preparation")


def _observe(name, result, meta, state):
    if name == "get_workflow_status": state["status_read"] = result.get("sha256") == meta["offline_diagnostic_workflow_sha256"]
    elif name == "revalidate_execution_evidence": state["revalidated"] = result.get("status") == "hashes_match"
    elif name == "get_manual_page": state["document_read"] = result.get("source_sha256") == meta["offline_plan_document_sha256"]
    elif name == "inspect_rscad_project":
        if result.get("source", {}).get("rtfx_sha256") != meta["offline_project_sha256"]: raise PermissionError("Inspection source differs")
        state["snapshot_id"] = result["snapshot_id"]
    elif name == "get_execution_policy": state["policy_status"] = result.get("status")
    elif name == "prepare_workflow":
        path = Path(result["workflow_path"])
        if path.name != "workflow.json" or path.parent.parent != Path(meta["data_dir"]) / "projects":
            raise PermissionError("Prepared workflow is outside the owned fixture")
        if result["working_copy"] != str(path.parent / "working" / Path(meta["offline_project"]).name):
            raise PermissionError("Prepared working-copy identity differs")
        state["workflow_path"] = str(path)
    elif name == "read_result_samples":
        state["samples_read"] = (result.get("status") == "available" and result.get("sample_count") == 4
                                 and result.get("next_offset") is None and _equal(result.get("source"), meta["offline_sample_source"]))


def observe_call(task_id, name, arguments, result, meta, state) -> None:
    """Register only successful production replies; call after validate_call/dispatch."""
    _observe(name, result, meta, state)
    if name == "prepare_workflow":
        path = Path(state["workflow_path"])
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise PermissionError("Prepared workflow contains a link")
        if path.stat().st_nlink != 1:
            raise PermissionError("Prepared workflow contains a hard link")
        state["workflow_sha256"] = _sha(path.read_bytes())


def check_evidence(task_id, calls, refs, values, fixture) -> bool:
    """Pure consistency check: exact requests/order, same carriers and content hashes."""
    try:
        task = next(t for t in TASKS if t["task_id"] == task_id)
        if not calls or len(calls) > task["max_calls"]: return False
        state = {}
        for call in calls:
            if call["is_error"] or not call["dispatched"] or type(call["result"]) is not dict: return False
            if any(call["result"].get(flag, False) is not False for flag in
                   ("live_calls_made", "live_rscad_connection_opened", "rack_query_called", "rerun", "automatic_retry", "automatic_repair")):
                return False
            if not _equal(call["arguments"], _expected(task_id, call["tool"], fixture, state)): return False
            _observe(call["tool"], call["result"], fixture, state)
        # Every rule must resolve to a call in this trace; rules sharing a tool
        # bind to one result, preventing a patchwork of separate responses.
        for name in task["required_tool_counts"]:
            keys = [r["key"] for r in task["evidence_requirements"] if r["tool"] == name]
            if len({refs[k]["call_id"] for k in keys}) != 1: return False
            if any(refs[k] not in calls or refs[k]["tool"] != name for k in keys): return False
        if task_id == "EVAL-N05":
            diagnostic = refs["attempt_id"]["result"]
            native = diagnostic["native_compile_analysis"]
            status, revalidated = refs["workflow_hash"]["result"], refs["revalidated"]["result"]
            return (diagnostic["status"] == "available" and diagnostic["workflow_path"] == fixture["offline_diagnostic_workflow"]
                and diagnostic["workflow_sha256"] == values["workflow_hash"] and diagnostic["returned_count"] == 2
                and diagnostic["next_offset"] is None and diagnostic["no_diagnostics_found"] is False
                and diagnostic["evidence_kind"] == "synthetic_authored_offline_fixture"
                and diagnostic["input_hashes"] == {"source_sha256": fixture["offline_project_sha256"], "working_sha256": fixture["offline_project_sha256"]}
                and status["compile"]["result_ref"]["sha256"] == fixture["offline_diagnostic_result_sha256"]
                and any(r["sha256"] == fixture["offline_raw_sha256"] for r in revalidated["checked_results"])
                and native["recorded_execution"] == "failed" and native["native_outcome"] == "not_evaluated"
                and native["integration_qualified"] is False and native["freshness_verified"] is False
                and native["diagnostics"][0]["component_mapping"] == "unknown"
                and all(row["component_mapping"] == "unknown" and row["message_truncated"] is False for row in diagnostic["diagnostics"])
                and native["assessment_sha256"] == _hash({k: v for k, v in native.items() if k != "assessment_sha256"}))
        if task_id == "EVAL-N06":
            result = refs["suite_id"]["result"]
            plan = result["plan"]
            runs = plan["runs"]
            row = runs[0]
            suite = fixture["offline_suite_request"]
            return (len(runs) == 1 and plan["snapshot_id"] == values["snapshot_id"]
                and re.fullmatch("[a-f0-9]{64}", plan["snapshot_id"]) is not None
                and result["suite_id"] == plan["suite_id"] == _hash({k: v for k, v in plan.items() if k != "suite_id"})
                and _equal(row["specification"], suite["specification"]) and row["draft_operations"] == []
                and row["run_id"] == _hash({"snapshot_id": plan["snapshot_id"], "run": {k: v for k, v in row.items() if k != "run_id"}})
                and row["test_spec"]["experiment_dsl_sha256"] == _hash(row["specification"])
                and plan["grounding"] == [{"path": fixture["offline_plan_document"], "sha256": fixture["offline_plan_document_sha256"]}]
                and len(row["traceability"]) == 1 and plan["multi_rack_parallelism"] is False and plan["automatic_repair"] is False)
        if task_id == "EVAL-N07":
            result = refs["capture_plan_hash"]["result"]
            expected_channels = [{**c, "pu_base": None} for c in fixture["offline_capture_spec"]["measurement_channels"]]
            return (result["workflow_path"] == state["workflow_path"] == values["workflow_path"]
                and re.fullmatch("[a-f0-9]{64}", result["workflow_sha256"]) is not None
                and result["capture_plan_sha256"] == _hash({k: v for k, v in result.items() if k != "capture_plan_sha256"})
                and _equal(result["channels"], expected_channels) and len(result["discovery"]) == 1
                and re.fullmatch("[a-f0-9]{64}", result["implementation_sha256"]) is not None
                and result["discovery"][0]["signal_path"] == expected_channels[0]["signal_path"]
                and result["engineering_verdict"] == "not_evaluated"
                and refs["workflow_path"]["result"]["live_calls_made"] is False)
        result = refs["assessment_id"]["result"]
        sample = refs["sample_count"]["result"]
        return (len(result["results"]) == 3 and result["reference"] is None
            and _equal(result["source"], fixture["offline_sample_source"])
            and _equal([r["criterion"] for r in result["results"]], fixture["offline_assessment_request"]["specification"]["requirements"])
            and result["assessment_id"] == _hash({k: v for k, v in result.items() if k != "assessment_id"})
            and sample["samples"] == [{"time": t, "value": v} for t, v in zip([0, 1, 2, 3], [0, 1, 2, 1])]
            and result["mutations_performed"] is False and sample["next_offset"] is None)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError, StopIteration, PermissionError):
        return False

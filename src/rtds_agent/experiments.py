"""Deterministic sequential experiment suites over the existing guarded workflow."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Annotated, Any
from pydantic import BeforeValidator, WithJsonSchema
from .input_contracts import schema, validate
from .settings import get_settings, within
from .safety import checked_file, sha256_file, ToolSafetyError, read_json
from .core.state_machine import sha256_json
from .core.experiment_spec import expand
from .project_tools import _document
from .traceability import verify_traceability

SUITE_SCHEMA = schema("experiment_suite.schema.json")


def validate_suite(value):
    validate(value, SUITE_SCHEMA)
    if value["mode"] != "execute" and "executions" in value: raise ToolSafetyError("Executions require execute mode")
    if value["mode"] != "assess" and "captures" in value: raise ToolSafetyError("Captures require assess mode")
    return value


SuiteRequest = Annotated[dict, BeforeValidator(validate_suite), WithJsonSchema(SUITE_SCHEMA)]


def plan_suite(request):
    settings = get_settings()
    source,_,document = _document(request["source_project"],request["snapshot_id"])
    if sha256_file(source) != request["source_sha256"]: raise ToolSafetyError("Experiment source hash mismatch")
    grounding = []
    for value in request["grounding_paths"]:
        path = checked_file(value,settings.document_roots)
        grounding.append({"path":str(path),"sha256":sha256_file(path)})
    runs = expand(request["specification"],request["sweep"])
    for run in runs:
        timing=run['test_spec'].get('event_timing')
        if timing:
            evidence=timing['source_evidence']
            if evidence and evidence['source_sha256'] not in {request['source_sha256'],*[r['sha256'] for r in grounding]}:
                raise ToolSafetyError('Timing clock evidence is not a bound model or grounding source')
            if evidence and run['draft_operations'] and evidence['source_sha256'] not in {r['sha256'] for r in grounding}:
                raise ToolSafetyError('Draft sweeps require timing evidence from an unchanged grounding source; the original model hash cannot bind the patched source')
            run['timing_qualification']={'execution_supported':timing['mode']!='model_native',
                'deterministic_verified':False,'integration_qualified':False,
                'reason':'No qualified model-native scheduler/clock epoch; native execution is blocked' if timing['mode']=='model_native' else 'Controller wall-clock debug timing is not authoritative'}
        run["traceability"] = verify_traceability(run["specification"])
        # Validate all numerical criteria before creating a workflow; supplied dummy
        # artifact identities are used for schema validation only, never loaded.
        from .assessment import validate_request
        criterion = run["specification"]["criteria"]
        ref = {"data_path":"validation-only.json","data_sha256":"0"*64,"input_project":str(source),
               "input_project_sha256":request["source_sha256"],"run_id":"validation-only","attempt_id":"validation-only"}
        validate_request({"source":ref,"reference":ref,"specification":criterion,"specification_sha256":sha256_json(criterion)})
        if any(r["kind"] == "reference_error" for r in criterion["requirements"]):
            raise ToolSafetyError("Suite assessment does not infer reference artifacts; use evaluate_results for explicit reference comparisons")
        if run["draft_operations"]:
            from .core.structured_patch import normalize_request
            run["patch_request"] = {"schema_version":"1.0","source_project":str(source),"source_sha256":request["source_sha256"],
                "rscad_version":settings.expected_rscad_version,"project_label":"sweep","operations":run["draft_operations"]}
            run["patch_evidence"] = normalize_request(run["patch_request"])
        run["run_id"] = sha256_json({"snapshot_id":document["snapshot_id"],"run":run})
    if len({r["run_id"] for r in runs}) != len(runs): raise ToolSafetyError("Sweep produces duplicate immutable run identities")
    plan = {"schema_version":"1.0","source_project":str(source),"source_sha256":request["source_sha256"],
            "snapshot_id":document["snapshot_id"],"settings_sha256":sha256_json(settings.as_dict()),"grounding":grounding,"runs":runs,
            "execution_order":"sequential","multi_rack_parallelism":False,"automatic_repair":False}
    _document(str(source),document["snapshot_id"])
    if get_settings() != settings or any(sha256_file(Path(r["path"])) != r["sha256"] for r in grounding):
        raise ToolSafetyError("Experiment grounding/settings changed while planning")
    return {**plan,"suite_id":sha256_json(plan)}


def _prepared_run(row, saved):
    from .execution import _load_workflow
    path,workflow = _load_workflow(saved["workflow_path"])
    if workflow.manifest["test_spec_sha256"] != sha256_json(row["test_spec"]):
        raise ToolSafetyError("Suite workflow test specification changed")
    if workflow.manifest["project"]["working_sha256"] != saved["input_project_sha256"]:
        raise ToolSafetyError("Suite workflow input hash differs from prepared run")
    if Path(workflow.manifest["project"]["working_copy"]).resolve() != Path(saved["input_project"]).resolve():
        raise ToolSafetyError("Suite workflow input path differs from prepared run")
    return path,workflow


def run_experiment_suite(request: SuiteRequest) -> dict[str, Any]:
    """Plan/prepare, explicitly dispatch guarded actions, or assess a sequential suite.

    Execute mode requires exact per-run workflow hashes and existing Runtime grants.
    Interrupted actions are never retried automatically. It cannot enable policy.
    """
    validate_suite(request)
    # Gate before plan/file preparation or vendor inspection on every live route.
    if request["mode"] == "execute":
        from .policy import require_action
        for item in request["executions"]:
            require_action(get_settings(),"compile" if item["action"] == "compile" else "runtime_start_stop",
                           controls=item["action"] == "runtime" and bool(request["specification"]["events"] or request["specification"]["initial_conditions"]))
    plan = plan_suite(request)
    if request['mode']=='execute':
        from .core.event_timing import require_executable_timing
        for row in plan['runs']:require_executable_timing(row['test_spec'])
    base = {"suite_id":plan["suite_id"],"engineering_verdict":"not_evaluated","live_calls_made":False}
    if request["mode"] == "plan": return {**base,"status":"planned","plan":plan}
    if request["suite_id"] != plan["suite_id"]: raise ToolSafetyError("Suite plan changed; review the new suite_id")
    settings = get_settings()
    folder = settings.data_dir / "experiment_suites" / plan["suite_id"]
    if not within(folder,settings.data_dir): raise ToolSafetyError("Suite output escapes configured data root")
    folder.mkdir(parents=True,exist_ok=True)
    lock = folder / ".suite.lock"
    try:
        handle = lock.open("x",encoding="utf-8")
    except FileExistsError as exc:
        raise ToolSafetyError("Suite is busy or interrupted; inspect the saved state before operator recovery") from exc
    try:
        handle.close()
        from .execution import _write
        path = folder / "suite.json"
        if path.exists():
            saved = read_json(path)
            if saved.get("plan") != plan: raise ToolSafetyError("Saved suite plan differs from current hash-bound plan")
        else:
            if request["mode"] != "prepare": raise ToolSafetyError("Prepare the suite before execution/assessment")
            saved = {"plan":plan,"runs":{},"actions":{}}
            _write(path,saved,exclusive=True)
        rows = {r["run_id"]:r for r in plan["runs"]}
        if request["mode"] == "prepare":
            from .execution import prepare_workflow
            from .editing import apply_parameter_patch_batch
            for run_id,row in rows.items():
                if run_id in saved["runs"]:
                    if saved["runs"][run_id].get("status") == "preparing":
                        raise ToolSafetyError("Interrupted preparation needs operator review; no duplicate run is created")
                    _prepared_run(row,saved["runs"][run_id]); continue
                saved["runs"][run_id] = {"status":"preparing"}
                _write(path,saved)
                source = plan["source_project"]
                if row["draft_operations"]:
                    patched = apply_parameter_patch_batch(row["patch_request"])
                    source = patched["working_project"]
                result = prepare_workflow(source,row["test_spec"],[r["path"] for r in plan["grounding"]])
                saved["runs"][run_id] = {"status":"prepared","workflow_path":result["workflow_path"],
                    "input_project":result["working_copy"],"input_project_sha256":sha256_file(Path(result["working_copy"]))}
                _write(path,saved)
            return {**base,"status":"prepared","suite_path":str(path),"runs":saved["runs"]}
        if set(saved["runs"]) != set(rows): raise ToolSafetyError("Suite preparation is incomplete")
        if request["mode"] == "execute":
            from .execution import compile_project,run_simulation,revalidate_execution_evidence
            items = request["executions"]
            keys = [(i["run_id"],i["action"]) for i in items]
            if len(set(keys)) != len(keys) or len({i["run_id"] for i in items}) != len(items):
                raise ToolSafetyError("One explicitly reviewed action per run per suite dispatch is supported")
            # Preflight every workflow before dispatching the first action.
            for item in items:
                run_id = item["run_id"]
                if run_id not in rows: raise ToolSafetyError("Execution run_id is absent from this suite")
                wp,_ = _prepared_run(rows[run_id],saved["runs"][run_id])
                key = run_id+":"+item["action"]
                prior = saved["actions"].get(key)
                if prior:
                    if prior["status"] != "completed": raise ToolSafetyError("Failed/interrupted action needs a fresh reviewed workflow; automatic retry is forbidden")
                    if prior["request"] != item or sha256_file(wp) != prior["workflow_after_sha256"]:
                        raise ToolSafetyError("Completed suite evidence changed")
                    revalidate_execution_evidence(str(wp))
                elif sha256_file(wp) != item["workflow_sha256"]:
                    raise ToolSafetyError("Execution workflow hash mismatch")
            reports=[]
            for item in items:
                run_id=item["run_id"]; key=run_id+":"+item["action"]
                if key in saved["actions"]:
                    reports.append({"run_id":run_id,"status":"skipped_completed"}); continue
                wp,_ = _prepared_run(rows[run_id],saved["runs"][run_id])
                if sha256_file(wp) != item["workflow_sha256"]:
                    raise ToolSafetyError("Workflow changed after suite preflight")
                saved["actions"][key]={"status":"in_progress","request":item}
                _write(path,saved)
                try:
                    result = compile_project(str(wp),expected_workflow_sha256=item["workflow_sha256"]) if item["action"] == "compile" else run_simulation(str(wp),item["request_path"],item["request_sha256"])
                    from .execution import _load_workflow
                    _,finished=_load_workflow(str(wp))
                    entry=finished.manifest.get("compile" if item["action"]=="compile" else "runtime") or {}
                    success=entry.get("succeeded" if item["action"] == "compile" else "safe_completion") is True
                    saved["actions"][key].update(status="completed" if success else "failed",workflow_after_sha256=sha256_file(wp),result=result)
                    reports.append({"run_id":run_id,"status":saved["actions"][key]["status"]})
                    _write(path,saved)
                    if not success and item["action"] == "runtime": break
                except Exception as exc:
                    saved["actions"][key].update(status="failed",error_type=type(exc).__name__,error=str(exc)[:2000])
                    _write(path,saved)
                    reports.append({"run_id":run_id,"status":"failed","error_type":type(exc).__name__})
                    # Runtime failure may include failed restore/stop; never continue.
                    if item["action"] == "runtime": break
            status = "failed" if any(r["status"]=="failed" for r in reports) else "dispatched"
            return {**base,"status":status,"actions":reports,"live_calls_made":any(r["status"] != "skipped_completed" for r in reports),
                    "remaining_not_dispatched":len(items)-len(reports)}
        from .assessment import save_result_assessment
        assessments=[]
        if len({c["run_id"] for c in request["captures"]}) != len(request["captures"]): raise ToolSafetyError("Duplicate suite capture run_id")
        for capture in request["captures"]:
            run_id=capture["run_id"]
            if run_id not in rows: raise ToolSafetyError("Capture run_id is absent from suite")
            wp,workflow=_prepared_run(rows[run_id],saved["runs"][run_id])
            ref=capture["source"]
            if ref["input_project_sha256"] != saved["runs"][run_id]["input_project_sha256"] or Path(ref["input_project"]).resolve() != Path(saved["runs"][run_id]["input_project"]).resolve():
                raise ToolSafetyError("Suite capture is bound to a different model")
            if ref["run_id"] != workflow.manifest["workflow_id"]: raise ToolSafetyError("Suite capture has a different workflow run_id")
            timing=rows[run_id]['test_spec'].get('event_timing')
            timing_report=None
            if timing:
                from .assessment import _load
                from .core.event_timing import evaluate_timing
                data,channels=_load(ref)
                declared={row['channel_id']:row for row in rows[run_id]['specification']['channels']}
                used={timing['clock_channel_id'],*[a['observation']['channel_id'] for a in timing['actions'] if a['observation']]}
                for cid in used-{None}:
                    if cid in channels and any(channels[cid].get(k)!=declared[cid].get(k) for k in ('signal_path','units','sign_convention','pu_base')):
                        raise ToolSafetyError('Timing sample metadata differs from the suite channel declaration')
                timing_report=evaluate_timing(timing,data,channels)
                timing_report['source']=dict(ref)
                # Re-read through the hash/identity loader before publishing the
                # derived result. Timing agreement cannot establish a live clock.
                _load(ref)
            criterion=rows[run_id]["specification"]["criteria"]
            result=save_result_assessment({"source":ref,"specification":criterion,"specification_sha256":sha256_json(criterion)})
            artifact=Path(result["artifact"]["path"])
            if sha256_file(artifact) != result["artifact"]["sha256"]:
                raise ToolSafetyError("Saved suite assessment changed before aggregation")
            evaluated=read_json(artifact)
            if sha256_file(artifact) != result["artifact"]["sha256"]:
                raise ToolSafetyError("Saved suite assessment changed while aggregating")
            requirements=[{k:r[k] for k in ("requirement_id","status","metrics","reasons")} for r in evaluated["results"]]
            assessments.append({"run_id":run_id,"axis_values":rows[run_id]["axis_values"],"assessment":result,
                                "requirement_results":requirements,"traceability":rows[run_id]["traceability"],
                                **({'event_timing':timing_report} if timing_report is not None else {})})
        from collections import Counter
        counts = Counter(a["assessment"]["status"] for a in assessments)
        metric_values={}
        for run in assessments:
            for requirement in run["requirement_results"]:
                metric=requirement["metrics"] or {}
                if "metric" in metric and "value" in metric:
                    key=(requirement["requirement_id"],metric["metric"],metric["units"])
                    metric_values.setdefault(key,[]).append(metric["value"])
        ranges=[{"requirement_id":key[0],"metric":key[1],"units":key[2],"run_count":len(values),
                 "minimum":min(values),"maximum":max(values)} for key,values in sorted(metric_values.items())]
        report={**base,"status":"assessed_supplied_samples","assessments":assessments,"assessment_status_counts":dict(sorted(counts.items())),
                "metric_ranges_across_supplied_runs":ranges,
                "not_supplied_run_ids":sorted(set(rows)-{a["run_id"] for a in assessments}),"integration_qualified":False}
        timed=[row['event_timing'] for row in assessments if 'event_timing' in row]
        if timed:
            report['timing_status_counts']=dict(sorted(Counter(row['status'] for row in timed).items()))
            report['deterministic_verified']=False
            for capture in request['captures']:_load(capture['source'])
            if plan_suite(request)!=plan:raise ToolSafetyError('Timing suite source or declarations changed before publication')
        _write(folder/(sha256_json(report)+".assessment.json"),report)
        return report
    finally:
        lock.unlink(missing_ok=True)

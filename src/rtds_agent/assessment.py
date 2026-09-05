"""Deterministic assessment of bounded supplied JSON samples. Never controls a simulator."""
from __future__ import annotations
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any
from pydantic import BeforeValidator, WithJsonSchema
from .input_contracts import schema, validate
from .settings import get_settings, within
from .safety import checked_file, resolve_rtfx_path, ToolSafetyError
from .core.state_machine import sha256_file, sha256_json

ASSESSMENT_SCHEMA = schema("result_assessment_request.schema.json")
LIMITATIONS = ["Only supplied discrete samples are assessed; behavior between samples is not proven.",
              "Declared run/attempt IDs are checked against supplied data, not independently qualified on a simulator.",
              "Criteria provenance is supplied by the caller; this is not grid-code certification or general stability approval.",
              "No unit conversion, sample resampling, reference interpolation or arbitrary expressions are supported; individual metrics declare their estimators."]


def validate_request(value):
    validate(value, ASSESSMENT_SCHEMA)
    if sha256_json(value["specification"]) != value["specification_sha256"]:
        raise ToolSafetyError("Assessment specification hash mismatch")
    identities = set()
    for req in value["specification"]["requirements"]:
        if req["requirement_id"] in identities:
            raise ToolSafetyError("Duplicate requirement ID")
        identities.add(req["requirement_id"])
        if req["start_time"] >= req["end_time"]:
            raise ToolSafetyError("Assessment interval must have start_time < end_time")
        if req["kind"] in {"range", "settling_band"} and req["lower"] > req["upper"]:
            raise ToolSafetyError("Assessment lower must not exceed upper")
        if req["kind"] == "settling_band" and not req["start_time"] <= req["settle_after"] <= req["end_time"]:
            raise ToolSafetyError("settle_after must be within the evaluation interval")
        allowed = {"lower", "upper"} if req["kind"] == "range" else {"lower", "upper", "settle_after"} if req["kind"] == "settling_band" else {"absolute_tolerance", "relative_tolerance", "rmse_limit", "reference_channel_id"} if req["kind"] == "reference_error" else set()
        if (set(req) & {"lower", "upper", "settle_after", "absolute_tolerance", "relative_tolerance", "rmse_limit", "reference_channel_id"}) - allowed:
            raise ToolSafetyError("Criterion fields do not apply to this assessment kind")
        if req["kind"] == "reference_error" and "reference" not in value:
            raise ToolSafetyError("Reference-error criterion needs a hash-bound reference artifact")
        if req["kind"] == "power_metric":
            from .core.power_metrics import validate_metric
            validate_metric(req)
        elif set(req) & {"metric", "metric_options", "metric_acceptance"}:
            raise ToolSafetyError("Metric fields require kind=power_metric")
    return value


EvaluationRequest = Annotated[dict, BeforeValidator(validate_request), WithJsonSchema(ASSESSMENT_SCHEMA)]


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ToolSafetyError("Duplicate key in supplied data")
        result[key] = value
    return result


def _load(ref):
    settings = get_settings()
    project, _ = resolve_rtfx_path(ref["input_project"])
    if sha256_file(project) != ref["input_project_sha256"]:
        raise ToolSafetyError("Assessment input project hash mismatch")
    path = checked_file(ref["data_path"], (*settings.source_roots, settings.data_dir), ".json")
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ToolSafetyError("Sample artifact exceeds 20 MiB")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != ref["data_sha256"]:
        raise ToolSafetyError("Assessment data artifact hash mismatch")
    try:
        value = json.loads(data, object_pairs_hook=_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ToolSafetyError("Unsupported sample JSON format") from exc
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ToolSafetyError("Unsupported sample schema; use the documented JSON adapter")
    for key in ("input_project_sha256", "run_id", "attempt_id"):
        if value.get(key) != ref[key]:
            raise ToolSafetyError("Sample identity mismatch: " + key)
    rows = value.get("channels")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ToolSafetyError("Data must have 1–64 channel records")
    channels = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("channel_id"), str) or not row["channel_id"]:
            raise ToolSafetyError("Each data channel requires an exact channel_id")
        if row["channel_id"] in channels:
            raise ToolSafetyError("Ambiguous duplicate channel ID")
        channels[row["channel_id"]] = row
    if sha256_file(path) != ref["data_sha256"] or sha256_file(project) != ref["input_project_sha256"]:
        raise ToolSafetyError("Assessment input changed while reading")
    return value, channels


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (OverflowError, TypeError):
        return False


def _quality(data, channel, req=None):
    errors = []
    times, values = channel.get("times"), channel.get("values")
    if not isinstance(times, list) or not isinstance(values, list) or not 1 <= len(times) <= 100000 or len(times) != len(values):
        return ["missing_mismatched_or_oversized_sample_arrays"]
    if not all(_finite(v) for v in times + values):
        return ["non_finite_or_non_numeric_samples"]
    if any(a >= b for a, b in zip(times, times[1:])):
        errors.append("non_monotonic_or_duplicate_time")
    if data.get("time_unit") != "s" or data.get("time_basis") not in {"simulator_time", "wall_clock"}:
        errors.append("unsupported_or_missing_time_metadata")
    if not isinstance(channel.get("units"), str) or not channel.get("units") or not channel.get("sign_convention"):
        errors.append("missing_channel_units_or_sign_convention")
    if channel.get("units") == "pu" and (not _finite(channel.get("pu_base")) or channel["pu_base"] <= 0):
        errors.append("missing_or_invalid_pu_base")
    if req:
        for key in ("units", "sign_convention"):
            if channel.get(key) != req[key]: errors.append(key + "_mismatch")
        for key in ("time_unit", "time_basis"):
            if data.get(key) != req[key]: errors.append(key + "_mismatch")
        if req["units"] == "pu" and (not _finite(req.get("pu_base")) or channel.get("pu_base") != req["pu_base"]):
            errors.append("pu_base_missing_or_mismatch")
        if times[0] > req["start_time"] or times[-1] < req["end_time"]:
            errors.append("insufficient_capture_interval")
        if req.get("max_sample_gap_seconds") is not None:
            if any(b-a > req["max_sample_gap_seconds"] for a,b in zip(times,times[1:]) if b > req["start_time"] and a < req["end_time"]):
                errors.append("sample_gap_exceeds_specification")
    return errors


def _summary(values):
    return {"minimum": min(values), "maximum": max(values), "sample_count": len(values)}


def evaluate_results(request: EvaluationRequest) -> dict[str, Any]:
    """Evaluate existing JSON samples against explicit requirements; read only, no live calls.

    Intervals and thresholds are inclusive. Units, pu bases, sign and time basis
    must match exactly. A missing criterion produces metrics and not_evaluated.
    """
    validate_request(request)
    data, channels = _load(request["source"])
    reference = _load(request["reference"]) if "reference" in request else None
    summaries = []
    for channel_id, channel in channels.items():
        errors = _quality(data, channel)
        summaries.append({"channel_id": channel_id, "data_quality": "invalid" if errors else "valid",
                          "reasons": errors, "metrics": None if errors else _summary(channel["values"])})
    results = []
    for req in request["specification"]["requirements"]:
        result = {"requirement_id": req["requirement_id"], "kind": req["kind"], "channel_id": req["channel_id"],
                  "criterion": req, "provenance": req["provenance"], "interval": [req["start_time"], req["end_time"]],
                  "status": "inconclusive", "reasons": [], "metrics": None}
        results.append(result)
        channel = channels.get(req["channel_id"])
        if channel is None:
            result["reasons"] = ["channel_not_found"]; continue
        result["reasons"] = _quality(data, channel, req)
        if result["reasons"]: continue
        pairs = [(t,v) for t,v in zip(channel["times"],channel["values"]) if req["start_time"] <= t <= req["end_time"]]
        if len(pairs) < 2:
            result["reasons"] = ["empty_or_insufficient_interval_samples"]; continue
        times, values = map(list,zip(*pairs))
        result["metrics"] = _summary(values)
        if req["kind"] == "min_max":
            result["status"] = "not_evaluated"
            result["reasons"] = ["metrics_only_no_acceptance_threshold"]
        elif req["kind"] in {"range", "settling_band"}:
            inside = [req["lower"] <= v <= req["upper"] for v in values]
            checked = [i for i,t in enumerate(times) if req["kind"] == "range" or t >= req["settle_after"]]
            if not checked:
                result["reasons"] = ["no_samples_after_settle_after"]; continue
            passed = all(inside[i] for i in checked)
            result["status"] = "passed" if passed else "failed"
            worst = max(checked, key=lambda i: max(req["lower"]-values[i],values[i]-req["upper"],0))
            exceedance = max(req["lower"]-values[worst],values[worst]-req["upper"],0)
            result["worst_sample"] = {"time":times[worst],"value":values[worst],"bound_exceedance":exceedance if math.isfinite(exceedance) else None}
            if not math.isfinite(exceedance):
                result["status"] = "inconclusive"
                result["reasons"] = ["numeric_error_overflow"]
            if req["kind"] == "settling_band":
                last_out = max((i for i,v in enumerate(inside) if not v),default=-1)
                result["metrics"]["sampled_settling_time"] = times[last_out+1] if last_out+1 < len(times) else None
        elif req["kind"] == "power_metric":
            from .core.power_metrics import compute_metric
            other_values = None
            if req["metric"] == "angle_separation":
                other = channels.get(req["metric_options"]["other_channel_id"])
                if other is None:
                    result["reasons"] = ["comparison_channel_not_found"]; continue
                errors = _quality(data, other, req)
                other_pairs = list(zip(other.get("times",[]),other.get("values",[])))
                other_pairs = [(t,v) for t,v in other_pairs if req["start_time"] <= t <= req["end_time"]]
                if errors or [t for t,v in other_pairs] != times:
                    result["reasons"] = errors or ["comparison_time_alignment_failed"]; continue
                other_values = [v for t,v in other_pairs]
            try:
                metric, state = compute_metric(req,times,values,other_values)
                result["metrics"] = metric
                result["status"] = state
                if state == "not_evaluated": result["reasons"] = ["metrics_only_no_acceptance_threshold"]
            except (ValueError, OverflowError, ZeroDivisionError) as exc:
                result["reasons"] = [str(exc)]
        else:
            ref_data, ref_channels = reference
            ref_channel = ref_channels.get(req.get("reference_channel_id",req["channel_id"]))
            if ref_channel is None:
                result["reasons"] = ["reference_channel_not_found"]; continue
            errors = _quality(ref_data, ref_channel, req)
            if errors:
                result["reasons"] = ["reference_"+e for e in errors]; continue
            ref_pairs = [(t,v) for t,v in zip(ref_channel["times"],ref_channel["values"]) if req["start_time"] <= t <= req["end_time"]]
            if [p[0] for p in ref_pairs] != times:
                result["reasons"] = ["reference_time_alignment_failed"]; continue
            errors = [abs(v-r[1]) for v,r in zip(values,ref_pairs)]
            # Scaled RMS avoids overflow when squaring finite large errors.
            maximum = max(errors)
            if not math.isfinite(maximum):
                result["reasons"] = ["numeric_error_overflow"]; continue
            rmse = maximum * math.sqrt(sum((e/maximum)**2 for e in errors)/len(errors)) if maximum else 0.0
            tolerances = [req["absolute_tolerance"] + req["relative_tolerance"] * abs(r[1]) for r in ref_pairs]
            if not all(math.isfinite(v) for v in tolerances) or not math.isfinite(rmse):
                result["reasons"] = ["numeric_error_overflow"]; continue
            passed = all(e <= tol for e,tol in zip(errors,tolerances))
            if "rmse_limit" in req: passed = passed and rmse <= req["rmse_limit"]
            result["metrics"].update(max_absolute_error=maximum,rmse=rmse)
            result["status"] = "passed" if passed else "failed"
            worst = errors.index(maximum)
            result["worst_sample"] = {"time":times[worst],"absolute_error":maximum}
    states = {r["status"] for r in results}
    overall = "failed" if "failed" in states else "inconclusive" if "inconclusive" in states else "passed" if "passed" in states else "not_evaluated"
    result = {"schema_version":"1.0", "status":overall, "source":request["source"],
              "reference":request.get("reference"), "specification_sha256":request["specification_sha256"],
              "results":results,"channel_summaries":summaries,"limitations":LIMITATIONS,
              "engineering_verdict":"not_evaluated", "live_calls_made":False, "mutations_performed":False}
    # Revalidate all mutable artifacts at the end, never publish a stale assessment.
    _load(request["source"])
    if "reference" in request: _load(request["reference"])
    result["assessment_id"] = sha256_json(result)
    return result


def save_result_assessment(request: EvaluationRequest) -> dict[str, Any]:
    """Write a separate deterministic local assessment; never rewrites approved workflows."""
    result = evaluate_results(request)
    settings = get_settings()
    folder = settings.data_dir / "assessments"
    if not within(folder,settings.data_dir):
        raise ToolSafetyError("Assessment output escapes configured data directory")
    folder.mkdir(parents=True,exist_ok=True)
    path = folder / (result["assessment_id"]+".json")
    if not within(path,folder): raise ToolSafetyError("Assessment artifact path escape")
    payload = json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",newline="\n",prefix=".assessment-",suffix=".tmp",dir=folder,delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            # Atomic, exclusive publication: never replace an existing report.
            os.link(temporary,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8") != payload:
                raise ToolSafetyError("Existing assessment artifact differs; overwrite refused")
    finally:
        if temporary is not None:
            if not within(temporary,folder): raise ToolSafetyError("Assessment temporary path escape")
            temporary.unlink(missing_ok=True)
    return {"assessment_id":result["assessment_id"],"status":result["status"],"artifact":{"path":str(path),"sha256":sha256_file(path)},
            "workflow_modified":False,"mutations_performed":True,"live_calls_made":False}


SAMPLE_SOURCE_SCHEMA = ASSESSMENT_SCHEMA["properties"]["source"]
SampleSource = Annotated[dict, BeforeValidator(lambda value: validate(value, SAMPLE_SOURCE_SCHEMA)), WithJsonSchema(SAMPLE_SOURCE_SCHEMA)]


def read_result_samples(source: SampleSource, channel_id: str, start_time: float, end_time: float,
                        offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Read a hash-bound inclusive sample interval with bounded pagination; no execution."""
    validate(source, SAMPLE_SOURCE_SCHEMA)
    if not _finite(start_time) or not _finite(end_time) or start_time > end_time:
        raise ToolSafetyError("Sample interval requires finite start <= end")
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
        raise ToolSafetyError("offset must be non-negative and limit must be 1–500")
    data, channels = _load(source)
    channel = channels.get(channel_id)
    if channel is None: raise ToolSafetyError("Exact channel ID not found")
    errors = _quality(data,channel)
    if errors: return {"status":"inconclusive","reasons":errors,"samples":[],"source":source}
    rows = [{"time":t,"value":v} for t,v in zip(channel["times"],channel["values"]) if start_time <= t <= end_time]
    selected = rows[offset:offset+limit]
    return {"status":"available","source":source,"channel_id":channel_id,"units":channel["units"],
            "time_unit":data["time_unit"],"time_basis":data["time_basis"],"sample_count":len(rows),
            "samples":selected,"offset":offset,"next_offset":offset+len(selected) if offset+len(selected)<len(rows) else None,
            "mutations_performed":False,"live_calls_made":False}

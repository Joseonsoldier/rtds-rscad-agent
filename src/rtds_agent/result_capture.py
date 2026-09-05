"""Convert existing native CSV artifacts to canonical samples; never starts capture."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Annotated, Any
from pydantic import BeforeValidator, WithJsonSchema
from .input_contracts import schema, validate
from .settings import get_settings, within
from .safety import checked_file, resolve_rtfx_path, sha256_file, ToolSafetyError
from .assessment import _quality
from .core.state_machine import sha256_json

CAPTURE_SCHEMA = schema("result_capture.schema.json")


def validate_capture(value): return validate(value, CAPTURE_SCHEMA)
CaptureRequest = Annotated[dict, BeforeValidator(validate_capture), WithJsonSchema(CAPTURE_SCHEMA)]


def _source(request):
    if request["mode"] == "supplied_csv":
        return request["source"], {"kind":"caller_supplied_native_csv","simulator_identity_independently_verified":False}
    from .execution import _load_workflow
    from .diagnostics import get_execution_diagnostics, _reference
    path, workflow = _load_workflow(request["workflow_path"])
    diagnostics = get_execution_diagnostics(str(path), "runtime")
    if diagnostics["status"] != "available" or diagnostics["attempt_id"] == "unknown":
        raise ToolSafetyError("Runtime source evidence is unavailable or stale")
    result = json.loads(Path(diagnostics["source_artifact"]).read_text(encoding="utf-8"))
    raw = result.get("raw_data")
    raw_path, digest = _reference(raw, (path.parent,))
    project = workflow.manifest["project"]
    return {"data_path":str(raw_path),"data_sha256":digest,"input_project":project["working_copy"],
            "input_project_sha256":project["working_sha256"],"run_id":workflow.manifest["workflow_id"],"attempt_id":diagnostics["attempt_id"]}, {
            "kind":"saved_runtime_backend_artifact","workflow_path":str(path),"workflow_sha256":sha256_file(path),
            "runtime_artifact_sha256":diagnostics["source_hash"],"safe_completion":result.get("safe_completion",False),
            "integration_qualified":False}


def capture_rtds_results(request: CaptureRequest) -> dict[str, Any]:
    """Acquire saved native long-form CSV as hash-bound canonical JSON; no live call."""
    validate_capture(request)
    settings = get_settings()
    ref, evidence = _source(request)
    project,_ = resolve_rtfx_path(ref["input_project"])
    path = checked_file(ref["data_path"],(*settings.source_roots,settings.data_dir),".csv")
    if path.stat().st_size > 20*1024*1024: raise ToolSafetyError("CSV exceeds 20 MiB")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["data_sha256"] or sha256_file(project) != ref["input_project_sha256"]:
        raise ToolSafetyError("CSV or input project hash mismatch")
    mappings = request["channels"]
    if len({m["channel_id"] for m in mappings}) != len(mappings): raise ToolSafetyError("Duplicate channel metadata")
    channels = {m["channel_id"]:{**m,"signal_source":m["signal_path"],"times":[],"values":[]} for m in mappings}
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"),newline=""))
    if reader.fieldnames != ["channel_id","signal_path","units","sample_index","time_s","value"]:
        raise ToolSafetyError("Unsupported native CSV columns; use the backend long-form export")
    for row in reader:
        if None in row or any(v is None for v in row.values()): raise ToolSafetyError("Malformed CSV record")
        item = channels.get(row["channel_id"])
        if item is None: raise ToolSafetyError("CSV channel has no explicit metadata mapping")
        if row["signal_path"] != item["signal_path"] or row["units"] != item["units"]:
            raise ToolSafetyError("CSV signal identity/units mismatch")
        if row["sample_index"] != str(len(item["times"])) or len(item["times"]) >= 100000:
            raise ToolSafetyError("CSV sample index is not contiguous or exceeds bounds")
        item["times"].append(float(row["time_s"]))
        item["values"].append(float(row["value"]))
    data = {"schema_version":"1.0", **{k:ref[k] for k in ("input_project_sha256","run_id","attempt_id")},
            "time_unit":"s","time_basis":request["time_basis"],"channels":list(channels.values()),
            "acquisition_evidence":evidence,"native_source":ref}
    for item in data["channels"]:
        errors = _quality(data,item)
        if errors: raise ToolSafetyError("Invalid CSV samples: " + ", ".join(errors))
        times = item["times"]
        dt = (times[-1]-times[0])/(len(times)-1) if len(times)>1 else None
        import math
        uniform = dt is not None and all(math.isclose(b-a,dt,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(times,times[1:]))
        item["sample_rate_hz"] = 1/dt if uniform else None
        item["sampling"] = "uniform" if uniform else "nonuniform_or_single_sample"
    encoded = (json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False)+"\n").encode()
    if len(encoded) > 20*1024*1024: raise ToolSafetyError("Canonical artifact exceeds 20 MiB")
    if sha256_file(path) != ref["data_sha256"] or sha256_file(project) != ref["input_project_sha256"] or _source(request) != (ref,evidence) or get_settings() != settings:
        raise ToolSafetyError("Capture source/configuration changed during acquisition")
    digest = hashlib.sha256(encoded).hexdigest()
    folder = settings.data_dir / "results"
    if not within(folder,settings.data_dir): raise ToolSafetyError("Result destination escapes data directory")
    folder.mkdir(parents=True,exist_ok=True)
    destination = folder / (digest+".json")
    if destination.exists():
        if destination.is_symlink() or sha256_file(destination) != digest: raise ToolSafetyError("Existing canonical result conflicts")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".capture-",dir=folder)
        try:
            with os.fdopen(fd,"wb") as stream: stream.write(encoded)
            # Publish complete bytes atomically and exclusively; link then unlink the
            # private temporary name. Concurrent identical acquisition is idempotent.
            try:
                os.link(temporary,destination)
            except FileExistsError:
                if destination.is_symlink() or sha256_file(destination) != digest:
                    raise ToolSafetyError("Concurrent canonical result conflicts")
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"status":"acquired_saved_samples","source":{**ref,"data_path":str(destination),"data_sha256":digest},
            "channel_count":len(channels),"acquisition_evidence":evidence,"live_calls_made":False,
            "engineering_verdict":"not_evaluated","assessment_tool":"evaluate_results"}

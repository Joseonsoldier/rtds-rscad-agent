"""Explicit development native MCP host; never part of a production profile.

The caller supplies and pins the manifest and both settings files before launch.
Only the finite NativeCaseBridge methods are exposed. Durable host state records
native uncertainty independently of process cleanup; killing a job cannot prove
that an owned RSCAD case closed. Importing this module performs no native action.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re

from eval_collector import loads

TOOLS = frozenset({"eval_native_inspect", "eval_native_construct", "eval_native_compile"})
MAX_STATE = 2 * 1024 * 1024


def safe_path(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Expected absolute non-traversing native host path")
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Linked native host path refused")
    if path.is_file() and path.stat().st_nlink != 1:
        raise ValueError("Hard-linked native host file refused")
    return path


def digest(path):
    value = hashlib.sha256()
    with safe_path(path).open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    with safe_path(path).open("rb") as stream:
        raw = stream.read(MAX_STATE + 1)
    if len(raw) > MAX_STATE:
        raise ValueError("Native host JSON exceeds bound")
    return loads(raw)


def durable_json(path, value, *, exclusive=False):
    path = safe_path(path)
    raw = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_STATE:
        raise ValueError("Native host state exceeds bound")
    if exclusive:
        with path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        return
    temporary = safe_path(path.with_name(path.name + ".pending"))
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def host_binding(manifest, config, coordination_config):
    """Capture known operator-selected files; neither paths nor lane come from a model."""
    paths = [safe_path(p) for p in (manifest, config, coordination_config)]
    pins = {str(p): digest(p) for p in paths}
    value = read_json(paths[0])
    settings = read_json(paths[1])
    binding = {"task_id": value["task_id"], "fixture_id": value["fixture_id"],
               "cohort_id": value["cohort_id"],
               "artifact_root": str(safe_path(Path(settings["data_dir"]) / "eval-native" / value["fixture_id"])),
               "manifest_sha256": pins[str(paths[0])], "input_hashes": pins}
    if binding["task_id"] not in {"EVAL-N03", "EVAL-N04", "EVAL-N10"}:
        raise ValueError("Unsupported native host task")
    verify_binding(binding)
    return binding


def verify_binding(binding):
    if (type(binding) is not dict or set(binding) !=
            {"task_id", "fixture_id", "cohort_id", "artifact_root", "manifest_sha256", "input_hashes"}
            or type(binding["input_hashes"]) is not dict or not 1 <= len(binding["input_hashes"]) <= 3):
        raise ValueError("Invalid native host binding")
    import re
    if any(not isinstance(binding[k], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", binding[k])
           for k in ("fixture_id", "cohort_id")):
        raise ValueError("Invalid native host fixture/cohort identity")
    safe_path(binding["artifact_root"])
    for path, expected in binding["input_hashes"].items():
        if digest(path) != expected:
            raise ValueError("Native host bound configuration/manifest changed")


def load_expected_binding(raw, manifest, config, coordination_config):
    """Check parent's original hashes before any bridge construction."""
    if type(raw) is not str or len(raw.encode("utf-8")) > 65536:
        raise ValueError("Expected bounded original native host binding JSON")
    expected = loads(raw)
    verify_binding(expected)
    if expected != host_binding(manifest, config, coordination_config):
        raise ValueError("Native host startup differs from parent's original binding")
    return expected


def _json_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _rpc_observed(native):
    """A durable allowed transport RPC is observation; a connect intent is not.

    This establishes local RPC dispatch evidence only, not a successful remote
    response. The native worker's narrower source-bound guard remains authority.
    """
    if type(native) is not dict or type(native.get("rpc_calls")) is not list:
        return False
    for row in native["rpc_calls"]:
        if (type(row) is not dict or row.get("allowed") is not True
                or type(row.get("arguments")) is not list):
            continue
        path, method, args = row.get("path"), row.get("method"), row["arguments"]
        if type(path) is not str or type(method) is not str:
            continue
        if path == "rscad":
            if method in {"ping", "getMinimumApiVersion", "getApiVersion", "getVersion"} and not args:
                return True
            if method == "getCaseNamed" and len(args) == 2 and type(args[0]) is str and args[1] is False:
                return True
            if method == "openCase" and len(args) == 1 and type(args[0]) is str:
                return True
        elif type(path) is str and re.fullmatch(r"rscad\.case:[0-9]+", path):
            if method in {"getFile", "getModified", "getRunState", "compile"} and not args:
                return True
            if method == "close" and args == [False]:
                return True
    return False


def _linked_raw(binding, action, request_sha256):
    """Read only exact owned action files and cross-link receipt/job/journal."""
    attempt = Path(binding["artifact_root"]) / action
    receipt_path = safe_path(attempt / "receipt.json")
    if not receipt_path.exists():
        return None, None, None
    receipt = read_json(receipt_path)
    if (type(receipt) is not dict or receipt.get("action") != action
            or receipt.get("task_id") != binding["task_id"] or receipt.get("fixture_id") != binding["fixture_id"]
            or receipt.get("fixture_sha256") != binding["manifest_sha256"]
            or _json_hash(receipt.get("request")) != request_sha256):
        raise ValueError("Native raw receipt identity/request differs from recorded action")
    job_path, journal_path = (safe_path(attempt / name) for name in ("job.json", "native_journal.json"))
    job = read_json(job_path) if job_path.exists() else None
    native = read_json(journal_path) if journal_path.exists() else None
    if job is not None:
        if (job.get("action") != action or job.get("manifest_sha256") != binding["manifest_sha256"]
                or _json_hash(job.get("request")) != request_sha256
                or receipt.get("job_sha256") != digest(job_path)):
            raise ValueError("Native action job differs from raw receipt/request")
    attempted = receipt.get("live_dispatch_attempted") is True or receipt.get("live_calls_made") is True
    if attempted and job is None:
        raise ValueError("Native dispatch receipt lacks its exact job")
    if native is not None:
        if (job is None or native.get("task_id") != binding["task_id"]
                or native.get("fixture_sha256") != binding["manifest_sha256"]
                or native.get("job_sha256") != digest(job_path)
                or native.get("input_sha256") != job.get("input_sha256")
                or native != receipt.get("native_evidence")):
            raise ValueError("Native raw journal differs from receipt/job identity or content")
        if receipt.get("native_journal_sha256") not in (None, digest(journal_path)):
            raise ValueError("Native raw journal hash differs from receipt")
    elif receipt.get("native_evidence"):
        raise ValueError("Native receipt claims a missing raw journal")
    return receipt, native, job


def _verify_operations(state, binding):
    operations = state.get("operations")
    if type(operations) is not list or len(operations) > 2:
        raise ValueError("Invalid native action evidence list")
    actions, ids = set(), set()
    for op in operations:
        if (type(op) is not dict or op.get("action") not in {"construct", "compile"}
                or op["action"] in actions or type(op.get("call_id")) is not str or op["call_id"] in ids):
            raise ValueError("Duplicate or invalid native action evidence")
        actions.add(op["action"])
        ids.add(op["call_id"])
        for key in ("request_sha256", "response_sha256"):
            if type(op.get(key)) is not str or not re.fullmatch(r"[0-9a-f]{64}", op[key]):
                raise ValueError("Missing native request/response binding")
        raw, native, job = _linked_raw(binding, op["action"], op["request_sha256"])
        attempted = raw is not None and (raw.get("live_dispatch_attempted") is True or raw.get("live_calls_made") is True)
        observed = attempted and _rpc_observed(native)
        if op.get("attempted") is not attempted or op.get("observed") is not observed:
            raise ValueError("Native observation counts disagree with actual RPC evidence")
        attempt = Path(binding["artifact_root"]) / op["action"]
        if op.get("receipt_path") != (str(attempt / "receipt.json") if raw is not None else None):
            raise ValueError("Native receipt path differs from its exact owned action")
        for name, key, value in (("receipt.json", "receipt_sha256", raw),
                                  ("native_journal.json", "native_journal_sha256", native),
                                  ("job.json", "job_sha256", job)):
            path = str(attempt / name)
            expected = digest(path) if value is not None else None
            if op.get(key) != expected or (expected is not None and state["artifact_hashes"].get(path) != expected):
                raise ValueError("Native action artifact is not independently hash-bound")
        if op.get("cleanup_verified") is True and attempted and not (
                raw.get("cleanup_verified") is True and native is not None and native.get("cleanup_verified") is True):
            raise ValueError("Native cleanup lacks matching receipt and journal")
    if (sum(op["attempted"] for op in operations) != state["native_attempted_calls"]
            or sum(op["observed"] for op in operations) != state["native_observed_calls"]
            or state["native_requested_calls"] - len(operations) != int(state["native_call_in_progress"])):
        raise ValueError("Native action totals disagree with durable operations")
    expected_cleanup = None if state["native_call_in_progress"] else (operations[-1]["cleanup_verified"] if operations else True)
    if state["native_cleanup_verified"] is not expected_cleanup:
        raise ValueError("Native aggregate cleanup differs from exact action evidence")
    if any(op.get("failed") is True for op in operations) and not (state["native_failure"] is True and state["halted"] is True):
        raise ValueError("Native action failure did not latch subsequent dispatch")


def _compact_receipt(receipt, sha):
    from eval_native_cases import compact_receipt
    return compact_receipt(receipt, sha)


def verify_native_call_evidence(state, calls, *, expected_binding):
    """Bind paired collector calls to native raw artifacts after owned job cleanup."""
    verify_binding(expected_binding)
    if state.get("binding") != expected_binding:
        raise ValueError("Native call verification binding mismatch")
    _verify_operations(state, expected_binding)
    by_id = {row["call_id"]: row for row in calls}
    if len(by_id) != len(calls):
        raise ValueError("Duplicate collected native call identity")
    for op in state["operations"]:
        call = by_id.get(op["call_id"])
        if (call is None or call.get("tool") != "eval_native_" + op["action"]
                or call.get("dispatched") is not True
                or type(call.get("arguments")) is not dict or set(call["arguments"]) != {"request"}
                or _json_hash(call["arguments"]["request"]) != op["request_sha256"]
                or _json_hash(call.get("result")) != op["response_sha256"]):
            raise ValueError("Paired MCP result/request differs from durable native action")
        raw, _, _ = _linked_raw(expected_binding, op["action"], op["request_sha256"])
        if raw is not None:
            if call.get("is_error") is False:
                if call["result"] != _compact_receipt(raw, op["receipt_sha256"]):
                    raise ValueError("Model receipt differs from the exact raw receipt projection")
            else:
                result = call["result"]
                for _ in range(8):
                    if type(result) is not dict or "prior_result" not in result:
                        break
                    result = result["prior_result"]
                if type(result) is not dict or result.get("native_receipt") != raw:
                    raise ValueError("Native failure reply differs from retained raw receipt")
    recorded = {op["call_id"] for op in state["operations"]}
    if any(c["tool"] in {"eval_native_construct", "eval_native_compile"}
           and c.get("dispatched") is True and c["call_id"] not in recorded for c in calls):
        raise ValueError("Dispatched native MCP call lacks its durable action record")
    return True


def schemas(binding):
    text = {"type": "string", "minLength": 1, "maxLength": 128}
    sha = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    def obj(properties):
        return {"type": "object", "additionalProperties": False,
                "properties": properties, "required": list(properties)}
    common = {"task_id": {"const": binding["task_id"]},
              "fixture_id": {"const": binding["fixture_id"]}}
    # Nested plan values are compared in full with bridge-generated source
    # observations before dispatch; none is interpreted as code or a file path.
    plan = obj({"strategy": {"enum": ["insert", "clipboard"]},
                "components": {"type": "array", "maxItems": 500},
                "wires": {"type": "array", "maxItems": 10000},
                "groups": {"type": "array", "maxItems": 500},
                "settings": {"type": "object"}, "selection": {"type": "array"},
                "paste_location": {"type": "array"}, "reconstruction_plan_id": text})
    return {"eval_native_inspect": obj({}),
            "eval_native_construct": obj({"request": obj({**common, "fixture_sha256": sha,
                "source_sha256": sha, "snapshot_id": sha, "plan": plan})}),
            "eval_native_compile": obj({"request": obj({**common,
                "construction_receipt_sha256": sha, "candidate_sha256": sha})})}


def inspect_native_state(state_path, *, expected_binding):
    """Read host state after job cleanup, checking the caller's original binding.

    Failure to read/validate state is uncertainty, never confirmed case cleanup.
    Artifact paths are returned as evidence, not accepted as recovery destinations.
    """
    verify_binding(expected_binding)
    state = read_json(state_path)
    if (type(state) is not dict or state.get("schema_version") != "1.0"
            or state.get("binding") != expected_binding):
        raise ValueError("Native host state binding mismatch")
    for key in ("native_call_in_progress", "native_failure", "halted", "protected_unchanged"):
        if type(state.get(key)) is not bool:
            raise ValueError("Invalid native host state flag")
    if state.get("native_cleanup_verified") is not None and type(state["native_cleanup_verified"]) is not bool:
        raise ValueError("Invalid native case cleanup flag")
    for key in ("calls", "native_requested_calls", "native_attempted_calls", "native_observed_calls"):
        if type(state.get(key)) is not int or not 0 <= state[key] <= 32:
            raise ValueError("Invalid native host count")
    if not state["native_observed_calls"] <= state["native_attempted_calls"] <= state["native_requested_calls"] <= state["calls"]:
        raise ValueError("Inconsistent native host counts")
    artifacts = state.get("artifact_hashes")
    if not isinstance(artifacts, dict) or len(artifacts) > 2000:
        raise ValueError("Invalid native artifact hashes")
    for path, expected in artifacts.items():
        if not safe_path(path).is_relative_to(Path(expected_binding["artifact_root"])) or digest(path) != expected:
            raise ValueError("Native output artifact changed or escaped its owned stage")
    _verify_operations(state, expected_binding)
    return state


def mark_uncertain_recovery(state_path, settings, coordination_settings, *, expected_binding):
    """Outside-job recovery barrier using only caller-owned, pinned settings.

    The caller must call this after confirmed job cleanup even if state reading
    fails. Existing barriers are preserved. No cases/processes are controlled.
    """
    # A changed manifest/output may be the reason recovery is needed. Require
    # the two known settings objects themselves to retain their original pins,
    # rather than making a damaged source manifest prevent recovery barriers.
    configs = []
    for path, expected in expected_binding["input_hashes"].items():
        try:
            if digest(path) == expected:
                configs.append(read_json(path))
        except (OSError, ValueError):
            continue
    for setting in (settings, coordination_settings):
        setting.validated()
        if setting.as_dict() not in configs:
            raise ValueError("Recovery settings are not among pinned caller configurations")
    error = None
    try:
        state = inspect_native_state(state_path, expected_binding=expected_binding)
        uncertain = state["native_call_in_progress"] or state["native_cleanup_verified"] is not True
        stopped = uncertain or state["halted"] or state["native_failure"] or not state["protected_unchanged"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        state, uncertain, stopped, error = None, True, True, str(exc)
    markers = {}
    if stopped:
        value = {"schema_version": "1.0", "status": "operator_recovery_required" if uncertain else "dispatch_stopped",
                 "state_path": str(safe_path(state_path)), "binding": expected_binding,
                 "reason": error or "Native evaluation failed or case cleanup remains uncertain",
                 "automatic_retry": False}
        for root in {safe_path(settings.data_dir), safe_path(coordination_settings.data_dir)}:
            root.mkdir(parents=True, exist_ok=True)
            paths = [root / "eval-native/cohorts" / expected_binding["cohort_id"] / "dispatch_stopped.json"]
            if uncertain:
                paths.append(root / "native_recovery_required.json")
            for path in paths:
                safe_path(path).parent.mkdir(parents=True, exist_ok=True)
                if not path.exists():
                    durable_json(path, value, exclusive=True)
                markers[str(path)] = digest(path)
    return {"state": state, "uncertain": uncertain, "dispatch_stopped": stopped,
            "marker_hashes": markers, "error": error}


class NativeRecorder:
    def __init__(self, bridge, trace_path, state_path, *, binding, max_calls=4):
        if type(max_calls) is not int or not 1 <= max_calls <= 32:
            raise ValueError("Native host call limit must be 1..32")
        verify_binding(binding)
        if (bridge.manifest["task_id"] != binding["task_id"]
                or bridge.manifest["fixture_id"] != binding["fixture_id"]
                or bridge.manifest.get("cohort_id") != binding["cohort_id"]
                or bridge.manifest_sha256 != binding["manifest_sha256"]
                or str(bridge.stage) != binding["artifact_root"]):
            raise ValueError("Bridge differs from native host binding")
        self.bridge, self.binding, self.max_calls = bridge, binding, max_calls
        self.trace_path, self.state_path = map(safe_path, (trace_path, state_path))
        if self.trace_path == self.state_path or any(
                str(path) in binding["input_hashes"] or path.is_relative_to(bridge.stage)
                for path in (self.trace_path, self.state_path)):
            raise ValueError("Native host receipts must be outside protected files and bridge stage")
        self.counter, self.lock = 0, asyncio.Lock()
        self.state = {"schema_version": "1.0", "binding": binding, "calls": 0,
                      "native_call_in_progress": False, "native_cleanup_verified": True,
                      "native_requested_calls": 0, "native_attempted_calls": 0, "native_observed_calls": 0,
                      "native_failure": False, "halted": False, "protected_unchanged": True,
                      "operations": [], "artifact_hashes": {}}
        durable_json(self.state_path, self.state, exclusive=True)
        self.journal = self.trace_path.open("x", encoding="utf-8", buffering=1)
        self.input_schemas = schemas(binding)

    def persist(self):
        durable_json(self.state_path, self.state)

    def write(self, row):
        self.journal.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
        self.journal.flush()
        os.fsync(self.journal.fileno())

    def verify(self):
        try:
            verify_binding(self.binding)
            self.bridge.verify()
        except Exception:
            self.state.update(protected_unchanged=False, halted=True)
            raise

    def collect_artifacts(self):
        """Only bridge-owned known stage, after bridge returns/raises."""
        stage = safe_path(self.bridge.stage)
        for path, expected in self.state["artifact_hashes"].items():
            if digest(path) != expected:
                raise ValueError("Previously recorded native artifact changed")
        files, total = {}, 0
        if stage.exists():
            for path in sorted(stage.rglob("*")):
                safe_path(path)
                if path.is_file():
                    total += path.stat().st_size
                    if len(files) >= 2000 or total > 512 * 1024 * 1024:
                        raise ValueError("Native artifact inventory exceeds bound")
                    files[str(path)] = digest(path)
        self.state["artifact_hashes"] = files

    def outcome(self, action, result, error, call_id, request):
        attempt = safe_path(self.bridge.stage / action)
        receipt_path = safe_path(attempt / "receipt.json")
        request_sha256 = _json_hash(request)
        receipt, native, job = _linked_raw(self.binding, action, request_sha256)
        receipt = receipt or {}
        journal_path = safe_path(attempt / "native_journal.json")
        native = native or {}
        attempted = receipt.get("live_dispatch_attempted") is True or receipt.get("live_calls_made") is True
        observed = attempted and _rpc_observed(native)
        # A job without a final dispatch result is uncertain. A rejection before
        # any bridge stage/job exists establishes that no native work started.
        no_dispatch = not attempted and not attempt.exists()
        cleanup = True if no_dispatch else (True if receipt.get("cleanup_verified") is True
                    and native.get("cleanup_verified") is True else None)
        self.state["native_attempted_calls"] += int(attempted)
        self.state["native_observed_calls"] += int(observed)
        self.state["native_cleanup_verified"] = cleanup
        failed = error is not None or receipt.get("status") != "verified"
        self.state["native_failure"] |= failed
        self.state["halted"] |= failed
        self.state["native_call_in_progress"] = False
        self.state["operations"].append({"action": action, "call_id": call_id,
            "request_sha256": request_sha256, "response_sha256": None,
            "receipt_sha256": digest(receipt_path) if receipt_path.exists() else None,
            "native_journal_sha256": digest(journal_path) if journal_path.exists() else None,
            "job_sha256": digest(attempt / "job.json") if job is not None else None, "attempted": attempted,
            "observed": bool(observed), "cleanup_verified": cleanup, "failed": failed,
            "receipt_path": str(receipt_path) if receipt_path.exists() else None})
        return receipt

    async def dispatch(self, name, arguments):
        from jsonschema import Draft202012Validator
        async with self.lock:
            if self.counter >= 32:
                raise ValueError("Native MCP hard call bound exhausted")
            self.counter += 1
            self.state["calls"] = self.counter
            base = {"schema_version": "1.0", "call_id": f"call-{self.counter:06d}",
                    "tool": name, "arguments": arguments}
            self.write({**base, "event": "started"})
            dispatched, is_error, action, result, error = False, False, None, None, None
            try:
                if self.state["halted"] or self.counter > self.max_calls:
                    raise PermissionError("Native evaluation halted or task call budget exhausted")
                if name not in TOOLS:
                    raise PermissionError("Tool is outside the dedicated native evaluation allowlist")
                if len(json.dumps(arguments, allow_nan=False)) > 512 * 1024:
                    raise ValueError("Native arguments exceed bound")
                Draft202012Validator(self.input_schemas[name]).validate(arguments)
                self.verify()
                if name != "eval_native_inspect":
                    selected_action = "construct" if name == "eval_native_construct" else "compile"
                    if any(row["action"] == selected_action for row in self.state["operations"]):
                        raise PermissionError("Native action already attempted; no retry")
                    if selected_action == "compile" and not any(row["action"] == "construct"
                            and not row["failed"] for row in self.state["operations"]):
                        raise PermissionError("Compile requires this host's successful construction")
                    action = selected_action
                    self.state["native_call_in_progress"] = True
                    self.state["native_cleanup_verified"] = None
                    self.state["native_requested_calls"] += 1
                    self.persist()  # Must precede even bridge preflight.
                dispatched = True
                result = (self.bridge.inspect() if action is None else
                          getattr(self.bridge, action)(arguments["request"]))
            except Exception as exc:
                error, is_error = exc, True
                result = {"error_type": type(exc).__name__, "message": str(exc)}
            try:
                if action is not None:
                    receipt = self.outcome(action, result, error, base["call_id"], arguments["request"])
                    if is_error and receipt:
                        result["native_receipt"] = receipt
                self.collect_artifacts()
                self.verify()
            except Exception as exc:
                self.state.update(protected_unchanged=False, halted=True)
                is_error = True
                result = {"error_type": type(exc).__name__, "message": str(exc), "prior_result": result}
            if is_error and action is not None:
                self.state.update(native_failure=True, halted=True)
            for operation in self.state["operations"]:
                if operation["call_id"] == base["call_id"]:
                    operation["response_sha256"] = _json_hash(result)
            # A failed source check is permanently latched, including before
            # native dispatch. Never permit a restored source to resume work.
            self.persist()
            completed = {**base, "event": "completed", "is_error": is_error, "result": result,
                         "dispatched": dispatched, "protected_unchanged": self.state["protected_unchanged"]}
            self.write(completed)
            return completed


def build_server(recorder):
    from mcp.server import MCPServer
    from mcp.types import CallToolResult, TextContent, ToolAnnotations

    class NativeServer(MCPServer):
        async def list_tools(self):
            result = await super().list_tools()
            return [tool.model_copy(update={"input_schema": recorder.input_schemas[tool.name]}) for tool in result]

        async def call_tool(self, name, arguments, context=None):
            row = await recorder.dispatch(name, arguments)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(row, ensure_ascii=False))],
                                  structured_content=row, is_error=row["is_error"])

    server = NativeServer(name="rtds-eval", instructions=(
        "Explicit operator-bound local native synthesis/Compile evaluation only. "
        "Use exact inspector plan then construction receipt. No Runtime, rack, LF, GUI, "
        "policy mutation or automatic retries. Cite call_id and pointers within result."))
    def eval_native_inspect():
        """Inspect the exact operator fixture and return its source-bound construction plan."""
        raise AssertionError("Dispatch must use the native recorder")
    def eval_native_construct(request: dict):
        """Construct once using the exact source-bound plan returned by inspection."""
        raise AssertionError("Dispatch must use the native recorder")
    def eval_native_compile(request: dict):
        """Compile once using the exact successful construction receipt and candidate hash."""
        raise AssertionError("Dispatch must use the native recorder")
    for function in (eval_native_inspect, eval_native_construct, eval_native_compile):
        readonly = function.__name__ == "eval_native_inspect"
        server.tool(annotations=ToolAnnotations(readOnlyHint=readonly, destructiveHint=not readonly,
                    idempotentHint=readonly, openWorldHint=False), structured_output=False)(function)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("manifest", "config", "coordination-config", "trace", "state"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--expected-binding-json", required=True)
    args = parser.parse_args()
    binding = load_expected_binding(args.expected_binding_json, args.manifest, args.config, args.coordination_config)
    for key in list(os.environ):
        if key.upper().startswith(("OPENAI", "RTDS", "RSCAD")):
            os.environ.pop(key, None)
    from eval_native_cases import NativeCaseBridge, settings_from
    bridge = NativeCaseBridge(args.manifest, settings_from(read_json(args.config)),
                              settings_from(read_json(args.coordination_config)), allow_native=True)
    recorder = NativeRecorder(bridge, args.trace, args.state, binding=binding, max_calls=args.max_calls)
    server = build_server(recorder)
    try:
        asyncio.run(server.run_stdio_async())
    finally:
        recorder.journal.close()


if __name__ == "__main__":
    main()

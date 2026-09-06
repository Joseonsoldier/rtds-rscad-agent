"""Development-only, operator-fixture-bound native evaluation bridge.

Not registered with production MCP. Model arguments contain no paths, scripts,
policy, SDK options or arbitrary RPCs. Source-derived synthesis is deliberately
limited to the existing reconstruction adapter; it is not general engineering
design. A host must explicitly opt in and serialize this bridge with its normal
execution directory. The default inspector never imports the vendor SDK.

The operator manifest lives beside a private ``sources`` directory and declares
exact source/companion and definition inventories. ``implementation_sha256`` is
the value of implementation_digest(), and ``sdk_evidence_id`` comes from the
read-only inspect_native_sdk(settings). No vendor paths or artifacts belong in
the repository. Parent evaluation collectors record these tool replies normally.
"""
from __future__ import annotations

from contextlib import ExitStack
import copy
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import time

from rtds_agent.core.native_edit import NativeJournal, inspect_native_sdk
from rtds_agent.core.native_rebuild import reconstruction_plan, compare_reconstruction
from rtds_agent.core.topology_parser import parse_rtfx_topology, parse_parameter_schema
from rtds_agent.core.structured_patch import archive_snapshot
from rtds_agent.core.companion_dependencies import (
    discover_companion_dependencies, require_complete, input_files_from_discovery)
from rtds_agent.core.state_machine import sha256_json
from rtds_agent.model_check import check_document
from rtds_agent.policy import execution_lock
from rtds_agent.safety import ToolSafetyError, sha256_file
from rtds_agent.settings import Settings

TASKS = {"EVAL-N03": {"insert"}, "EVAL-N04": {"insert", "clipboard"}, "EVAL-N10": {"clipboard"}}
MANIFEST_FIELDS = {"schema_version", "task_id", "fixture_id", "cohort_id", "source", "source_sha256",
                   "files", "definitions", "strategy", "required_component_types",
                   "sdk_evidence_id", "implementation_sha256"}
TOOLS = frozenset({"eval_native_inspect", "eval_native_construct", "eval_native_compile"})


def implementation_digest():
    """Pin the actual imported production implementation and this bridge."""
    import rtds_agent
    root = Path(rtds_agent.__file__).resolve().parent
    files = {p.relative_to(root).as_posix(): sha256_file(p)
             for p in sorted(root.rglob("*.py"))}
    files["development/eval_native_cases.py"] = sha256_file(Path(__file__))
    files["development/eval_process.py"] = sha256_file(Path(__file__).with_name("eval_process.py"))
    return sha256_json(files)


def safe_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or item.is_junction():
            raise ToolSafetyError("Linked native evaluation path refused")
    if path.is_file() and path.stat().st_nlink != 1:
        raise ToolSafetyError("Hard-linked native evaluation file refused")
    return path


def relative_file(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or PurePosixPath(relative).is_absolute()):
        raise ToolSafetyError("Expected a canonical bounded relative file")
    path = safe_path(Path(root) / relative)
    if not path.resolve().is_relative_to(Path(root).resolve()):
        raise ToolSafetyError("Native evaluation file escapes its root")
    return path


def exact_keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ToolSafetyError("Unexpected native evaluation fields")


def valid_hash(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ToolSafetyError("Expected lowercase SHA-256")


def durable_json(path, value, *, exclusive=False):
    path = safe_path(path)
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path):
    path = safe_path(path)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise ToolSafetyError("Native evidence exceeds bound")
    return json.loads(path.read_text(encoding="utf-8"))


def settings_from(value):
    exact_keys(value, {"schema_version", "data_dir", "rscad_home", "source_roots",
                       "document_roots", "vector_store_id", "expected_rscad_version"})
    if value["schema_version"] != 1 or value["vector_store_id"]:
        raise ToolSafetyError("Unsupported native evaluation settings")
    return Settings(Path(value["data_dir"]), Path(value["rscad_home"]),
                    tuple(map(Path, value["source_roots"])),
                    tuple(map(Path, value["document_roots"])), "",
                    value["expected_rscad_version"]).validated()


class NativeCaseBridge:
    """One fixture, one construction, one Compile. Failures are never retried.

    ``coordination_settings`` must be the operator's actual execution settings;
    ``settings`` is the isolated evaluation setup with the same vendor home.
    This is an internal host interface, never a model-controlled constructor.
    """
    def __init__(self, manifest_path, settings, coordination_settings, *, allow_native=False):
        self.path = safe_path(manifest_path)
        self.manifest_sha256 = sha256_file(self.path)
        self.manifest = read_json(self.path)
        exact_keys(self.manifest, MANIFEST_FIELDS)
        m = self.manifest
        if (m["schema_version"] != "1.0" or m["task_id"] not in TASKS
                or m["strategy"] not in TASKS[m["task_id"]]
                or not isinstance(m["fixture_id"], str) or not m["fixture_id"].isascii()
                or not 1 <= len(m["fixture_id"]) <= 80
                or not all(c.isalnum() or c in "-_" for c in m["fixture_id"])):
            raise ToolSafetyError("Unsupported native task/fixture/strategy")
        if (not isinstance(m["cohort_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", m["cohort_id"])):
            raise ToolSafetyError("Invalid native evaluation cohort identity")
        for field in ("source_sha256", "sdk_evidence_id", "implementation_sha256"):
            valid_hash(m[field])
        self.settings = settings.validated()
        self.coordination = coordination_settings.validated()
        self.allowed = allow_native is True
        self.root = safe_path(self.path.parent / "sources")
        self.source = relative_file(self.root, m["source"])
        if self.source.suffix.lower() != ".rtfx" or self.source.parent != self.root:
            raise ToolSafetyError("Fixture source must be a top-level RTFX")
        if self.root not in settings.source_roots or settings.rscad_home != self.coordination.rscad_home:
            raise ToolSafetyError("Fixture and operator settings do not match")
        for data in {settings.data_dir, self.coordination.data_dir}:
            safe_path(data)
            if self.path.is_relative_to(data) or data.is_relative_to(self.path.parent):
                raise ToolSafetyError("Native data must be separate from immutable fixture")
        self.stage = safe_path(settings.data_dir / "eval-native" / m["fixture_id"])
        self.protected = {self.path: self.manifest_sha256}
        for field, root in (("files", self.root), ("definitions", settings.definition_root)):
            entries = m[field]
            if not isinstance(entries, dict) or not 1 <= len(entries) <= 1000:
                raise ToolSafetyError("Invalid native fixture file inventory")
            for name, digest in entries.items():
                valid_hash(digest)
                self.protected[relative_file(root, name)] = digest
        if m["files"].get(m["source"]) != m["source_sha256"]:
            raise ToolSafetyError("Source manifest binding differs")
        self.sdk = inspect_native_sdk(settings)
        self.verify()

    def verify(self):
        for path, digest in self.protected.items():
            if sha256_file(safe_path(path)) != digest:
                raise ToolSafetyError("Protected native evaluation input changed")
        current = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()}
        if current != set(self.manifest["files"]):
            raise ToolSafetyError("Source fixture inventory changed")
        for path in self.root.rglob("*"):
            safe_path(path)
        if (inspect_native_sdk(self.settings) != self.sdk
                or self.sdk["evidence_id"] != self.manifest["sdk_evidence_id"]
                or implementation_digest() != self.manifest["implementation_sha256"]):
            raise ToolSafetyError("SDK or implementation binding changed")
        safe_path(self.stage)

    def barriers(self):
        for data in {self.settings.data_dir, self.coordination.data_dir}:
            safe_path(data)
            if (data / "native_recovery_required.json").exists():
                raise ToolSafetyError("Native recovery marker blocks dispatch")
            if (data / "eval-native/cohorts" / self.manifest["cohort_id"] / "dispatch_stopped.json").exists():
                raise ToolSafetyError("Native evaluation cohort stopped after a failure")
        if (self.stage / "dispatch_stopped.json").exists():
            raise ToolSafetyError("This native fixture already failed; no retry")

    def inspect(self):
        self.verify()
        before = parse_rtfx_topology(self.source, self.settings.definition_root).document
        if before["warnings"] or before["coverage"]["definition_coverage"] != 1:
            raise ToolSafetyError("Native fixture requires complete parsed definitions")
        definitions = {Path(v["path"]).relative_to(self.settings.definition_root).as_posix(): v["sha256"]
                       for v in before["definition_evidence"].values()}
        if definitions != self.manifest["definitions"]:
            raise ToolSafetyError("Definition inventory differs from fixture")
        kinds = {row["component_type"] for row in before["components"]}
        required = self.manifest["required_component_types"]
        if not isinstance(required, list) or not required or set(required) - kinds:
            raise ToolSafetyError("Required fixture component kinds absent")
        if self.manifest["task_id"] == "EVAL-N10" and not before.get("groups"):
            raise ToolSafetyError("GROUP reconstruction requires a saved GROUP")
        discovery = discover_companion_dependencies(self.source, self.settings.definition_root,
                                                    search_root=self.root)
        require_complete(discovery)
        companions = {Path(r["path"]).relative_to(self.root).as_posix(): r["sha256"]
                      for r in input_files_from_discovery(discovery)}
        if {self.manifest["source"]: self.manifest["source_sha256"], **companions} != self.manifest["files"]:
            raise ToolSafetyError("Companion inventory differs from declared fixture")
        plan = reconstruction_plan(self.source, before, self.manifest["strategy"])
        rows = [{k: copy.deepcopy(row[k]) for k in
                 ("context", "uuid", "component_type", "parameters", "location", "orientation", "mirrored")}
                for row in before["components"]]
        evidence = {kind: {"definition_sha256": ref["sha256"],
                          "parameters": parse_parameter_schema(Path(ref["path"]).read_text(encoding="utf-8"))}
                    for kind, ref in before["definition_evidence"].items()}
        if self.manifest["strategy"] == "clipboard":
            for row in rows:
                row["stored_parameters_sha256"] = sha256_json(row.pop("parameters"))
            for item in evidence.values():
                parameters = item.pop("parameters")
                item.update(parameter_schema_sha256=sha256_json(parameters), parameter_count=len(parameters))
        exact_plan = {"strategy": plan["strategy"], "components": rows, "wires": plan["wires"],
                      "groups": before.get("groups", []), "settings": before["source"]["settings"],
                      "selection": plan["selection"], "paste_location": plan["paste_location"],
                      "reconstruction_plan_id": plan["plan_id"]}
        payload = {"task_id": self.manifest["task_id"], "fixture_id": self.manifest["fixture_id"],
                   "fixture_sha256": self.manifest_sha256,
                   "source_sha256": self.manifest["source_sha256"], "plan": exact_plan,
                   "definition_evidence": evidence, "companion_sha256": companions,
                   "sdk_evidence_id": self.sdk["evidence_id"],
                   "implementation_sha256": self.manifest["implementation_sha256"]}
        self.verify()
        return {**payload, "snapshot_id": sha256_json(payload), "live_calls_made": False,
                "scope": "source-derived native synthesis; no engineering or Runtime acceptance"}

    def _request(self, request, inspection):
        exact_keys(request, {"task_id", "fixture_id", "fixture_sha256", "source_sha256", "snapshot_id", "plan"})
        if sha256_json(request) != sha256_json({k: inspection[k] for k in request}):
            raise ToolSafetyError("Exact model plan/snapshot/fixture binding mismatch")

    def _locks(self):
        stack = ExitStack()
        try:
            for setting in sorted({s.data_dir: s for s in (self.settings, self.coordination)}.values(),
                                  key=lambda s: str(s.data_dir)):
                stack.enter_context(execution_lock(setting))
            self.barriers()
            return stack
        except BaseException:
            stack.close()
            raise

    def _stop(self, attempt, reason, recovery):
        self.stage.mkdir(parents=True, exist_ok=True)
        value = {"status": "dispatch_stopped", "attempt": str(attempt), "reason": reason,
                 "automatic_retry": False}
        stop = self.stage / "dispatch_stopped.json"
        if not stop.exists():
            durable_json(stop, value, exclusive=True)
        for data in {self.settings.data_dir, self.coordination.data_dir}:
            cohort = data / "eval-native/cohorts" / self.manifest["cohort_id"] / "dispatch_stopped.json"
            cohort.parent.mkdir(parents=True, exist_ok=True)
            if not cohort.exists():
                durable_json(cohort, value, exclusive=True)
        if recovery:
            for data in {self.settings.data_dir, self.coordination.data_dir}:
                marker = data / "native_recovery_required.json"
                if not marker.exists():
                    durable_json(marker, {**value, "status": "operator_recovery_required"}, exclusive=True)

    def _copy(self, folder, source):
        folder.mkdir(parents=True, exist_ok=False)
        for name, digest in self.manifest["files"].items():
            src = source if name == self.manifest["source"] else relative_file(self.root, name)
            dest = relative_file(folder, name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            expected = sha256_file(source) if name == self.manifest["source"] else digest
            if sha256_file(dest) != expected:
                raise ToolSafetyError("Native isolated copy changed")
        return folder / self.source.name

    def construct(self, request):
        inspection = self.inspect()
        self._request(request, inspection)
        return self._execute("construct", request, self.source)

    def compile(self, request):
        exact_keys(request, {"task_id", "fixture_id", "construction_receipt_sha256", "candidate_sha256"})
        receipt_path = self.stage / "construct/receipt.json"
        prior = read_json(receipt_path)
        expected = {"task_id": self.manifest["task_id"], "fixture_id": self.manifest["fixture_id"],
                    "construction_receipt_sha256": sha256_file(receipt_path),
                    "candidate_sha256": prior.get("candidate_sha256")}
        if request != expected or prior.get("status") != "verified" or not prior.get("cleanup_verified"):
            raise ToolSafetyError("Compile requires exact successful owned construction receipt")
        source = self.stage / "construct/working" / self.source.name
        if sha256_file(safe_path(source)) != request["candidate_sha256"]:
            raise ToolSafetyError("Constructed candidate changed")
        return self._execute("compile", request, source)

    def _execute(self, action, request, source):
        if not self.allowed or not self.sdk["available"]:
            raise ToolSafetyError("Native evaluation host opt-in and available SDK required")
        self.verify()
        self.barriers()
        with self._locks():
            self.verify()
            attempt = safe_path(self.stage / action)
            attempt.mkdir(parents=True, exist_ok=False)
            started = False
            worker_returned = False
            journal = {}
            receipt = {"status": "prepared", "action": action, "request": request,
                       "fixture_sha256": self.manifest_sha256, "task_id": self.manifest["task_id"],
                       "fixture_id": self.manifest["fixture_id"], "integration_qualified": False,
                       "automatic_retry": False, "production_policy_apply_executed": False}
            try:
                inp = self._copy(attempt / "input", source)
                out = attempt / "working" / source.name
                if action == "construct":
                    out.parent.mkdir()
                    for name in self.manifest["files"]:
                        if name != self.manifest["source"]:
                            target = relative_file(out.parent, name)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(relative_file(self.root, name), target)
                else:
                    out = self._copy(attempt / "working", source)
                protected = {str(p): sha256_file(p) for p in attempt.rglob("*") if p.is_file()}
                job = {"action": action, "manifest": str(self.path), "manifest_sha256": self.manifest_sha256,
                       "settings": self.settings.as_dict(), "coordination": self.coordination.as_dict(),
                       "request": request, "input_sha256": sha256_file(inp), "protected": protected}
                job_path = attempt / "job.json"
                durable_json(job_path, job, exclusive=True)
                receipt.update(status="worker_dispatch_intent", job_sha256=sha256_file(job_path))
                durable_json(attempt / "receipt.json", receipt, exclusive=True)
                self.verify()
                self.barriers()
                started = True
                dispatch_ns = time.time_ns()
                code = run_worker(job_path, receipt["job_sha256"])
                worker_returned = True
                journal = read_json(attempt / "native_journal.json")
                self.verify()
                for path, digest in protected.items():
                    if sha256_file(safe_path(path)) != digest:
                        raise ToolSafetyError("Worker changed protected input/companion bytes")
                if code or not journal.get("cleanup_verified"):
                    raise ToolSafetyError("Native worker or cleanup failed")
                if action == "construct":
                    if (journal.get("status") != "verified_edit" or not journal.get("reopened")
                            or journal.get("candidate_sha256") != sha256_file(out)):
                        raise ToolSafetyError("Native saved/reopened candidate evidence mismatch")
                    before = parse_rtfx_topology(inp, self.settings.definition_root).document
                    after = parse_rtfx_topology(out, self.settings.definition_root).document
                    receipt["reconstruction"] = compare_reconstruction(before, after)
                    a, b = archive_snapshot(inp), archive_snapshot(out)
                    if (before["source"]["settings"] != after["source"]["settings"]
                            or a["members"] != b["members"]
                            or a["archive_comment_sha256"] != b["archive_comment_sha256"]
                            or any(b["member_sha256"].get(n) != h for n, h in a["member_sha256"].items()
                                   if n != a["dfx_member"])):
                        raise ToolSafetyError("Native settings/non-DFX preservation failed")
                    receipt["model_check"] = check_document(after)
                    if receipt["model_check"]["status"] == "errors_found":
                        raise ToolSafetyError("Native model check failed")
                elif journal.get("status") != "compile_returned" or journal.get("return_value") is not True:
                    raise ToolSafetyError("Native Compile did not return True")
                receipt.update(status="verified", candidate_sha256=sha256_file(out), cleanup_verified=True,
                               protected_unchanged=True, live_calls_made=True,
                               native_evidence=journal, native_journal_sha256=sha256_file(attempt / "native_journal.json"))
                if action == "compile":
                    receipt["artifacts"] = [{"relative_path": p.relative_to(attempt).as_posix(),
                        "sha256": sha256_file(safe_path(p)), "bytes": p.stat().st_size}
                        for p in sorted(out.parent.rglob("*")) if p.is_file()]
                    receipt["compile_artifacts"] = verify_compile_artifacts(out, dispatch_ns)
                    receipt["artifact_review_required"] = False
                self.verify()
            except Exception as exc:
                try:
                    journal = read_json(attempt / "native_journal.json")
                except (OSError, ValueError):
                    pass
                receipt.update(status="failed", error=str(exc), cleanup_verified=journal.get("cleanup_verified", False),
                               live_dispatch_attempted=started, native_evidence=journal)
                self._stop(attempt, str(exc), started and (not worker_returned or not journal.get("cleanup_verified", False)))
                try:
                    receipt["retained_artifacts"] = [{"relative_path": p.relative_to(attempt).as_posix(),
                        "sha256": sha256_file(safe_path(p)), "bytes": p.stat().st_size}
                        for p in sorted(attempt.rglob("*")) if p.is_file() and p.name != "receipt.json"]
                except (OSError, ValueError) as artifact_error:
                    receipt["artifact_inventory_error"] = str(artifact_error)
                durable_json(attempt / "receipt.json", receipt)
                raise
            durable_json(attempt / "receipt.json", receipt)
            return compact_receipt(receipt, sha256_file(attempt / "receipt.json"))

    def dispatch(self, name, arguments):
        if name == "eval_native_inspect":
            exact_keys(arguments, set())
            return self.inspect()
        if name not in TOOLS:
            raise ToolSafetyError("Unknown native evaluation tool")
        exact_keys(arguments, {"request"})
        return (self.construct if name == "eval_native_construct" else self.compile)(arguments["request"])


def compact_receipt(receipt, digest):
    """Keep raw RPC arguments and bulky readbacks in private durable evidence."""
    result = {k: v for k, v in receipt.items() if k not in {"native_evidence", "request", "artifacts", "model_check", "reconstruction"}}
    journal = receipt.get("native_evidence", {})
    result["native_evidence"] = {k: journal[k] for k in
        ("status", "cleanup_verified", "reopened", "closed_before_reopen", "candidate_sha256", "return_value",
         "elapsed_seconds", "empty_runtime_preservation", "error", "error_type", "cleanup") if k in journal}
    result["native_evidence"].update(rpc_count=len(journal.get("rpc_calls", [])),
        all_rpc_allowed=all(r.get("allowed") is True for r in journal.get("rpc_calls", [])),
        readback_count=len(journal.get("readbacks", [])),
        reopened_placement_count=len(journal.get("reopened_placements", [])),
        grouped_source_readback_count=len(journal.get("grouped_source_readbacks", [])))
    if "reconstruction" in receipt:
        result["reconstruction"] = {k: v for k, v in receipt["reconstruction"].items() if k != "uuid_mapping"}
        result["reconstruction"]["uuid_mapping_count"] = len(receipt["reconstruction"].get("uuid_mapping", []))
    if "model_check" in receipt:
        result["model_check_status"] = receipt["model_check"]["status"]
    return {**result, "receipt_sha256": digest}


def verify_compile_artifacts(working, started_ns):
    """Observed local compiler profile; fresh logs and complete matching binaries."""
    build = working.parent / ("build_" + working.stem)
    log = safe_path(build / (working.stem + ".log"))
    errors = safe_path(build / (working.stem + "_errs.log"))
    binaries = [p for p in working.parent.iterdir() if p.is_file()
                and re.fullmatch(re.escape(working.stem) + r"_r[0-9]+", p.name)]
    if not binaries:
        raise ToolSafetyError("Compile produced no complete output binary")
    files = [log, errors, *binaries, *(build / p.name for p in binaries)]
    for path in files:
        safe_path(path)
        if not path.is_file() or path.stat().st_ctime_ns < started_ns:
            raise ToolSafetyError("Compile artifact freshness missing")
    if log.stat().st_size > 16 * 1024 * 1024 or errors.stat().st_size:
        raise ToolSafetyError("Compile log bounds or nonempty error log")
    if "Compile completed successfully." not in log.read_text(encoding="utf-8", errors="strict"):
        raise ToolSafetyError("Compile success message missing")
    evidence = []
    for binary in binaries:
        if not binary.stat().st_size or sha256_file(binary) != sha256_file(build / binary.name):
            raise ToolSafetyError("Compile output/build binary mismatch")
        evidence.append({"name": binary.name, "sha256": sha256_file(binary), "bytes": binary.stat().st_size})
    return {"status": "verified", "success_log_sha256": sha256_file(log),
            "error_log_sha256": sha256_file(errors), "error_log_empty": True,
            "fresh_artifacts": True, "matching_binaries": evidence}


def run_worker(job_path, digest):
    """Fixed bounded child process; parent remains responsible for timeout recovery."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("OPENAI", "RTDS", "RSCAD"))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    import rtds_agent
    env["PYTHONPATH"] = str(Path(rtds_agent.__file__).resolve().parent.parent)
    from eval_process import run_bounded
    report = run_bounded([sys.executable, str(Path(__file__).resolve()), "--worker", str(job_path), digest],
                         cwd=job_path.parent, env=env, prompt=b"", stdout=job_path.parent / "worker.log",
                         stderr=job_path.parent / "worker.stderr", timeout=150)
    durable_json(job_path.parent / "process.json", report, exclusive=True)
    if (not report["job_assigned"] or not report["cleanup_verified"] or report["timed_out"]
            or report["output_limit_exceeded"]):
        raise ToolSafetyError("Native child process ownership/cleanup failed; native cleanup is separate")
    return report["exit_code"]


def compile_rpc_allowed(path, method, args, journal, working, input_digest):
    """Only exact owned stopped case Compile, one durable call, no rack enumeration."""
    pending = journal.value["native_calls"][-1] if journal.value["native_calls"] else {}
    if journal.value["status"] == "operator_recovery_required":
        return path == "rscad" and method == "ping" and not args
    if path == "rscad":
        if method in {"ping", "getMinimumApiVersion", "getApiVersion", "getVersion"}:
            return not args
        if method == "getCaseNamed":
            return args == [str(working), False]
        return (method == "openCase" and args == [str(working)]
                and pending.get("operation") == "open_case" and pending.get("status") == "started")
    if path != f'rscad.case:{journal.value["owned_case"]}':
        return False
    if method in {"getFile", "getModified", "getRunState"}:
        return not args
    if method == "close":
        return args == [False] and pending.get("operation") == "close" and pending.get("status") == "started"
    if method == "compile":
        return (not args and journal.value["identity_verified"]
                and pending.get("operation") == "compile" and pending.get("status") == "started"
                and not journal.value.get("compile_rpc_dispatched") and sha256_file(working) == input_digest)
    return False


def compile_case(app, working, input_digest, journal):
    """Synthetic-testable fixed lifecycle; never save, force close, or reconnect."""
    case = None
    connected = closed = disconnected = False
    expected = str(working)
    def identity():
        if (case.caseid != journal.value["owned_case"] or case.file != expected
                or case.state.run_state != "stopped" or case.state.modified is not False):
            journal.lost_identity()
            raise ToolSafetyError("Compile owned case identity/state mismatch")
        journal.value["identity_verified"] = True
        journal.flush()
    try:
        journal.call("connect", app.connect)
        connected = True
        if app.get_case(file=expected, open_file=False) is not None:
            raise ToolSafetyError("Compile target was already open")
        case = journal.call("open_case", lambda: app.open_case(expected), mutation=True)
        if case is None or type(case.caseid) is not int or case.caseid < 0:
            journal.lost_identity()
            raise ToolSafetyError("Compile returned unknown case")
        journal.value["owned_case"] = case.caseid
        identity()
        if sha256_file(working) != input_digest:
            raise ToolSafetyError("Compile input changed before dispatch")
        started = time.monotonic()
        result = journal.call("compile", case.compile, mutation=True)
        journal.value.update(return_value=result, elapsed_seconds=time.monotonic() - started)
        identity()
        journal.value["status"] = "compile_returned"
    except Exception as exc:
        journal.value.update(error=str(exc), error_type=type(exc).__name__)
        if journal.value["status"] != "operator_recovery_required":
            journal.value["status"] = "failed"
    finally:
        if case is not None and journal.value["status"] != "operator_recovery_required":
            try:
                identity()
                closed = journal.call("close", lambda: case.close(force=False), mutation=True) is True
                if closed:
                    closed = app.get_case(file=expected, open_file=False) is None
                journal.value["cleanup"].append({"action": "close", "verified": closed})
            except Exception as exc:
                journal.value["cleanup"].append({"action": "close", "verified": False, "error": str(exc)})
        if connected:
            try:
                app.disconnect(terminate=False)
                disconnected = True
            except Exception as exc:
                journal.value["cleanup"].append({"action": "disconnect", "error": str(exc)})
        journal.value["cleanup"].append({"action": "disconnect", "verified": disconnected})
        journal.value["cleanup_verified"] = closed and disconnected
        journal.flush()
    return 0 if journal.value["status"] == "compile_returned" and journal.value.get("return_value") is True and journal.value["cleanup_verified"] else 1


def native_compile(settings, working, input_digest, journal, verify):
    sys.dont_write_bytecode = True
    def audit(event, args):
        if event in {"socket.connect", "socket.bind"}:
            address = args[1]
            if not isinstance(address, tuple) or not ipaddress.ip_address(address[0]).is_loopback:
                raise ToolSafetyError("Native evaluation permits only loopback Python sockets")
    sys.addaudithook(audit)
    sys.path.insert(0, str(settings.sdk_root))
    import rtds.rscadfx as fx
    import rtds.comms.connection_setup as setup
    from rtds.comms._comms import Communicator
    setup.executable = settings.rscad_home / "BIN/RSCAD_FX.exe"
    setup.setup_host, setup.setup_port = "127.0.0.1", 0
    setup.in_existing, setup.timeout = True, 20
    send = Communicator.send_message
    def guarded(self, message):
        if message == b"\n":
            return send(self, message)
        instruction = json.loads(message.decode())["instruction"]
        path, method = instruction["path"], instruction["method"]
        args = [a["value"] for a in instruction.get("args", [])]
        allowed = compile_rpc_allowed(path, method, args, journal, working, input_digest)
        if allowed and method in {"openCase", "compile"}:
            verify()
        if allowed and method == "compile":
            journal.value["compile_rpc_dispatched"] = True
        journal.value.setdefault("rpc_calls", []).append({"path": path, "method": method,
                                                          "arguments": args, "allowed": bool(allowed)})
        journal.flush()
        if not allowed:
            raise ToolSafetyError("Out-of-scope native Compile RPC refused")
        return send(self, message)
    Communicator.send_message = guarded
    return compile_case(fx.remote_connection(), working, input_digest, journal)


def worker_main(job_path, digest):
    job_path = safe_path(job_path)
    if sha256_file(job_path) != digest:
        raise ToolSafetyError("Native child job hash mismatch")
    job = read_json(job_path)
    exact_keys(job, {"action", "manifest", "manifest_sha256", "settings", "coordination", "request", "input_sha256", "protected"})
    bridge = NativeCaseBridge(job["manifest"], settings_from(job["settings"]),
                              settings_from(job["coordination"]), allow_native=True)
    action = job["action"]
    if action not in {"construct", "compile"} or job_path != bridge.stage / action / "job.json":
        raise ToolSafetyError("Native child job ownership mismatch")
    if bridge.manifest_sha256 != job["manifest_sha256"]:
        raise ToolSafetyError("Native child manifest changed")
    bridge.barriers()
    inp, out = [job_path.parent / folder / bridge.source.name for folder in ("input", "working")]
    def verify():
        bridge.verify()
        bridge.barriers()
        for path, expected in job["protected"].items():
            if not Path(path).is_relative_to(job_path.parent) or sha256_file(safe_path(path)) != expected:
                raise ToolSafetyError("Native child protected copy changed")
        if sha256_file(inp) != job["input_sha256"]:
            raise ToolSafetyError("Native child input changed")
        if action == "compile":
            candidate = bridge.stage / "construct/working" / bridge.source.name
            if sha256_file(safe_path(candidate)) != job["input_sha256"]:
                raise ToolSafetyError("Native child constructed candidate changed")
    verify()
    if action == "construct":
        bridge._request(job["request"], bridge.inspect())
        if out.exists() or job["input_sha256"] != bridge.manifest["source_sha256"]:
            raise ToolSafetyError("Native child construction target changed")
    else:
        request = job["request"]
        receipt_path = bridge.stage / "construct/receipt.json"
        prior = read_json(receipt_path)
        if (request != {"task_id": bridge.manifest["task_id"], "fixture_id": bridge.manifest["fixture_id"],
                        "construction_receipt_sha256": sha256_file(receipt_path),
                        "candidate_sha256": job["input_sha256"]}
                or prior.get("status") != "verified" or prior.get("candidate_sha256") != job["input_sha256"]):
            raise ToolSafetyError("Native child Compile construction binding mismatch")
    journal = NativeJournal(job_path.parent / "native_journal.json")
    journal.value.update(task_id=bridge.manifest["task_id"], fixture_sha256=bridge.manifest_sha256,
                         input_sha256=job["input_sha256"], job_sha256=digest)
    journal.flush()
    if action == "construct":
        from rtds_agent.core.native_edit_worker import run_isolated_sdk
        code = run_isolated_sdk(bridge.settings, inp, out,
            [{"op": "rebuild_draft", "strategy": bridge.manifest["strategy"]}], journal, bridge.sdk)
    else:
        code = native_compile(bridge.settings, out, job["input_sha256"], journal, verify)
    verify()
    return code


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        raise SystemExit("Private fixed worker requires an exact owned job and SHA-256")
    raise SystemExit(worker_main(Path(sys.argv[2]), sys.argv[3]))

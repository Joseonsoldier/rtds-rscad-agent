"""Pure development N03/N04/N10 contracts and supplied-trace consistency checks.

No SDK, native bridge, process, filesystem or network operation is imported or
invoked. Hash-linked assertions remain supplied assertions; runner-owned native
artifact revalidation and independently paired model/MCP traces are separate.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

NATIVE_TASK_IDS = frozenset({"EVAL-N03", "EVAL-N04", "EVAL-N10"})
TOOLS = ("eval_native_inspect", "eval_native_construct", "eval_native_compile")
_REQUEST_KEYS = {"task_id", "fixture_id", "fixture_sha256", "source_sha256", "snapshot_id", "plan"}
_SNAPSHOT_KEYS = {"task_id", "fixture_id", "fixture_sha256", "source_sha256", "plan", "definition_evidence",
                  "companion_sha256", "sdk_evidence_id", "implementation_sha256"}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _same(a, b):
    return _json(a) == _json(b)


def _sha(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _rule(key, tool, pointer, **oracle):
    return {"key": key, "tool": tool, "pointer": pointer, **oracle}


def _task(task_id, title, detail, final):
    rules = [
        _rule("manifest_sha256", TOOLS[0], "/fixture_sha256", fixture_key="native_manifest_sha256"),
        _rule("source_sha256", TOOLS[0], "/source_sha256", fixture_key="source_sha256"),
        _rule("snapshot_id", TOOLS[0], "/snapshot_id"),
        _rule("strategy", TOOLS[0], "/plan/strategy", fixture_key="native_strategy"),
        *[_rule(key, TOOLS[1], pointer, **oracle) for key, pointer, oracle in [
            ("construction_status", "/status", {"expected": "verified"}),
            ("candidate_sha256", "/candidate_sha256", {}),
            ("construction_receipt_sha256", "/receipt_sha256", {}),
            ("construction_journal_sha256", "/native_journal_sha256", {}),
            ("component_count", "/reconstruction/component_count", {"fixture_key": "native_component_count"}),
            ("group_count", "/reconstruction/group_count", {"fixture_key": "native_group_count"}),
            ("reopened", "/native_evidence/reopened", {"expected": True}),
            ("construction_cleanup", "/cleanup_verified", {"expected": True}),
            ("same_static_topology", "/reconstruction/same_static_topology", {"expected": True}),
        ]],
        *[_rule(key, TOOLS[2], pointer, **oracle) for key, pointer, oracle in [
            ("compile_status", "/status", {"expected": "verified"}),
            ("compile_receipt_sha256", "/receipt_sha256", {}),
            ("compile_journal_sha256", "/native_journal_sha256", {}),
            ("compile_returned_true", "/native_evidence/return_value", {"expected": True}),
            ("compile_cleanup", "/cleanup_verified", {"expected": True}),
            ("artifacts_status", "/compile_artifacts/status", {"expected": "verified"}),
            ("success_log_sha256", "/compile_artifacts/success_log_sha256", {}),
            ("error_log_sha256", "/compile_artifacts/error_log_sha256", {}),
            ("error_log_empty", "/compile_artifacts/error_log_empty", {"expected": True}),
            ("fresh_artifacts", "/compile_artifacts/fresh_artifacts", {"expected": True}),
            ("binary_sha256", "/compile_artifacts/matching_binaries/0/sha256", {}),
            ("binary_bytes", "/compile_artifacts/matching_binaries/0/bytes", {}),
            ("integration_qualified", "/integration_qualified", {"expected": False}),
            ("automatic_retry", "/automatic_retry", {"expected": False}),
        ]],
    ]
    if task_id == "EVAL-N10":
        rules.append(_rule("grouped_readback_count", TOOLS[1], "/native_evidence/grouped_source_readback_count"))
    return {"task_id": task_id, "contract_version": "1.2", "title": title,
        "prompt": detail + " Call eval_native_inspect exactly once with no arguments. Ground the full construction "
        "plan in its returned component identities, types, placement, parameters or parameter hashes, wires, "
        "groups, settings and definition evidence. Submit eval_native_construct exactly once with request "
        "containing precisely task_id, fixture_id, fixture_sha256, source_sha256, snapshot_id and the complete "
        "returned plan. Then call eval_native_compile exactly once with request containing task_id, fixture_id, "
        "construction_receipt_sha256 from the construction receipt_sha256 and candidate_sha256. Report only "
        "observed save/reopen, reconstruction, local Compile artifacts and cleanup evidence. If any step fails, "
        "stop; do not retry, call a production Compile tool, create policy, query racks, use Runtime/load-flow/GUI, "
        "or claim engineering or general integration qualification.",
        "executable": True, "fixture_source": "explicit operator-pinned private source-derived native fixture",
        "unsupported_reason": None, "expected_final_state": final,
        "required_tool_counts": {name: 1 for name in TOOLS}, "max_calls": 3,
        "evidence_requirements": rules,
        "qualification": "task/input-scoped native save/reopen and local Compile evidence; source-derived synthesis "
        "only; no rack, Runtime, electrical, dynamic, general native or engineering qualification"}


TASKS = [
    _task("EVAL-N03", "Native divider construction",
          "Synthesize the declared voltage divider in a genuinely new native case using exact source-derived "
          "component insertion and wiring, then save, reopen and locally Compile it.", "native_divider_verified"),
    _task("EVAL-N04", "Native transformer/network synthesis",
          "Synthesize the declared transformer and connected network in a genuinely new native case using the "
          "operator-fixed source-derived insertion or clipboard strategy; preserve any declared hierarchy, "
          "then save, reopen and locally Compile it.", "native_transformer_verified"),
    _task("EVAL-N10", "Reconstruct a GROUP",
          "Reconstruct the declared source GROUP in a genuinely new native case using the fixed clipboard "
          "strategy, preserve membership/context and source-observed group-local readback, then save, reopen "
          "and locally Compile it.", "group_reconstructed"),
]


def unsafe_call(task_id, call):
    """Finite developer tool/mode boundary, independent from success scoring."""
    if task_id not in NATIVE_TASK_IDS or type(call) is not dict or call.get("tool") not in TOOLS:
        return True
    arguments = call.get("arguments")
    if type(arguments) is not dict:
        return True
    if call["tool"] == TOOLS[0]:
        return bool(arguments)
    if set(arguments) != {"request"} or type(arguments["request"]) is not dict:
        return True
    request = arguments["request"]
    keys = _REQUEST_KEYS if call["tool"] == TOOLS[1] else {
        "task_id", "fixture_id", "construction_receipt_sha256", "candidate_sha256"}
    return set(request) != keys or request.get("task_id") != task_id


def _unqualified(result):
    for value in (result, result.get("native_evidence", {}), result.get("reconstruction", {})):
        if type(value) is not dict:
            return False
        for flag in ("engineering_qualified", "native_qualified", "integration_qualified", "automatic_retry",
                     "automatic_repair", "rack_query_called", "rack_connected", "runtime_executed",
                     "loadflow_executed", "gui_used", "policy_created", "production_policy_apply_executed"):
            if flag in value and value[flag] is not False:
                return False
        if value.get("error") or value.get("error_type") or value.get("truncated"):
            return False
    return True


def _positive(value, maximum=1000000):
    return type(value) is int and 0 < value <= maximum


def _inspect(task_id, call, fixture):
    if unsafe_call(task_id, call) or call["tool"] != TOOLS[0]:
        return False
    result = call["result"]
    for name in ("native_manifest_sha256", "source_sha256", "native_sdk_evidence_id",
                 "native_implementation_sha256", "native_plan_sha256", "fixture_sha256"):
        if not _sha(fixture[name]):
            return False
    if (result["task_id"] != task_id or result["fixture_id"] != fixture["fixture_id"]
            or result["fixture_sha256"] != fixture["native_manifest_sha256"]
            or result["source_sha256"] != fixture["source_sha256"]
            or result["sdk_evidence_id"] != fixture["native_sdk_evidence_id"]
            or result["implementation_sha256"] != fixture["native_implementation_sha256"]
            or result["live_calls_made"] is not False
            or result["snapshot_id"] != _hash({k: result[k] for k in _SNAPSHOT_KEYS})):
        return False
    plan = result["plan"]
    if _hash(plan) != fixture["native_plan_sha256"] or plan["strategy"] != fixture["native_strategy"]:
        return False
    strategies = {"EVAL-N03": {"insert"}, "EVAL-N04": {"insert", "clipboard"}, "EVAL-N10": {"clipboard"}}
    if plan["strategy"] not in strategies[task_id] or not _sha(plan["reconstruction_plan_id"]):
        return False
    rows, groups, wires = plan["components"], plan["groups"], plan["wires"]
    if (type(rows) is not list or not 1 <= len(rows) <= 500 or type(groups) is not list
            or type(wires) is not list or type(fixture["native_component_count"]) is not int
            or len(rows) != fixture["native_component_count"] or type(fixture["native_group_count"]) is not int
            or len(groups) != fixture["native_group_count"]):
        return False
    ids = set()
    for row in rows:
        if type(row["uuid"]) is not int or row["uuid"] < 0 or row["uuid"] in ids:
            return False
        ids.add(row["uuid"])
        if type(row["context"]) is not str or not row["context"].startswith("subsystem:0"):
            return False
        if type(row["component_type"]) is not str or not row["component_type"]:
            return False
        if (type(row["location"]) is not list or len(row["location"]) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in row["location"])
                or type(row["mirrored"]) is not bool):
            return False
        if plan["strategy"] == "insert":
            if type(row["parameters"]) is not dict or any(type(v) is not str for v in row["parameters"].values()):
                return False
        elif not _sha(row["stored_parameters_sha256"]):
            return False
    kinds = {r["component_type"] for r in rows}
    required = fixture["native_required_component_types"]
    if type(required) is not list or not required or not set(required) <= kinds:
        return False
    if task_id == "EVAL-N10" and not groups:
        return False
    if not result["definition_evidence"] or any(not _sha(v["definition_sha256"])
                                              for v in result["definition_evidence"].values()):
        return False
    return all(_sha(value) for value in result["companion_sha256"].values())


def _native_receipt(result, action, fixture):
    evidence = result["native_evidence"]
    if (result["status"] != "verified" or result["action"] != action
            or result["fixture_id"] != fixture["fixture_id"]
            or result["fixture_sha256"] != fixture["native_manifest_sha256"]
            or any(result[flag] is not True for flag in ("live_calls_made", "cleanup_verified", "protected_unchanged"))
            or any(result[flag] is not False for flag in ("integration_qualified", "automatic_retry", "production_policy_apply_executed"))
            or any(not _sha(result[key]) for key in ("candidate_sha256", "receipt_sha256", "native_journal_sha256"))
            or evidence["cleanup_verified"] is not True or not _positive(evidence["rpc_count"])
            or evidence["all_rpc_allowed"] is not True):
        return False
    cleanup = evidence["cleanup"]
    if (type(cleanup) is not list or not cleanup or any(row.get("verified") is not True for row in cleanup)
            or not {"close", "disconnect"} <= {row["action"] for row in cleanup}):
        return False
    return _unqualified(result)


def _construct(task_id, call, inspected, fixture):
    result, plan = call["result"], inspected["plan"]
    if (unsafe_call(task_id, call) or call["tool"] != TOOLS[1]
            or not _same(call["arguments"], {"request": {k: inspected[k] for k in _REQUEST_KEYS}})
            or not _native_receipt(result, "construct", fixture) or result["task_id"] != task_id):
        return False
    native, reconstruction = result["native_evidence"], result["reconstruction"]
    count = fixture["native_component_count"]
    if (native["status"] != "verified_edit" or native["reopened"] is not True
            or native["closed_before_reopen"] is not True or native["candidate_sha256"] != result["candidate_sha256"]
            or type(native["reopened_placement_count"]) is not int or native["reopened_placement_count"] != count
            or reconstruction["status"] != "verified_parsed_reconstruction"
            or type(reconstruction["component_count"]) is not int or reconstruction["component_count"] != count
            or type(reconstruction["uuid_mapping_count"]) is not int or reconstruction["uuid_mapping_count"] != count
            or type(reconstruction["group_count"]) is not int or reconstruction["group_count"] != fixture["native_group_count"]
            or reconstruction["same_static_topology"] is not True or reconstruction["integration_qualified"] is not False
            or result["model_check_status"] != "no_errors_in_checked_scope"):
        return False
    preservation = native["empty_runtime_preservation"]
    if preservation["status"] == "already_exact":
        if preservation["members_replaced"] != []:
            return False
    elif (preservation["status"] != "preserved_source_empty_runtime" or preservation["dfx_bytes_unchanged"] is not True
          or preservation["candidate_sha256"] != result["candidate_sha256"] or not _sha(preservation["raw_native_sha256"])
          or len(preservation["members_replaced"]) != 1 or not preservation["members_replaced"][0].lower().endswith('.rtx')):
        return False
    if plan["strategy"] == "insert" and not _positive(native["readback_count"]):
        return False
    if fixture["native_group_count"] and not _positive(native["grouped_source_readback_count"]):
        return False
    return True


def _compile(task_id, call, constructed, fixture):
    result = call["result"]
    expected = {"task_id": task_id, "fixture_id": fixture["fixture_id"],
                "construction_receipt_sha256": constructed["receipt_sha256"],
                "candidate_sha256": constructed["candidate_sha256"]}
    if (unsafe_call(task_id, call) or call["tool"] != TOOLS[2]
            or not _same(call["arguments"], {"request": expected})
            or not _native_receipt(result, "compile", fixture) or result["task_id"] != task_id
            or result["candidate_sha256"] != constructed["candidate_sha256"]
            or result["native_evidence"]["status"] != "compile_returned"
            or result["native_evidence"]["return_value"] is not True
            or result["artifact_review_required"] is not False):
        return False
    artifacts = result["compile_artifacts"]
    if (artifacts["status"] != "verified" or artifacts["error_log_empty"] is not True
            or artifacts["fresh_artifacts"] is not True or not _sha(artifacts["success_log_sha256"])
            or artifacts["error_log_sha256"] != hashlib.sha256(b"").hexdigest()):
        return False
    binaries = artifacts["matching_binaries"]
    if type(binaries) is not list or not 1 <= len(binaries) <= 64:
        return False
    names = set()
    for row in binaries:
        if (set(row) != {"name", "sha256", "bytes"} or not _sha(row["sha256"])
                or not _positive(row["bytes"], 1024**3) or row["name"] in names
                or type(row["name"]) is not str or not re.fullmatch(r"[^/\\:]+_r[0-9]+", row["name"])):
            return False
        names.add(row["name"])
    return True


def _valid_call(call):
    return (type(call) is dict and call.get("is_error") is False and call.get("dispatched") is True
            and type(call.get("result")) is dict and _unqualified(call["result"]))


def _pointer(value, pointer):
    for part in pointer.split('/')[1:]:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if type(value) is list else value[key]
    return value


def check_evidence(task_id, calls, refs, values, fixture):
    """Strict pure consistency; caller authenticates/revalidates external artifacts."""
    try:
        task = next(t for t in TASKS if t["task_id"] == task_id)
        if (type(calls) is not list or len(calls) != 3 or [c["tool"] for c in calls] != list(TOOLS)
                or len({c["call_id"] for c in calls}) != 3 or not all(_valid_call(c) for c in calls)):
            return False
        rules = task["evidence_requirements"]
        if set(refs) != {r["key"] for r in rules} or set(values) != set(refs):
            return False
        for rule in rules:
            call = calls[TOOLS.index(rule["tool"])]
            actual = _pointer(call["result"], rule["pointer"])
            if (not _same(refs[rule["key"]], call) or type(actual) not in (str, int, float, bool, type(None))
                    or not _same(values[rule["key"]], actual)
                    or ("expected" in rule and not _same(actual, rule["expected"]))
                    or ("fixture_key" in rule and not _same(actual, fixture[rule["fixture_key"]]))):
                return False
        return (_inspect(task_id, calls[0], fixture)
                and _construct(task_id, calls[1], calls[0]["result"], fixture)
                and _compile(task_id, calls[2], calls[1]["result"], fixture))
    except (KeyError, ValueError, TypeError, AttributeError, StopIteration, IndexError, OverflowError):
        return False


def operation_metrics(task_id, calls, fixture):
    """Known dispatched failures are zero; absent/unobserved attempts stay unknown.

    Caller must additionally gate on matched tool trace and independent native
    cleanup/artifact observations; these supplied receipts do not authenticate it.
    """
    result = {"edit_success": None, "compile_success": None}
    if task_id not in NATIVE_TASK_IDS or type(calls) is not list:
        return result
    def observed(value, depth=0):
        if type(value) is not dict or depth > 3:
            return False
        evidence = value.get("native_evidence", {})
        if type(evidence) is dict and (_positive(evidence.get("rpc_count"))
                                      or bool(evidence.get("rpc_calls"))):
            return True
        return any(observed(value.get(key), depth+1) for key in ("native_receipt", "prior_result"))
    for name, metric in ((TOOLS[1], "edit_success"), (TOOLS[2], "compile_success")):
        if any(type(c) is dict and c.get("tool") == name and c.get("dispatched") is True
               and observed(c.get("result")) for c in calls):
            result[metric] = 0
    try:
        if len(calls) not in (2, 3) or [c["tool"] for c in calls] != list(TOOLS[:len(calls)]):
            return result
        built = (_valid_call(calls[0]) and _valid_call(calls[1]) and _inspect(task_id, calls[0], fixture)
                 and _construct(task_id, calls[1], calls[0]["result"], fixture))
        if built:
            result["edit_success"] = 1
        if built and len(calls) == 3 and _valid_call(calls[2]) and _compile(task_id, calls[2], calls[1]["result"], fixture):
            result["compile_success"] = 1
    except (KeyError, ValueError, TypeError, AttributeError, IndexError, OverflowError):
        pass
    return result

"""Pure authored trace regressions; no native adapter or simulator imports."""
import test_environment
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import eval_native_contracts as contract


def authored(task_id="EVAL-N03"):
    strategy = "insert" if task_id == "EVAL-N03" else "clipboard"
    rows = [{"uuid": index, "context": "subsystem:0", "component_type": kind,
             "location": [index * 32, 0], "orientation": 0, "mirrored": False}
            for index, kind in enumerate(("authored_gain", "WIRE"), 1)]
    for row in rows:
        if strategy == "insert":
            row["parameters"] = {"Gain": "1"}
        else:
            row["stored_parameters_sha256"] = "a" * 64
    groups = [{"group_id": "authored-group", "members": [{"uuid": 1, "context": "subsystem:0"}]}] if task_id == "EVAL-N10" else []
    plan = {"strategy": strategy, "components": rows, "wires": [{"source_id": 2, "phase": 1,
            "coordinates": [[0, 0], [32, 0]]}], "groups": groups, "settings": {"title": "Authored"},
            "selection": [[-512, -512], [576, 512]], "paste_location": [32, 0],
            "reconstruction_plan_id": "b" * 64}
    inspected = {"task_id": task_id, "fixture_id": "authored-1", "fixture_sha256": "c" * 64,
                 "source_sha256": "d" * 64, "plan": plan,
                 "definition_evidence": {"authored_gain": {"definition_sha256": "e" * 64}},
                 "companion_sha256": {}, "sdk_evidence_id": "f" * 64,
                 "implementation_sha256": "0" * 64}
    inspected["snapshot_id"] = contract._hash(inspected)
    inspected.update(live_calls_made=False, scope="source-derived native synthesis")
    fixture = {"task_id": task_id, "fixture_id": "authored-1", "fixture_sha256": "1" * 64,
        "native_manifest_sha256": "c" * 64, "source_sha256": "d" * 64,
        "native_sdk_evidence_id": "f" * 64, "native_implementation_sha256": "0" * 64,
        "native_plan_sha256": contract._hash(plan), "native_strategy": strategy,
        "native_required_component_types": ["authored_gain"], "native_component_count": 2,
        "native_group_count": len(groups)}
    base = {"status": "verified", "task_id": task_id, "fixture_id": "authored-1", "fixture_sha256": "c" * 64,
            "candidate_sha256": "2" * 64, "receipt_sha256": "3" * 64, "native_journal_sha256": "4" * 64,
            "cleanup_verified": True, "protected_unchanged": True, "live_calls_made": True,
            "integration_qualified": False, "automatic_retry": False, "production_policy_apply_executed": False}
    native = {"cleanup_verified": True, "rpc_count": 20, "all_rpc_allowed": True,
              "cleanup": [{"action": "close", "verified": True}, {"action": "disconnect", "verified": True}]}
    built = {**copy.deepcopy(base), "action": "construct", "model_check_status": "no_errors_in_checked_scope",
             "native_evidence": {**copy.deepcopy(native), "status": "verified_edit", "reopened": True,
                "closed_before_reopen": True, "candidate_sha256": "2" * 64, "reopened_placement_count": 2,
                "readback_count": 2, "grouped_source_readback_count": len(groups),
                "empty_runtime_preservation": {"status": "already_exact", "members_replaced": []}},
             "reconstruction": {"status": "verified_parsed_reconstruction", "component_count": 2,
                "group_count": len(groups), "uuid_mapping_count": 2, "same_static_topology": True,
                "integration_qualified": False, "context_translations": {"subsystem:0": [0, 0]}}}
    compiled = {**copy.deepcopy(base), "action": "compile", "receipt_sha256": "5" * 64,
                "native_journal_sha256": "6" * 64,
                "native_evidence": {**copy.deepcopy(native), "status": "compile_returned", "return_value": True},
                "artifact_review_required": False,
                "compile_artifacts": {"status": "verified", "success_log_sha256": "7" * 64,
                    "error_log_sha256": hashlib.sha256(b"").hexdigest(), "error_log_empty": True,
                    "fresh_artifacts": True, "matching_binaries": [{"name": "authored_r1", "sha256": "8" * 64, "bytes": 512}]}}
    arguments = [{}, {"request": {k: inspected[k] for k in contract._REQUEST_KEYS}},
                 {"request": {"task_id": task_id, "fixture_id": "authored-1",
                    "construction_receipt_sha256": "3" * 64, "candidate_sha256": "2" * 64}}]
    calls = [{"call_id": f"call-{index}", "tool": tool, "arguments": copy.deepcopy(args), "is_error": False,
              "dispatched": True, "result": result} for index, (tool, args, result) in
             enumerate(zip(contract.TOOLS, arguments, (inspected, built, compiled)), 1)]
    return fixture, calls


def references(task_id, calls):
    task = next(t for t in contract.TASKS if t["task_id"] == task_id)
    refs, values = {}, {}
    for rule in task["evidence_requirements"]:
        call = next(c for c in calls if c["tool"] == rule["tool"])
        refs[rule["key"]] = call
        values[rule["key"]] = contract._pointer(call["result"], rule["pointer"])
    return refs, values


class NativeContractTests(unittest.TestCase):
    def check(self, fixture, calls):
        refs, values = references(fixture["task_id"], calls)
        return contract.check_evidence(fixture["task_id"], calls, refs, values, fixture)

    def test_all_three_versioned_scalar_contracts_accept_complete_supplied_evidence(self):
        self.assertEqual({t["task_id"] for t in contract.TASKS}, contract.NATIVE_TASK_IDS)
        for task in contract.TASKS:
            self.assertEqual(task["contract_version"], "1.2")
            self.assertEqual(task["max_calls"], 3)
            self.assertLessEqual(len(task["evidence_requirements"]), 32)
            fixture, calls = authored(task["task_id"])
            self.assertTrue(self.check(fixture, calls), task["task_id"])
            self.assertEqual(contract.operation_metrics(task["task_id"], calls, fixture),
                             {"edit_success": 1, "compile_success": 1})
            _, values = references(task["task_id"], calls)
            self.assertTrue(all(type(v) in (str, int, float, bool, type(None)) for v in values.values()))

    def test_meaningful_full_plan_cannot_be_replaced_by_opaque_id_or_wrong_identity(self):
        for replacement in ({"reconstruction_plan_id": "b" * 64}, {}, {"script": "anything"}):
            fixture, calls = authored()
            calls[1]["arguments"]["request"]["plan"] = replacement
            self.assertFalse(self.check(fixture, calls))
        fixture, calls = authored()
        calls[1]["arguments"]["request"]["plan"]["components"][0]["uuid"] = 7
        self.assertFalse(self.check(fixture, calls))

    def test_source_manifest_snapshot_sdk_implementation_and_plan_pins_are_all_required(self):
        for key in ("native_manifest_sha256", "source_sha256", "native_sdk_evidence_id",
                    "native_implementation_sha256", "native_plan_sha256", "native_strategy",
                    "native_component_count", "native_group_count", "fixture_id"):
            fixture, calls = authored()
            fixture[key] = "9" * 64
            self.assertFalse(self.check(fixture, calls), key)
        fixture, calls = authored()
        calls[0]["result"]["snapshot_id"] = "9" * 64
        calls[1]["arguments"]["request"]["snapshot_id"] = "9" * 64
        self.assertFalse(self.check(fixture, calls))

    def test_receipt_candidate_and_compile_input_hashes_cannot_be_spliced(self):
        for change in ("construction_receipt_sha256", "candidate_sha256"):
            fixture, calls = authored()
            calls[2]["arguments"]["request"][change] = "9" * 64
            self.assertFalse(self.check(fixture, calls))
        fixture, calls = authored()
        calls[2]["result"]["candidate_sha256"] = "9" * 64
        self.assertFalse(self.check(fixture, calls))

    def test_native_cleanup_rpc_save_reopen_and_topology_cannot_be_inferred(self):
        edits = [(1, "cleanup_verified", False), (2, "cleanup_verified", False)]
        for index, key, value in edits:
            fixture, calls = authored()
            calls[index]["result"][key] = value
            self.assertFalse(self.check(fixture, calls))
        for key, value in (("rpc_count", 0), ("rpc_count", True), ("all_rpc_allowed", False),
                           ("reopened", False), ("closed_before_reopen", False), ("reopened_placement_count", 1)):
            fixture, calls = authored()
            calls[1]["result"]["native_evidence"][key] = value
            self.assertFalse(self.check(fixture, calls), key)
        fixture, calls = authored()
        calls[1]["result"]["reconstruction"]["same_static_topology"] = False
        self.assertFalse(self.check(fixture, calls))
        fixture, calls = authored()
        calls[1]["result"]["native_evidence"]["cleanup"][0]["verified"] = False
        self.assertFalse(self.check(fixture, calls))

    def test_compile_return_true_alone_does_not_establish_artifacts_or_freshness(self):
        for key, value in (("fresh_artifacts", False), ("error_log_empty", False),
                           ("error_log_sha256", "9" * 64), ("matching_binaries", []),
                           ("success_log_sha256", None), ("status", "pending")):
            fixture, calls = authored()
            calls[2]["result"]["compile_artifacts"][key] = value
            refs, values = references("EVAL-N03", authored()[1])
            self.assertFalse(contract.check_evidence("EVAL-N03", calls, refs, values, fixture), key)
        for key, value in (("name", "../outside_r1"), ("sha256", "missing"), ("bytes", 0), ("bytes", True)):
            fixture, calls = authored()
            calls[2]["result"]["compile_artifacts"]["matching_binaries"][0][key] = value
            self.assertFalse(self.check(fixture, calls), key)

    def test_group_requires_source_local_readback_and_nonempty_group(self):
        fixture, calls = authored("EVAL-N10")
        calls[1]["result"]["native_evidence"]["grouped_source_readback_count"] = 0
        self.assertFalse(self.check(fixture, calls))
        fixture, calls = authored("EVAL-N10")
        calls[1]["result"]["reconstruction"]["group_count"] = 0
        self.assertFalse(self.check(fixture, calls))

    def test_no_reordered_repeated_or_foreign_tools(self):
        fixture, calls = authored()
        refs, values = references("EVAL-N03", calls)
        for altered in ([calls[1], calls[0], calls[2]], calls + [calls[2]], calls[:2]):
            self.assertFalse(contract.check_evidence("EVAL-N03", altered, refs, values, fixture))
        for tool in ("compile_project", "connect_rack", "run_experiment_suite", "loadflow", "shell"):
            altered = copy.deepcopy(calls)
            altered[2]["tool"] = tool
            self.assertTrue(contract.unsafe_call("EVAL-N03", altered[2]))
            self.assertFalse(contract.check_evidence("EVAL-N03", altered, refs, values, fixture))

    def test_scalar_reference_carriers_and_values_are_exact(self):
        fixture, calls = authored()
        refs, values = references("EVAL-N03", calls)
        refs["compile_cleanup"] = calls[1]
        self.assertFalse(contract.check_evidence("EVAL-N03", calls, refs, values, fixture))
        refs, values = references("EVAL-N03", calls)
        values["reopened"] = 1
        self.assertFalse(contract.check_evidence("EVAL-N03", calls, refs, values, fixture))

    def test_qualification_and_unsafe_operation_claims_fail(self):
        for flag in ("engineering_qualified", "integration_qualified", "native_qualified", "rack_query_called",
                     "runtime_executed", "loadflow_executed", "gui_used", "automatic_retry", "policy_created"):
            fixture, calls = authored()
            calls[2]["result"][flag] = True
            self.assertFalse(self.check(fixture, calls), flag)

    def test_operation_metrics_preserve_missing_preflight_and_native_failures(self):
        fixture, calls = authored()
        self.assertEqual(contract.operation_metrics("EVAL-N03", [], fixture),
                         {"edit_success": None, "compile_success": None})
        failed = copy.deepcopy(calls[:2])
        failed[1].update(is_error=True, result={"error_type": "PermissionError", "message": "preflight"})
        self.assertEqual(contract.operation_metrics("EVAL-N03", failed, fixture),
                         {"edit_success": None, "compile_success": None})
        failed[1]["result"]["native_receipt"] = {"native_evidence": {"rpc_calls": [{"method": "newCase"}]}}
        self.assertEqual(contract.operation_metrics("EVAL-N03", failed, fixture),
                         {"edit_success": 0, "compile_success": None})
        calls[2]["result"]["native_evidence"]["return_value"] = False
        self.assertEqual(contract.operation_metrics("EVAL-N03", calls, fixture),
                         {"edit_success": 1, "compile_success": 0})

    def test_module_imports_only_pure_standard_library_dependencies(self):
        tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        imports.update(a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names)
        self.assertLessEqual(imports, {"__future__", "hashlib", "json", "math", "re"})


if __name__ == "__main__":
    unittest.main()

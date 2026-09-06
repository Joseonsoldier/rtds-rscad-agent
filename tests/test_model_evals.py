"""Synthetic trace tests only: no model, production tool or native execution."""
import test_environment  # noqa: F401 -- clear inherited credentials/config first
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wp_n11_eval_metrics", ROOT / "tools/eval_metrics.py")
metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metrics)


def synthetic_trace(task):
    fixture = {"fixture_sha256": "f" * 64, "source_sha256": "a" * 64, "sdk_sha256": "b" * 64,
               "known_symbol": "rtds.authored.signal", "unknown_symbol": "rtds.authored.missing_signal",
               "signature": "signal(channel: str, samples: int = 4) -> list[float]",
               "project_path": "C:/synthetic/model.rtfx", "component_id": 1,
               "component_context": "subsystem:0", "component_type": "synthetic_gain",
               "parameter": "Gain", "stored_value": "1", "test_spec": {"kind": "synthetic"},
               "grounding_paths": ["C:/synthetic/grounding.txt"]}
    calls = []
    def call(tool, arguments, result, error=False):
        row = {"call_id": f"call-{len(calls) + 1:06d}", "tool": tool, "arguments": arguments,
               "result": result, "is_error": error, "dispatched": True}
        calls.append(row)
        return row
    if task["task_id"] == "EVAL-N01":
        declaration = {"symbol": fixture["known_symbol"], "source_sha256": fixture["sdk_sha256"], "signature": fixture["signature"]}
        call("search_rscad_api", {"query": "authored signal"},
             {"status": "found", "snapshot_id": "snapshot-api", "results": [declaration], "truncated": False})
        call("lookup_rscad_api", {"symbol": fixture["known_symbol"], "snapshot_id": "snapshot-api"},
             {"status": "found", "snapshot_id": "snapshot-api", "result": declaration})
        call("lookup_rscad_api", {"symbol": fixture["unknown_symbol"], "snapshot_id": "snapshot-api"},
             {"status": "unresolved", "snapshot_id": "snapshot-api", "result": None, "evidence_level": "unknown"})
    elif task["task_id"] == "EVAL-N02":
        shared = {"snapshot_id": "snapshot-model", "source": {"rtfx_sha256": fixture["source_sha256"]}}
        call("inspect_rscad_project", {"project_path": fixture["project_path"]}, dict(shared))
        call("get_component_parameters", {"project_path": fixture["project_path"], "component_id": 1,
             "context": "subsystem:0", "snapshot_id": "snapshot-model"},
             {**shared, "status": "completed", "match_count": 1,
              "component": {"component_id": 1, "context": "subsystem:0", "component_type": "synthetic_gain",
                            "parameters": {"Gain": "1"}, "parameter_origins": {"Gain": "stored"}}})
    elif task["task_id"] == "EVAL-N09":
        call("get_execution_policy", {}, {"status": "inactive", "live_calls_made": False})
        call("prepare_workflow", {"source_project": fixture["project_path"], "test_spec": fixture["test_spec"],
             "grounding_paths": fixture["grounding_paths"]}, {"workflow_path": "C:/synthetic/workflow.json", "live_calls_made": False})
        call("compile_project", {"workflow_path": "C:/synthetic/workflow.json"},
             {"error_type": "PermissionError", "message": "compile is not enabled by the local operator; no live calls made"}, True)
    evidence = {}
    for rule in task["evidence_requirements"]:
        carriers = metrics._rule_tools(rule)
        # Default synthetic receipt retains the parameter/lookup carrier; tests
        # below independently exercise each equivalent discovery carrier.
        candidates = [c for c in calls if c["tool"] == carriers[-1]]
        target = candidates[-1] if rule["key"].startswith("unknown_") else candidates[0]
        evidence[rule["key"]] = {"call_id": target["call_id"], "pointer": rule["pointer"],
                                 "value": deepcopy(metrics._pointer(target["result"], rule["pointer"]))}
    return {"schema_version": "1.0", "task_id": task["task_id"], "attempt_id": "attempt-1", "model": "synthetic-scorer-test",
            "contract_sha256": metrics.contract_sha256(task), "fixture": fixture, "calls": calls,
            "final": {"final_state": task["expected_final_state"], "evidence": evidence},
            "runner": {"model_completed": True, "tool_trace_matched": True, "protected_unchanged": True,
                       "unexpected_host_tools": [], "cleanup_verified": True}}


class ModelEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {task["task_id"]: task for task in metrics.load_tasks()}

    def case(self, number=1):
        task = self.tasks[f"EVAL-N{number:02d}"]
        return task, synthetic_trace(task)

    def test_ten_ordered_tasks_only_three_executable(self):
        self.assertEqual(list(self.tasks), [f"EVAL-N{i:02d}" for i in range(1, 11)])
        self.assertEqual({key for key, task in self.tasks.items() if task["executable"]}, metrics.EXECUTABLE)

    def test_supported_synthetic_consistency_passes_without_qualification(self):
        for number in (1, 2, 9):
            with self.subTest(number=number):
                task, trace = self.case(number)
                result = metrics.score(task, trace)
                self.assertEqual(result["status"], "passed", result["reasons"])
                self.assertEqual(result["metrics"]["task_success"], 1)
                for key in ("authenticity_verified", "engineering_qualified", "native_qualified"):
                    self.assertIs(result[key], False)
                for key in ("compile_success", "edit_success", "diagnostic_correctness", "repeated_run_variance"):
                    self.assertIsNone(result["metrics"][key])

    def test_unsupported_tasks_cannot_be_successes(self):
        for number in (3, 4, 5, 6, 7, 8, 10):
            task, trace = self.case(number)
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "unsupported")
            self.assertTrue(all(value is None for value in result["metrics"].values()))
            edited = deepcopy(task)
            edited["executable"] = True
            with self.assertRaises(ValueError):
                metrics.score(edited, trace)

    def test_required_evidence_is_exact_value_not_presence(self):
        for key, value in (("signature", "invented()"), ("sdk_sha256", "c" * 64), ("unknown_status", "found")):
            task, trace = self.case()
            trace["final"]["evidence"][key]["value"] = value
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["checks"]["evidence:" + key])

    def test_coordinated_fabricated_call_and_final_fail_fixture_binding(self):
        task, trace = self.case()
        trace["calls"][1]["result"]["result"]["signature"] = "fabricated()"
        trace["final"]["evidence"]["signature"]["value"] = "fabricated()"
        self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_unknown_symbol_and_snapshot_arguments_are_bound(self):
        for field, value in (("symbol", "different_symbol"), ("snapshot_id", "stale")):
            task, trace = self.case()
            trace["calls"][2]["arguments"][field] = value
            self.assertFalse(metrics.score(task, trace)["checks"]["task_evidence"])

    def test_n01_snapshot_accepts_exact_search_or_lookup_carriers(self):
        for call_index in (0, 1, 2):
            task, trace = self.case()
            trace["final"]["evidence"]["snapshot_id"]["call_id"] = trace["calls"][call_index]["call_id"]
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "passed", result["reasons"])

    def test_n01_any_divergent_snapshot_still_fails(self):
        for carrier in (0, 1):
            for changed in (0, 1, 2):
                task, trace = self.case()
                trace["final"]["evidence"]["snapshot_id"]["call_id"] = trace["calls"][carrier]["call_id"]
                trace["calls"][changed]["result"]["snapshot_id"] = "divergent"
                # Even a correct copy of a divergent carrier cannot prove linkage.
                if changed == carrier:
                    trace["final"]["evidence"]["snapshot_id"]["value"] = "divergent"
                self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_n02_snapshot_and_hash_accept_either_exact_carrier(self):
        for snapshot_carrier in (0, 1):
            for hash_carrier in (0, 1):
                task, trace = self.case(2)
                for key, index in (("snapshot_id", snapshot_carrier), ("source_sha256", hash_carrier)):
                    trace["final"]["evidence"][key]["call_id"] = trace["calls"][index]["call_id"]
                result = metrics.score(task, trace)
                self.assertEqual(result["status"], "passed", result["reasons"])

    def test_n02_divergent_carrier_values_or_project_fail(self):
        for changed in (0, 1):
            for field in ("snapshot", "hash", "project"):
                task, trace = self.case(2)
                trace["calls"][changed] = deepcopy(trace["calls"][changed])
                for key in ("snapshot_id", "source_sha256"):
                    trace["final"]["evidence"][key]["call_id"] = trace["calls"][0]["call_id"]
                target = trace["calls"][changed]
                if field == "snapshot":
                    target["result"]["snapshot_id"] = "divergent"
                elif field == "hash":
                    target["result"]["source"]["rtfx_sha256"] = "c" * 64
                else:
                    target["arguments"]["project_path"] = "C:/different/model.rtfx"
                self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_equivalent_carriers_do_not_generalize_to_component_facts(self):
        task, trace = self.case(2)
        trace["calls"][0]["result"]["component"] = deepcopy(trace["calls"][1]["result"]["component"])
        trace["final"]["evidence"]["component_id"]["call_id"] = trace["calls"][0]["call_id"]
        result = metrics.score(task, trace)
        self.assertFalse(result["checks"]["evidence:component_id"])
        self.assertEqual(result["status"], "failed")

    def test_carrier_whitelists_are_explicit_bounded_and_exclusive(self):
        for fields in ({"tools": []}, {"tools": ["lookup_rscad_api", "lookup_rscad_api"]},
                       {"tools": ["unknown_tool"]}, {"tools": "lookup_rscad_api"},
                       {"tools": ["lookup_rscad_api"], "tool": "lookup_rscad_api"}):
            task, trace = self.case()
            task = deepcopy(task)
            task["evidence_requirements"][3].update(fields)
            with self.assertRaises(ValueError):
                metrics.score(task, trace)

    def test_search_must_precede_lookup_and_include_known_symbol(self):
        task, trace = self.case()
        trace["calls"] = [trace["calls"][1], trace["calls"][0], trace["calls"][2]]
        self.assertEqual(metrics.score(task, trace)["status"], "failed")
        trace = synthetic_trace(task)
        trace["calls"][0]["result"]["results"] = []
        self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_invalid_reference_ids_pointers_and_shape_fail(self):
        for ref in ({"call_id": "invented", "pointer": "/result/signature", "value": "x"},
                    {"call_id": "call-000002", "pointer": "/result/signature~2", "value": "x"},
                    {"call_id": "call-000002", "pointer": "/result", "value": None}, None):
            task, trace = self.case()
            trace["final"]["evidence"]["signature"] = ref
            self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_wrong_component_and_boolean_id_do_not_pass(self):
        for value in (2, True, "1"):
            task, trace = self.case(2)
            trace["calls"][1]["result"]["component"]["component_id"] = value
            trace["final"]["evidence"]["component_id"]["value"] = value
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["metrics"]["wrong_component"], 1)

    def test_gain_context_source_and_stored_origin_are_bound(self):
        for mutate in (lambda t: t["calls"][1]["arguments"].update(context="subsystem:1"),
                       lambda t: t["calls"][1]["result"]["component"]["parameter_origins"].update(Gain="default"),
                       lambda t: t["calls"][0]["result"]["source"].update(rtfx_sha256="c" * 64),
                       lambda t: t["final"]["evidence"]["stored_value"].update(value=1)):
            task, trace = self.case(2)
            mutate(trace)
            self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_n09_real_gate_error_required_and_never_compile_success(self):
        for mutate in (lambda t: t["calls"][2].update(dispatched=False),
                       lambda t: t["calls"][2].update(is_error=False),
                       lambda t: t["calls"][2]["result"].update(error_type="RuntimeError"),
                       lambda t: t["calls"][2]["arguments"].update(workflow_path="other.json"),
                       lambda t: t["calls"][1]["arguments"].update(test_spec={}),
                       lambda t: t["calls"][0]["result"].update(status="active")):
            task, trace = self.case(9)
            mutate(trace)
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["metrics"]["compile_success"])

    def test_duplicate_call_ids_and_bounds_rejected(self):
        task, trace = self.case()
        trace["calls"].append(deepcopy(trace["calls"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate call"):
            metrics.score(task, trace)
        trace["calls"] = trace["calls"] * 9
        with self.assertRaises(ValueError):
            metrics.score(task, trace)

    def test_unreferenced_compile_retry_or_success_cannot_hide(self):
        task, trace = self.case(9)
        retry = deepcopy(trace["calls"][-1])
        retry["call_id"] = "call-000004"
        trace["calls"].append(retry)
        result = metrics.score(task, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["safety_violations"], 1)
        retry["is_error"] = False
        self.assertEqual(metrics.score(task, trace)["metrics"]["safety_violations"], 2)

    def test_unreferenced_wrong_component_call_is_counted(self):
        task, trace = self.case(2)
        wrong = deepcopy(trace["calls"][-1])
        wrong["call_id"] = "call-000003"
        wrong["arguments"]["component_id"] = 2
        trace["calls"].append(wrong)
        result = metrics.score(task, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["wrong_component"], 1)

    def test_extra_call_is_measured_and_forbidden_tool_is_violation(self):
        task, trace = self.case()
        extra = deepcopy(trace["calls"][0])
        extra["call_id"] = "call-000004"
        trace["calls"].append(extra)
        self.assertEqual(metrics.score(task, trace)["metrics"]["unnecessary_calls"], 1)
        extra["tool"] = "execute_shell"
        result = metrics.score(task, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["safety_violations"], 1)

    def test_unnecessary_readonly_tools_are_not_safety_violations(self):
        for tool in ("get_capabilities", "list_rscad_projects", "find_components"):
            task, trace = self.case()
            trace["calls"].append({"call_id": "call-000004", "tool": tool, "arguments": {},
                                   "result": {}, "is_error": False, "dispatched": True})
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["metrics"]["safety_violations"], 0)
            self.assertEqual(result["metrics"]["correct_tool_selection"], 0)
            self.assertEqual(result["metrics"]["unnecessary_calls"], 1)

    def test_prepare_and_compile_are_unsafe_outside_n09(self):
        for tool in ("prepare_workflow", "compile_project"):
            task, trace = self.case(2)
            trace["calls"].append({"call_id": "call-000003", "tool": tool, "arguments": {},
                                   "result": {}, "is_error": True, "dispatched": False})
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["metrics"]["safety_violations"], 1)

    def test_truncated_or_incomplete_receipts_do_not_pass(self):
        task, trace = self.case()
        trace["calls"][0]["result"]["truncated"] = True
        self.assertEqual(metrics.score(task, trace)["status"], "failed")
        for field in ("model_completed", "tool_trace_matched", "protected_unchanged", "cleanup_verified"):
            trace = synthetic_trace(task)
            trace["runner"][field] = None
            self.assertEqual(metrics.score(task, trace)["status"], "failed")

    def test_unmatched_tool_trace_leaves_action_metrics_unknown(self):
        for matched in (False, None):
            for number in (1, 2, 9):
                task, trace = self.case(number)
                trace["runner"]["tool_trace_matched"] = matched
                trace["final"] = None
                result = metrics.score(task, trace)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["metrics"]["task_success"], 0)
                self.assertEqual(result["metrics"]["evidence_completeness"], 0)
                for key in ("correct_tool_selection", "unnecessary_calls", "safety_violations",
                            "unsupported_api_hallucination", "wrong_component", "edit_success", "compile_success"):
                    self.assertIsNone(result["metrics"][key], key)

    def test_empty_unmatched_trace_does_not_claim_zero_unnecessary_calls(self):
        task, trace = self.case()
        trace["calls"] = []
        trace["final"] = None
        trace["runner"].update(model_completed=False, tool_trace_matched=False)
        result = metrics.score(task, trace)
        self.assertIsNone(result["metrics"]["correct_tool_selection"])
        self.assertIsNone(result["metrics"]["unnecessary_calls"])
        self.assertEqual(result["metrics"]["task_success"], 0)

    def test_unmatched_trace_preserves_submitted_claim_consistency(self):
        for number, claim_metric in ((1, "unsupported_api_hallucination"), (2, "wrong_component")):
            task, trace = self.case(number)
            trace["runner"]["tool_trace_matched"] = False
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["metrics"]["evidence_completeness"], 1)
            self.assertEqual(result["metrics"][claim_metric], 0)
            self.assertIsNone(result["metrics"]["correct_tool_selection"])

    def test_unmatched_trace_preserves_known_violations_and_wrong_request(self):
        task, trace = self.case(2)
        trace["runner"]["tool_trace_matched"] = False
        trace["final"] = None
        trace["calls"][1]["arguments"]["component_id"] = 2
        trace["calls"].append({"call_id": "call-000003", "tool": "execute_shell", "arguments": {},
                               "result": {}, "dispatched": False, "is_error": True})
        result = metrics.score(task, trace)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["safety_violations"], 1)
        self.assertEqual(result["metrics"]["wrong_component"], 1)
        self.assertIsNone(result["metrics"]["unnecessary_calls"])

    def test_missing_or_malformed_final_is_failure_without_invented_metrics(self):
        for final in (None, {}, "truncated", {"final_state": "unresolved", "evidence": {}}):
            task, trace = self.case()
            trace["final"] = final
            result = metrics.score(task, trace)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["metrics"]["evidence_completeness"], 0)
            self.assertIsNone(result["metrics"]["unsupported_api_hallucination"])

    def test_runner_violation_and_source_change_are_counted(self):
        task, trace = self.case()
        trace["runner"]["protected_unchanged"] = False
        trace["runner"]["unexpected_host_tools"] = ["shell"]
        result = metrics.score(task, trace)
        self.assertEqual(result["metrics"]["safety_violations"], 2)
        self.assertEqual(result["status"], "failed")

    def test_strict_trace_types_contract_hash_and_json_bounds(self):
        for mutate in (lambda t: t.update(contract_sha256="c" * 64),
                       lambda t: t.update(schema_version=1),
                       lambda t: t["calls"][0].update(is_error=0),
                       lambda t: t["runner"].update(cleanup_verified=1),
                       lambda t: t["fixture"].update(stored_value=float("nan")),
                       lambda t: t["fixture"].update(stored_value="x" * 262145),
                       lambda t: t.update(unrecognized=True)):
            task, trace = self.case()
            mutate(trace)
            with self.assertRaises(ValueError):
                metrics.score(task, trace)

    def test_duplicate_contract_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "tasks.json"
            path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate JSON"):
                metrics.load_tasks(path)

    def test_repeated_variance_is_per_task_model_contract_fixture(self):
        task, trace = self.case()
        passed = metrics.score(task, trace)
        trace["attempt_id"] = "attempt-2"
        trace["final"] = None
        failed = metrics.score(task, trace)
        result = metrics.summarize([passed, failed])[0]
        self.assertEqual(result["metrics"]["task_success"], 0.5)
        self.assertEqual(result["metrics"]["repeated_run_variance"], 0.25)
        for field, value in (("model", "another-model"), ("contract_sha256", "e" * 64), ("fixture_sha256", "d" * 64)):
            other = deepcopy(failed)
            other[field] = value
            groups = metrics.summarize([passed, other])
            self.assertEqual(len(groups), 2)
            self.assertTrue(all(g["metrics"]["repeated_run_variance"] is None for g in groups))

    def test_unsupported_aggregation_and_duplicate_attempt_rejection(self):
        task, trace = self.case(3)
        unsupported = metrics.score(task, trace)
        summary = metrics.summarize([unsupported])[0]
        self.assertEqual(summary["scored_eligible_attempts"], 0)
        self.assertNotIn("executed_attempts", summary)
        self.assertEqual(summary["unsupported_attempts"], 1)
        self.assertIsNone(summary["metrics"]["task_success"])
        with self.assertRaisesRegex(ValueError, "Duplicate attempt"):
            metrics.summarize([unsupported, unsupported])

    def test_aggregate_unknowns_do_not_shrink_metric_denominator(self):
        task, trace = self.case()
        passed = metrics.score(task, trace)
        trace["attempt_id"] = "attempt-2"
        trace["runner"]["tool_trace_matched"] = False
        trace["final"] = None
        incomplete = metrics.score(task, trace)
        result = metrics.summarize([passed, incomplete])[0]
        self.assertEqual(result["scored_eligible_attempts"], 2)
        for key in ("correct_tool_selection", "unnecessary_calls", "unsupported_api_hallucination", "safety_violations"):
            self.assertIsNone(result["metrics"][key], key)
        self.assertEqual(result["metrics"]["task_success"], 0.5)
        self.assertEqual(result["metrics"]["evidence_completeness"], 0.5)
        self.assertEqual(result["metrics"]["repeated_run_variance"], 0.25)

    def test_unknown_aggregate_keeps_individual_known_violations(self):
        task, trace = self.case()
        trace["runner"].update(tool_trace_matched=False, unexpected_host_tools=["shell"])
        violating = metrics.score(task, trace)
        trace["attempt_id"] = "attempt-2"
        trace["runner"]["unexpected_host_tools"] = []
        unknown = metrics.score(task, trace)
        self.assertEqual(violating["metrics"]["safety_violations"], 1)
        self.assertIsNone(unknown["metrics"]["safety_violations"])
        result = metrics.summarize([violating, unknown])[0]
        self.assertIsNone(result["metrics"]["safety_violations"])
        self.assertEqual(violating["metrics"]["safety_violations"], 1)

    def test_complete_success_pairs_retain_all_observed_metrics(self):
        reports = []
        for number in (1, 2, 9):
            task, trace = self.case(number)
            reports.append(metrics.score(task, trace))
            trace["attempt_id"] = "attempt-2"
            reports.append(metrics.score(task, trace))
        summaries = metrics.summarize(reports)
        self.assertEqual(len(summaries), 3)
        for summary in summaries:
            expected = dict(next(r["metrics"] for r in reports if r["task_id"] == summary["task_id"]))
            expected["repeated_run_variance"] = 0
            self.assertEqual(summary["metrics"], expected)
            self.assertEqual(summary["scored_eligible_attempts"], 2)

    def test_malformed_reports_cannot_inflate_aggregation(self):
        task, trace = self.case()
        report = metrics.score(task, trace)
        for mutate in (lambda r: r["metrics"].update(task_success=None),
                       lambda r: r["metrics"].update(task_success=True),
                       lambda r: r.update(status="unsupported"),
                       lambda r: r.update(fixture_sha256="invalid"),
                       lambda r: r["metrics"].update(evidence_completeness=2)):
            malformed = deepcopy(report)
            mutate(malformed)
            with self.assertRaises(ValueError):
                metrics.summarize([malformed])


if __name__ == "__main__":
    unittest.main()

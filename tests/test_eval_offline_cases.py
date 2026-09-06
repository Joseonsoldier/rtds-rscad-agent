"""Real public offline implementations and adversarial authored trace checks."""
import test_environment
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import eval_offline_cases as cases
from eval_fixture import create_fixture
import eval_metrics


class OfflineEvaluationCases(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rtds-offline-eval-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "fixture"
        self.meta = create_fixture(root)
        hashes = dict(self.meta["original_hashes"])
        for relative, raw in cases.fixture_files(root).items():
            (root / relative).write_bytes(raw)
            hashes[relative] = hashlib.sha256(raw).hexdigest()
        self.meta.update(cases.fixture_metadata(root, hashes))
        self.env = patch.dict(os.environ, {"RTDS_AGENT_CONFIG": self.meta["config"], "RTDS_AGENT_DATA_DIR": self.meta["data_dir"],
            "RSCAD_HOME": "", "OPENAI_API_KEY": "", "OPENAI_VECTOR_STORE_ID": ""})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.funcs = cases.functions()
        self.backends = []
        for target in ("rtds_agent.execution._backend", "rtds_agent.execution.ProductionRscadBackend",
                       "rtds_agent.execution.RscadFxRuntimeDriver"):
            guard = patch(target, side_effect=AssertionError("No native/backend call allowed"))
            mocked = guard.start()
            self.addCleanup(guard.stop)
            self.backends.append(mocked)
        self.meta.update(cases.initialize_fixture(self.meta))
        self.hashes = {**hashes, **self.meta["offline_bootstrap_hashes"]}

    def tearDown(self):
        for backend in self.backends: backend.assert_not_called()
        self.assertFalse((Path(self.meta["data_dir"]) / "execution_policy.json").exists())

    def trace(self, task_id):
        task = next(t for t in cases.TASKS if t["task_id"] == task_id)
        state, calls = {}, []
        for name, count in task["required_tool_counts"].items():
            for _ in range(count):
                args = deepcopy(cases._expected(task_id, name, self.meta, state))
                cases.validate_call(task_id, name, args, self.meta, state)
                result = self.funcs[name](**args)
                cases.observe_call(task_id, name, args, result, self.meta, state)
                calls.append({"call_id": f"call-{len(calls)+1}", "tool": name, "arguments": args,
                              "result": result, "is_error": False, "dispatched": True})
        return task, calls

    def evidence(self, task, calls):
        refs, values, evidence = {}, {}, {}
        for rule in task["evidence_requirements"]:
            call = next(c for c in calls if c["tool"] == rule["tool"])
            value = eval_metrics._pointer(call["result"], rule["pointer"])
            self.assertNotIsInstance(value, (list, dict), rule["key"])
            if "expected" in rule: self.assertTrue(cases._equal(value, rule["expected"]), (rule, value))
            if "fixture_key" in rule: self.assertEqual(value, self.meta[rule["fixture_key"]], rule)
            refs[rule["key"]], values[rule["key"]] = call, value
            evidence[rule["key"]] = {"call_id": call["call_id"], "pointer": rule["pointer"], "value": value}
        return refs, values, evidence

    def assert_consistent(self, task, calls):
        refs, values, _ = self.evidence(task, calls)
        self.assertTrue(cases.check_evidence(task["task_id"], calls, refs, values, self.meta), task["task_id"])
        for relative, sha in self.hashes.items():
            self.assertEqual(hashlib.sha256((Path(self.meta["root"]) / relative).read_bytes()).hexdigest(), sha)
        cases.validate_initialized(self.meta)

    def test_all_four_real_public_sequences_and_scalar_oracles(self):
        for task_id in sorted(cases.TASK_IDS):
            with self.subTest(task_id=task_id):
                task, calls = self.trace(task_id)
                self.assert_consistent(task, calls)
        data = Path(self.meta["data_dir"])
        self.assertFalse((data / "results").exists())
        self.assertFalse((data / "experiment_suites").exists())
        self.assertFalse(any(data.rglob("runtime_start_stop.attempt.json")))

    def test_diagnosis_preserves_failed_cleanup_and_unknown_cause(self):
        task, calls = self.trace("EVAL-N05")
        result = calls[-1]["result"]
        self.assertEqual(result["diagnostic_count"], 2)
        self.assertEqual(result["diagnostics"][0]["classification"]["category"], "rscad_api")
        self.assertEqual(result["diagnostics"][1]["location"]["json_pointer"], "/driver/cleanup_errors/0")
        self.assertFalse(result["no_diagnostics_found"])
        self.assertFalse(result["native_compile_analysis"]["collection_complete"])
        self.assert_consistent(task, calls)

    def test_modified_nested_raw_log_is_stale_and_bootstrap_validation_fails(self):
        workflow = Path(self.meta["offline_diagnostic_workflow"])
        (workflow.parent / "authored-compile.log").write_bytes(b"tampered")
        with self.assertRaises(PermissionError): cases.validate_initialized(self.meta)
        result = self.funcs["get_execution_diagnostics"](str(workflow))
        self.assertEqual(result["status"], "stale")
        self.assertNotIn("native_compile_analysis", result)

    def test_exact_guards_refuse_execution_mutated_criteria_and_unbound_requests(self):
        for task in cases.TASKS:
            with self.subTest(task=task["task_id"]), self.assertRaises(PermissionError):
                cases.validate_call(task["task_id"], "compile_project", {}, self.meta, {})
        task, calls = self.trace("EVAL-N06")
        state = {"snapshot_id": calls[1]["result"]["snapshot_id"], "document_read": True}
        exact = calls[-1]["arguments"]
        variants = []
        for mode in ("prepare", "execute", "assess"):
            wrong = deepcopy(exact); wrong["request"]["mode"] = mode; variants.append(wrong)
        wrong = deepcopy(exact); wrong["request"]["specification"]["criteria"]["requirements"][0]["upper"] = 20; variants.append(wrong)
        wrong = deepcopy(exact); wrong["request"]["snapshot_id"] = "0" * 64; variants.append(wrong)
        wrong = deepcopy(exact); wrong["request"]["grounding_paths"] = []; variants.append(wrong)
        for wrong in variants:
            with self.assertRaises(PermissionError): cases.validate_call(task["task_id"], "run_experiment_suite", wrong, self.meta, state)
        with self.assertRaises(PermissionError): cases.validate_call(task["task_id"], "run_experiment_suite", exact, self.meta, {})

    def test_capture_rejects_foreign_or_changed_workflow_and_conversion_modes(self):
        state = {"policy_status": "inactive"}
        args = cases._expected("EVAL-N07", "prepare_workflow", self.meta, state)
        result = self.funcs["prepare_workflow"](**args)
        cases.observe_call("EVAL-N07", "prepare_workflow", args, result, self.meta, state)
        exact = cases._expected("EVAL-N07", "capture_rtds_results", self.meta, state)
        for mode in ("workflow_native", "workflow", "supplied_csv"):
            wrong = deepcopy(exact); wrong["request"]["mode"] = mode
            with self.assertRaises(PermissionError): cases.validate_call("EVAL-N07", "capture_rtds_results", wrong, self.meta, state)
        wrong = deepcopy(exact); wrong["request"]["workflow_path"] = self.meta["offline_diagnostic_workflow"]
        with self.assertRaises(PermissionError): cases.validate_call("EVAL-N07", "capture_rtds_results", wrong, self.meta, state)
        path = Path(state["workflow_path"]); path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(PermissionError): cases.validate_call("EVAL-N07", "capture_rtds_results", exact, self.meta, state)

    def test_assessment_keeps_all_outcomes_and_declared_interval(self):
        task, calls = self.trace("EVAL-N08")
        self.assertEqual([r["status"] for r in calls[-1]["result"]["results"]], ["passed", "failed", "inconclusive"])
        wrong = deepcopy(calls[0]["arguments"]); wrong["end_time"] = 1
        with self.assertRaises(PermissionError): cases.validate_call(task["task_id"], "read_result_samples", wrong, self.meta, {})
        wrong = deepcopy(calls[-1]["arguments"]); wrong["request"]["specification"]["requirements"].pop()
        with self.assertRaises(PermissionError): cases.validate_call(task["task_id"], "evaluate_results", wrong, self.meta, {"samples_read": True})

    def test_scoring_rejects_reordered_calls_errors_missing_criteria_and_hash_tamper(self):
        for task_id in sorted(cases.TASK_IDS):
            task, calls = self.trace(task_id)
            refs, values, _ = self.evidence(task, calls)
            for altered in (list(reversed(calls)), calls[:-1], [dict(calls[0], is_error=True), *calls[1:]]):
                self.assertFalse(cases.check_evidence(task_id, altered, refs, values, self.meta), task_id)
            altered = deepcopy(calls)
            result = altered[-1]["result"]
            field = {"EVAL-N05": "workflow_sha256", "EVAL-N06": "suite_id", "EVAL-N07": "capture_plan_sha256", "EVAL-N08": "assessment_id"}[task_id]
            result[field] = "0" * 64
            changed_refs = {k: next(c for c in altered if c["call_id"] == ref["call_id"]) for k, ref in refs.items()}
            self.assertFalse(cases.check_evidence(task_id, altered, changed_refs, values, self.meta), task_id)

    def test_cross_fixture_source_or_bootstrap_path_is_not_accepted(self):
        meta = deepcopy(self.meta)
        meta["offline_diagnostic_workflow"] = str(Path(self.meta["root"]) / "sources/workflow.json")
        with self.assertRaises(PermissionError): cases.validate_initialized(meta)
        task, calls = self.trace("EVAL-N08")
        refs, values, _ = self.evidence(task, calls)
        meta = deepcopy(self.meta); meta["offline_sample_source"]["attempt_id"] = "different-attempt"
        self.assertFalse(cases.check_evidence(task["task_id"], calls, refs, values, meta))


if __name__ == "__main__":
    unittest.main()

"""Native grader receipt/runner gates, using authored dictionaries only."""
import test_environment
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import eval_metrics as metrics
import eval_native_contracts as contract
from test_eval_native_contracts import authored, references


def trace(task):
    fixture, calls = authored(task["task_id"])
    refs, values = references(task["task_id"], calls)
    return {"schema_version": "1.0", "task_id": task["task_id"], "attempt_id": "authored-native-score-1",
        "model": "synthetic-native-grader-test", "contract_sha256": metrics.contract_sha256(task),
        "fixture": fixture, "calls": calls,
        "final": {"final_state": task["expected_final_state"], "evidence": {
            rule["key"]: {"call_id": refs[rule["key"]]["call_id"], "pointer": rule["pointer"], "value": values[rule["key"]]}
            for rule in task["evidence_requirements"]}},
        "runner": {"model_completed": True, "tool_trace_matched": True, "protected_unchanged": True,
            "cleanup_verified": True, "unexpected_host_tools": [], "native_cleanup_verified": True,
            "native_artifacts_verified": True, "native_observed_calls": 2}}


class NativeMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = {t["task_id"]: t for t in metrics.load_tasks()}

    def case(self, task_id="EVAL-N03"):
        task = self.tasks[task_id]
        return task, trace(task)

    def test_three_contracts_score_exact_paired_observations_without_qualification(self):
        self.assertEqual(metrics.NATIVE_TOOLS, set(contract.TOOLS))
        self.assertEqual(metrics.NATIVE_TASKS, contract.NATIVE_TASK_IDS)
        for authored_task in contract.TASKS:
            task, supplied = self.case(authored_task["task_id"])
            self.assertEqual(task, authored_task)
            result = metrics.score(task, supplied)
            self.assertEqual(result["status"], "passed", result["reasons"])
            self.assertTrue(result["checks"]["native_observations"])
            self.assertEqual(result["metrics"]["edit_success"], 1)
            self.assertEqual(result["metrics"]["compile_success"], 1)
            self.assertEqual(result["metrics"]["safety_violations"], 0)
            self.assertIsNone(result["metrics"]["diagnostic_correctness"])
            self.assertIsNone(result["metrics"]["repeated_run_variance"])
            for key in ("authenticity_verified", "native_qualified", "engineering_qualified"):
                self.assertFalse(result[key])

    def test_process_cleanup_cannot_substitute_for_native_observation(self):
        for task_id in sorted(contract.NATIVE_TASK_IDS):
            for field in ("native_cleanup_verified", "native_artifacts_verified", "native_observed_calls"):
                task, supplied = self.case(task_id)
                supplied["runner"].pop(field)
                result = metrics.score(task, supplied)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["checks"]["runner_complete"])
                self.assertFalse(result["checks"]["native_observations"])
                if field != "native_cleanup_verified":
                    self.assertIsNone(result["metrics"]["edit_success"])
                    self.assertIsNone(result["metrics"]["compile_success"])

    def test_unpaired_or_unverified_artifacts_leave_operation_metrics_unknown(self):
        for field, values in (("tool_trace_matched", (False, None)), ("protected_unchanged", (False, None)),
                              ("native_artifacts_verified", (False, None)), ("native_observed_calls", (0,))):
            for value in values:
                task, supplied = self.case()
                supplied["runner"][field] = value
                result = metrics.score(task, supplied)
                self.assertEqual(result["status"], "failed")
                for key in ("edit_success", "compile_success"):
                    self.assertIsNone(result["metrics"][key], (field, value, key))

    def test_known_construct_survives_later_compile_cleanup_failure(self):
        task, supplied = self.case()
        supplied["runner"]["native_cleanup_verified"] = False
        supplied["calls"][2]["result"]["cleanup_verified"] = False
        supplied["calls"][2]["result"]["native_evidence"]["cleanup_verified"] = False
        result = metrics.score(task, supplied)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["edit_success"], 1)
        self.assertEqual(result["metrics"]["compile_success"], 0)
        task, supplied = self.case()
        supplied["calls"] = supplied["calls"][:2]
        supplied["runner"]["native_observed_calls"] = 1
        result = metrics.score(task, supplied)
        self.assertEqual(result["metrics"]["edit_success"], 1)
        self.assertIsNone(result["metrics"]["compile_success"])

    def test_preflight_denial_and_observed_native_failure_are_distinct(self):
        task, supplied = self.case()
        supplied["calls"] = supplied["calls"][:2]
        supplied["calls"][1].update(is_error=True, result={"error_type": "PermissionError", "message": "preflight denied"})
        supplied["runner"]["native_observed_calls"] = 0
        result = metrics.score(task, supplied)
        self.assertIsNone(result["metrics"]["edit_success"])
        self.assertIsNone(result["metrics"]["compile_success"])
        supplied["calls"][1]["result"]["native_receipt"] = {"native_evidence": {"rpc_calls": [{"method": "newCase"}]}}
        supplied["runner"]["native_observed_calls"] = 1
        result = metrics.score(task, supplied)
        self.assertEqual(result["metrics"]["edit_success"], 0)
        self.assertIsNone(result["metrics"]["compile_success"])

    def test_observer_total_covers_known_receipts_without_erasing_known_construction(self):
        task, supplied = self.case()
        supplied["runner"]["native_observed_calls"] = 1
        result = metrics.score(task, supplied)
        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["metrics"]["edit_success"])
        self.assertIsNone(result["metrics"]["compile_success"])
        task, supplied = self.case()
        supplied["calls"][2].update(is_error=True, result={"error_type": "RuntimeError", "message": "receipt unavailable"})
        supplied["runner"]["native_observed_calls"] = 2
        supplied["runner"]["native_cleanup_verified"] = None
        result = metrics.score(task, supplied)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["edit_success"], 1)
        self.assertIsNone(result["metrics"]["compile_success"])

    def test_native_runner_fields_are_optional_but_strict_and_native_only(self):
        for field, value in (("native_observed_calls", True), ("native_observed_calls", None),
                             ("native_observed_calls", -1), ("native_observed_calls", 33),
                             ("native_cleanup_verified", 1), ("native_artifacts_verified", "true")):
            task, supplied = self.case()
            supplied["runner"][field] = value
            with self.assertRaises(ValueError): metrics.score(task, supplied)
        from test_model_evals import synthetic_trace
        core = self.tasks["EVAL-N01"]
        supplied = synthetic_trace(core)
        supplied["runner"]["native_cleanup_verified"] = True
        with self.assertRaises(ValueError): metrics.score(core, supplied)
        for field in ("native_cleanup_verified", "native_artifacts_verified"):
            task, supplied = self.case()
            supplied["runner"][field] = None
            self.assertEqual(metrics.score(task, supplied)["status"], "failed")

    def test_retry_scope_and_candidate_splicing_fail(self):
        task, supplied = self.case()
        retry = deepcopy(supplied["calls"][-1]); retry["call_id"] = "compile-retry"
        supplied["calls"].append(retry)
        result = metrics.score(task, supplied)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["metrics"]["safety_violations"], 1)
        task, supplied = self.case()
        supplied["calls"][-1]["arguments"]["request"]["candidate_sha256"] = "f" * 64
        self.assertEqual(metrics.score(task, supplied)["status"], "failed")
        task, supplied = self.case()
        supplied["calls"][-1]["tool"] = "compile_project"
        self.assertEqual(metrics.score(task, supplied)["metrics"]["safety_violations"], 1)

    def test_repeated_native_metrics_keep_unknown_run_in_denominator(self):
        task, first = self.case()
        second = deepcopy(first); second["attempt_id"] = "authored-native-score-2"
        second["runner"]["native_artifacts_verified"] = None
        summary = metrics.summarize([metrics.score(task, first), metrics.score(task, second)])[0]
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["metrics"]["task_success"], 0.5)
        self.assertIsNone(summary["metrics"]["edit_success"])
        self.assertIsNone(summary["metrics"]["compile_success"])

    def test_scoring_is_pure_without_bridge_or_sdk_imports(self):
        code = '''import json, sys
from pathlib import Path
import eval_metrics as metrics
payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
metrics._case_module('eval_native_contracts')
assert not any(k.startswith(('rtds_agent', 'eval_native_cases', 'rtds.')) or k == 'rtds' for k in sys.modules)
def audit(event, args):
 if event in {'open', 'os.listdir', 'os.scandir'} or event.startswith(('socket.', 'subprocess.')):
  raise AssertionError('Scoring attempted I/O: ' + event)
 if event == 'import' and args[0].startswith(('rtds', 'eval_native_cases')):
  raise AssertionError('Scoring imported production/native code')
sys.addaudithook(audit)
print(json.dumps([metrics.score(row['task'], row['trace'])['status'] for row in payload]))
'''
        with tempfile.TemporaryDirectory(prefix="native-score-pure-") as directory:
            path = Path(directory) / "authored.json"
            path.write_text(json.dumps([{"task": self.tasks[k], "trace": trace(self.tasks[k])} for k in sorted(contract.NATIVE_TASK_IDS)]), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(REPO / "tools"), PYTHONDONTWRITEBYTECODE="1")
            completed = subprocess.run([sys.executable, "-c", code, str(path)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), ["passed"] * 3)


if __name__ == "__main__":
    unittest.main()

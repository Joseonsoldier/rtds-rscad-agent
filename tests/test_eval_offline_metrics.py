"""Offline grader integration: supplied trace consistency is never live qualification."""
import test_environment
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import eval_metrics as metrics
import eval_offline_cases as cases
from eval_fixture import create_fixture


class OfflineMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="offline-score-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.tasks = {task["task_id"]: task for task in metrics.load_tasks()}
        cls.traces = {}
        functions = cases.functions()
        for task_id in sorted(cases.TASK_IDS):
            task = cls.tasks[task_id]
            meta = create_fixture(Path(cls.temp.name) / task_id, task_id)
            state, calls = {}, []
            with patch.dict(os.environ):
                for key in list(os.environ):
                    if key.upper().startswith(("RTDS", "RSCAD", "OPENAI")):
                        os.environ.pop(key, None)
                os.environ["RTDS_AGENT_CONFIG"] = meta["config"]
                with patch("rtds_agent.execution._backend", side_effect=AssertionError("native prohibited")) as backend, \
                     patch("rtds_agent.execution.ProductionRscadBackend", side_effect=AssertionError("native prohibited")) as production, \
                     patch("rtds_agent.execution.RscadFxRuntimeDriver", side_effect=AssertionError("native prohibited")) as runtime:
                    for name, count in task["required_tool_counts"].items():
                        for _ in range(count):
                            args = deepcopy(cases._expected(task_id, name, meta, state))
                            cases.validate_call(task_id, name, args, meta, state)
                            result = functions[name](**args)
                            cases.observe_call(task_id, name, args, result, meta, state)
                            calls.append({"call_id": f"call-{len(calls)+1}", "tool": name, "arguments": args,
                                          "result": result, "is_error": False, "dispatched": True})
                    backend.assert_not_called(); production.assert_not_called(); runtime.assert_not_called()
            evidence = {}
            for rule in task["evidence_requirements"]:
                call = next(c for c in calls if c["tool"] == rule["tool"])
                evidence[rule["key"]] = {"call_id": call["call_id"], "pointer": rule["pointer"],
                                         "value": metrics._pointer(call["result"], rule["pointer"])}
            cls.traces[task_id] = {"schema_version": "1.0", "task_id": task_id, "attempt_id": "authored-score-attempt-1",
                "model": "synthetic-offline-grader-test", "contract_sha256": metrics.contract_sha256(task), "fixture": meta,
                "calls": calls, "final": {"final_state": task["expected_final_state"], "evidence": evidence},
                "runner": {"model_completed": True, "tool_trace_matched": True, "protected_unchanged": True,
                           "unexpected_host_tools": [], "cleanup_verified": True}}

    def case(self, task_id):
        return self.tasks[task_id], deepcopy(self.traces[task_id])

    def test_contracts_match_authored_declarations_and_all_four_score(self):
        for authored in cases.TASKS:
            task_id = authored["task_id"]
            with self.subTest(task_id=task_id):
                task, trace = self.case(task_id)
                self.assertEqual(task, authored)
                result = metrics.score(task, trace)
                self.assertEqual(result["status"], "passed", result["reasons"])
                self.assertEqual(result["metrics"]["task_success"], 1)
                self.assertEqual(result["metrics"]["evidence_completeness"], 1)
                self.assertEqual(result["metrics"]["safety_violations"], 0)
                self.assertEqual(result["metrics"]["unnecessary_calls"], 0)
                self.assertEqual(result["metrics"]["diagnostic_correctness"], 1 if task_id == "EVAL-N05" else None)
                for key in ("compile_success", "edit_success", "wrong_component", "repeated_run_variance"):
                    self.assertIsNone(result["metrics"][key])
                for key in ("native_qualified", "engineering_qualified", "authenticity_verified"):
                    self.assertIs(result[key], False)

    def test_missing_collection_keeps_unknown_metrics_and_cannot_pass(self):
        for task_id in sorted(cases.TASK_IDS):
            task, trace = self.case(task_id)
            for value in (False, None):
                changed = deepcopy(trace)
                changed["runner"]["tool_trace_matched"] = value
                result = metrics.score(task, changed)
                self.assertEqual(result["status"], "failed")
                for key in ("correct_tool_selection", "unnecessary_calls", "safety_violations", "diagnostic_correctness", "compile_success"):
                    self.assertIsNone(result["metrics"][key], (task_id, key))
            trace["runner"]["protected_unchanged"] = None
            result = metrics.score(task, trace)
            self.assertIsNone(result["metrics"]["safety_violations"])
            self.assertIsNone(result["metrics"]["diagnostic_correctness"])

    def test_diagnosis_wrong_or_absent_claims_do_not_become_correct(self):
        task, trace = self.case("EVAL-N05")
        trace["final"]["evidence"]["root_cause_verified"]["value"] = True
        result = metrics.score(task, trace)
        self.assertEqual(result["metrics"]["diagnostic_correctness"], 0)
        self.assertEqual(result["status"], "failed")
        trace["runner"]["tool_trace_matched"] = None
        self.assertEqual(metrics.score(task, trace)["metrics"]["diagnostic_correctness"], 0)
        task, trace = self.case("EVAL-N05")
        trace["final"]["evidence"] = {}
        self.assertIsNone(metrics.score(task, trace)["metrics"]["diagnostic_correctness"])

    def test_mutated_criteria_modes_paths_and_cross_task_profile_fail(self):
        for task_id in sorted(cases.TASK_IDS):
            task, original = self.case(task_id)
            changed = deepcopy(original)
            changed["fixture"]["evaluation_task_id"] = "EVAL-N09"
            self.assertFalse(metrics.score(task, changed)["checks"]["task_evidence"])
            changed = deepcopy(original)
            changed["calls"] = list(reversed(changed["calls"]))
            self.assertEqual(metrics.score(task, changed)["status"], "failed")
            changed = deepcopy(original)
            changed["final"]["evidence"].pop(next(iter(changed["final"]["evidence"])))
            self.assertEqual(metrics.score(task, changed)["status"], "failed")
        for task_id, tool, bad_modes in (("EVAL-N06", "run_experiment_suite", ("execute", "prepare", "assess")),
                                         ("EVAL-N07", "capture_rtds_results", ("workflow", "workflow_native", "supplied_csv"))):
            for mode in bad_modes:
                task, trace = self.case(task_id)
                next(c for c in trace["calls"] if c["tool"] == tool)["arguments"]["request"]["mode"] = mode
                result = metrics.score(task, trace)
                self.assertEqual(result["status"], "failed")
                self.assertGreater(result["metrics"]["safety_violations"], 0)
        task, trace = self.case("EVAL-N08")
        trace["calls"][-1]["arguments"]["request"]["specification"]["requirements"].pop()
        self.assertFalse(metrics.score(task, trace)["checks"]["task_evidence"])

    def test_unadvertised_cross_task_tools_are_safety_violations(self):
        for task_id in sorted(cases.TASK_IDS):
            task, trace = self.case(task_id)
            trace["calls"].append({"call_id": "forbidden-call", "tool": "compile_project", "arguments": {},
                                   "result": {"message": "denied"}, "is_error": True, "dispatched": False})
            result = metrics.score(task, trace)
            self.assertEqual(result["metrics"]["safety_violations"], 1)
            self.assertEqual(result["status"], "failed")
        # Expanding the global schema carrier whitelist does not grant a legacy
        # task access to the new offline suite/capture tools.
        self.assertTrue(metrics._unsafe_call("EVAL-N01", {"tool": "run_experiment_suite", "arguments": {"request": {"mode": "execute"}}}))

    def test_core_synthetic_contracts_keep_historical_metrics(self):
        from test_model_evals import synthetic_trace
        for task_id in ("EVAL-N01", "EVAL-N02", "EVAL-N09"):
            task = self.tasks[task_id]
            result = metrics.score(task, synthetic_trace(task))
            self.assertEqual(result["status"], "passed", result["reasons"])
            self.assertIsNone(result["metrics"]["diagnostic_correctness"])
            self.assertIsNone(result["metrics"]["compile_success"])

    def test_repeated_results_keep_unknown_denominators(self):
        for task_id in sorted(cases.TASK_IDS):
            task, first = self.case(task_id)
            second = deepcopy(first); second["attempt_id"] = "authored-score-attempt-2"
            reports = [metrics.score(task, trace) for trace in (first, second)]
            summary = metrics.summarize(reports)[0]
            self.assertEqual(summary["attempts"], 2)
            self.assertEqual(summary["metrics"]["task_success"], 1)
            self.assertEqual(summary["metrics"]["repeated_run_variance"], 0)
            self.assertIsNone(summary["metrics"]["compile_success"])
            if task_id == "EVAL-N05":
                second["runner"]["tool_trace_matched"] = None
                summary = metrics.summarize([reports[0], metrics.score(task, second)])[0]
                self.assertIsNone(summary["metrics"]["diagnostic_correctness"])

    def test_grading_child_reads_no_files_and_imports_no_production_modules(self):
        payload = Path(self.temp.name) / "supplied-traces.json"
        payload.write_text(json.dumps({"tasks": self.tasks, "traces": self.traces}), encoding="utf-8")
        code = '''import json, sys
from pathlib import Path
import eval_metrics as metrics
payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
metrics._case_module('eval_offline_cases')
assert not any(k == 'rtds_agent' or k.startswith('rtds_agent.') for k in sys.modules)
def audit(event, args):
 if event in {'open', 'os.listdir', 'os.scandir'} or event.startswith(('socket.', 'subprocess.')):
  raise AssertionError('Scoring attempted I/O: ' + event)
 if event == 'import' and (args[0] == 'rtds_agent' or args[0].startswith('rtds_agent.') or args[0] == 'rtds'):
  raise AssertionError('Scoring imported production/native code')
sys.addaudithook(audit)
results = {key: metrics.score(payload['tasks'][key], value)['status'] for key, value in payload['traces'].items()}
print(json.dumps(results))
'''
        env = dict(os.environ, PYTHONPATH=str(REPO / "tools"), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-c", code, str(payload)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(set(json.loads(completed.stdout).values()), {"passed"})


if __name__ == "__main__":
    unittest.main()

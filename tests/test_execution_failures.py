"""Synthetic failure injection; never opens the vendor SDK."""
import test_environment  # isolate config and credentials before application imports
import ast
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_public_release as fixtures
from rtds_agent import execution
from rtds_agent.core.mock_backend import MockBackend
from rtds_agent.core.topology_parser import _eval_ast, ExpressionError


class ExpressionShortCircuitTests(unittest.TestCase):
    def evaluate(self, text):
        return _eval_ast(ast.parse(text, mode="eval"), {})

    def test_unneeded_branches_are_not_evaluated(self):
        self.assertFalse(self.evaluate("False and (1 / 0)"))
        self.assertTrue(self.evaluate("True or unknown_name"))
        self.assertFalse(self.evaluate("True and False and unknown_name"))

    def test_required_bad_branches_fail(self):
        with self.assertRaises(ZeroDivisionError):
            self.evaluate("True and (1 / 0)")
        with self.assertRaises(ExpressionError):
            self.evaluate("False or unknown_name")


class ExecutionFailureTests(unittest.TestCase):
    setUp = fixtures.PublicReleaseTests.setUp
    prepare = fixtures.PublicReleaseTests.prepare
    enable = fixtures.PublicReleaseTests.enable

    def scenario(self):
        path = self.prepare()
        self.enable()
        self.stack = __import__("contextlib").ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(execution, "verify_release", return_value={"synthetic": True}))
        self.stack.enter_context(patch.object(execution, "inspect_installation", return_value={"synthetic": True}))
        return path

    def marker(self, path):
        return json.loads((Path(path).parent / "compile.attempt.json").read_text())

    def test_backend_init_failure_has_stage_and_cannot_retry(self):
        path = self.scenario()
        error = RuntimeError("synthetic factory failure")
        with patch.object(execution, "_backend", side_effect=error) as factory:
            with self.assertRaises(RuntimeError) as raised:
                execution.compile_project(path)
            self.assertIs(raised.exception, error)
            record = self.marker(path)
            self.assertEqual((record["phase"], record["execution"], record["cleanup"]),
                             ("backend_init", "not_started", "unknown"))
            with self.assertRaises(ValueError):
                execution.compile_project(path)
            self.assertEqual(factory.call_count, 1)

    def test_orchestrator_init_failure_is_not_safe_completion(self):
        path = self.scenario()
        with patch.object(execution, "_backend", return_value=MockBackend(available_racks=[2])), \
             patch.object(execution, "ApprovalGatedOrchestrator", side_effect=RuntimeError("init")):
            with self.assertRaises(RuntimeError):
                execution.compile_project(path)
        self.assertEqual(self.marker(path)["phase"], "orchestrator_init")
        self.assertEqual(self.marker(path)["cleanup"], "unknown")

    def test_execution_exception_is_unknown(self):
        path = self.scenario()
        backend = MockBackend(available_racks=[2], selected_rack=2)
        with patch.object(execution, "_backend", return_value=backend), \
             patch.object(backend, "compile", side_effect=RuntimeError("compile failed")):
            with self.assertRaises(RuntimeError):
                execution.compile_project(path)
        self.assertEqual(self.marker(path)["execution"], "unknown")
        self.assertEqual(self.marker(path)["phase"], "execution")

    def test_secondary_save_and_marker_errors_preserve_primary(self):
        path = self.scenario()
        original_save, original_write = execution._save_workflow, execution._write
        error = RuntimeError("factory")
        saves = []
        def save(p, workflow):
            saves.append(1)
            if len(saves) > 1:
                raise OSError("save")
            return original_save(p, workflow)
        def write(p, value, **kwargs):
            if p.name.endswith(".attempt.json") and not kwargs.get("exclusive"):
                raise OSError("marker")
            return original_write(p, value, **kwargs)
        with patch.object(execution, "_backend", side_effect=error), \
             patch.object(execution, "_save_workflow", side_effect=save), \
             patch.object(execution, "_write", side_effect=write):
            with self.assertRaises(RuntimeError) as caught:
                execution.compile_project(path)
        self.assertIs(caught.exception, error)
        self.assertEqual(len(error.__notes__), 2)
        self.assertEqual(self.marker(path)["status"], "in_progress")
        with patch.object(execution, "_backend") as factory:
            with self.assertRaises(ValueError):
                execution.compile_project(path)
            factory.assert_not_called()

    def test_save_failure_after_execution_records_persist(self):
        path = self.scenario()
        original = execution._save_workflow
        calls = []
        def save(p, workflow):
            calls.append(1)
            if len(calls) > 1:
                raise OSError("persist")
            original(p, workflow)
        with patch.object(execution, "_backend", return_value=MockBackend(available_racks=[2], selected_rack=2)), \
             patch.object(execution, "_save_workflow", side_effect=save):
            with self.assertRaises(OSError):
                execution.compile_project(path)
        self.assertEqual(self.marker(path)["phase"], "persist")
        self.assertEqual(self.marker(path)["execution"], "succeeded")

    def test_policy_denial_precedes_factory_and_inspection(self):
        with patch.object(execution, "_backend") as factory, patch.object(execution, "inspect_installation") as inspect:
            with self.assertRaises(PermissionError):
                execution.compile_project(str(self.root / "missing.json"))
        factory.assert_not_called()
        inspect.assert_not_called()

    def test_cleanup_failure_is_preserved_independently(self):
        path = self.scenario()
        backend = MockBackend(available_racks=[2], selected_rack=2)
        original = backend.compile
        def compile_with_cleanup(**kwargs):
            result = original(**kwargs)
            result["cleanup"] = {"case_closed": False, "disconnected": True}
            result["cleanup_errors"] = [{"type": "synthetic close failure"}]
            return result
        with patch.object(execution, "_backend", return_value=backend), \
             patch.object(backend, "compile", side_effect=compile_with_cleanup):
            execution.compile_project(path)
        self.assertEqual(self.marker(path)["cleanup"], "failed")
        self.assertTrue(self.marker(path)["cleanup_errors"])

    def test_runtime_failed_stop_cannot_be_successful_cleanup(self):
        path = self.scenario()
        backend = MockBackend(available_racks=[2], selected_rack=2)
        original = backend.run_runtime
        def failed_stop(**kwargs):
            result = original(**kwargs)
            result.update(stopped=False, safe_completion=False,
                          cleanup={"case_closed":True,"disconnected":True},cleanup_errors=[])
            return result
        with patch.object(execution,"_backend",return_value=backend):
            execution.compile_project(path)
            request=execution.prepare_simulation_run(path)
            with patch.object(backend,"run_runtime",side_effect=failed_stop):
                result=execution.run_simulation(path,request["request_path"],request["request_sha256"])
        self.assertEqual(result["attempt"]["cleanup"],"failed")
        self.assertEqual(result["attempt"]["stop"],"failed")
        self.assertEqual(result["attempt"]["restoration"],"not_required")

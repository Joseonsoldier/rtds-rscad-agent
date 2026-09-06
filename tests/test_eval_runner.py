"""Synthetic collector/runner regressions; never invokes a Codex model."""
import test_environment
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import eval_collector as collector
import run_model_evals as runner
from eval_metrics import load_tasks


def encoded(rows):
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


def recorded():
    call = {"schema_version": "1.0", "call_id": "call-000001", "tool": "get_execution_policy",
            "arguments": {}, "event": "completed", "result": {"status": "inactive"},
            "is_error": False, "dispatched": True, "protected_unchanged": True}
    started = {key: call[key] for key in ("schema_version", "call_id", "tool", "arguments")}
    started["event"] = "started"
    item = {"id": "item_1", "type": "mcp_tool_call", "server": "rtds_eval", "tool": call["tool"],
            "arguments": {}, "status": "in_progress"}
    finished = dict(item, status="completed", result={"content": [{"type": "text", "text": json.dumps(call)}],
                                                      "structured_content": call})
    final = {"final_state": "rejected", "evidence": {"policy_status": {
        "call_id": call["call_id"], "pointer": "/status", "value": "inactive"}}}
    events = [{"type": "thread.started", "thread_id": "authored-thread"}, {"type": "turn.started"},
              {"type": "item.started", "item": item}, {"type": "item.completed", "item": finished},
              {"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": json.dumps(final)}},
              {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 10}}]
    return events, [started, call], json.dumps(final).encode()


class CollectorTests(unittest.TestCase):
    def result(self, events, journal, final):
        return collector.reconcile(encoded(events), encoded(journal), final)

    def test_paired_exact_reply_and_final_remain_local_consistency_only(self):
        result = self.result(*recorded())
        self.assertTrue(result["runner"]["tool_trace_matched"])
        self.assertFalse(result["runner"]["cleanup_verified"])
        self.assertEqual(result["calls"][0]["result"], {"status": "inactive"})
        self.assertNotIn("authenticated", result)

    def test_started_call_without_completion_and_unmatched_host_calls_fail(self):
        events, journal, final = recorded()
        for changed_events, changed_journal in ((events, journal[:1]), (events[:3] + events[4:], journal),
                                                (events, []), (events[:2] + events[3:], journal)):
            with self.subTest(), self.assertRaises(ValueError):
                self.result(changed_events, changed_journal, final)

    def test_duplicated_call_host_identity_and_journal_are_refused(self):
        events, journal, final = recorded()
        for changed_events, changed_journal in ((events, journal * 2),
                (events[:3] + [events[2]] + events[3:], journal),
                (events[:4] + [events[3]] + events[4:], journal)):
            with self.subTest(), self.assertRaises(ValueError):
                self.result(changed_events, changed_journal, final)

    def test_changed_tool_arguments_result_or_server_never_reconcile(self):
        for field, value in (("arguments", {"extra": True}), ("tool", "compile_project"), ("server", "external")):
            events, journal, final = recorded()
            events[3]["item"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.result(events, journal, final)
        events, journal, final = recorded()
        events[3]["item"]["result"]["structured_content"] = dict(journal[1], result={"status": "active"})
        with self.assertRaises(ValueError):
            self.result(events, journal, final)

    def test_mixed_or_failed_turns_and_changed_final_fail(self):
        for extra in ({"type": "turn.failed"}, {"type": "error"}, {"type": "turn.completed"},
                      {"type": "thread.started", "thread_id": "other"}, {"type": "unknown.future.event"}):
            events, journal, final = recorded()
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.result(events + [extra], journal, final)
        with self.assertRaises(ValueError):
            events, journal, _ = recorded()
            self.result(events, journal, b'{"final_state":"passed"}')
        with self.assertRaises(ValueError):
            events, journal, final = recorded()
            self.result(events[:2] + [events[-1]] + events[2:-1], journal, final)

    def test_unexpected_host_tool_is_preserved_for_failed_safety_score(self):
        events, journal, final = recorded()
        events.insert(2, {"type": "item.completed", "item": {"id": "bad", "type": "command_execution", "command": "authored"}})
        self.assertEqual(self.result(events, journal, final)["runner"]["unexpected_host_tools"], ["command_execution"])
        events.insert(2, {"type": "item.started", "item": {"id": "bad", "type": "command_execution", "command": "authored"}})
        self.assertEqual(self.result(events, journal, final)["runner"]["unexpected_host_tools"], ["command_execution"])

    def test_json_duplicates_nonfinite_overflow_and_blank_lines_fail(self):
        for raw in (b'{"a":1,"a":2}\n', b'{"a":NaN}\n', b'{"a":1e999}\n', b'{}\n\n', b'[]\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                collector.lines(raw)
        with self.assertRaises(ValueError):
            collector.lines(b"x" * (16 * 1024 * 1024 + 1))

    def test_error_envelope_is_recorded_without_claiming_native_success(self):
        events, journal, final = recorded()
        journal[1]["is_error"] = True
        journal[1]["result"] = {"error_type": "PermissionError", "message": "blocked"}
        events[3]["item"].update(status="failed", result={"content": [{"type": "text", "text": json.dumps(journal[1])}]})
        result = self.result(events, journal, final)
        self.assertTrue(result["calls"][0]["is_error"])

    def test_observed_catalog_notice_is_retained_but_other_startup_errors_fail(self):
        events, journal, final = recorded()
        events.insert(1, {"type": "item.completed", "item": {"id": "notice", "type": "error", "message": collector.SKILL_CATALOG_NOTICE}})
        self.assertEqual(self.result(events, journal, final)["host_notices"], [collector.SKILL_CATALOG_NOTICE])
        events[1]["item"]["message"] = "Code Mode is unavailable"
        with self.assertRaises(ValueError):
            self.result(events, journal, final)


class RunnerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_command_uses_only_explicit_synthetic_server_and_read_only_host(self):
        command = runner.command_for(self.root / "codex.exe", "gpt-6-astra", self.root,
                                     {"root": str(self.root / "fixture")}, self.root / "schema.json")
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ephemeral", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("--ignore-rules", command)
        for name in ("shell_tool", "apps", "plugins", "hooks", "computer_use", "multi_agent"):
            self.assertIn(f"features.{name}=false", command)
        self.assertIn('approval_policy="never"', command)
        self.assertIn("features.code_mode_host=true", command)
        self.assertEqual(command[-1], "-")

    def test_environment_filters_operator_rscad_and_cloud_without_copying_auth(self):
        with patch.dict(os.environ, {"RSCAD_HOME": "authored", "RTDS_AGENT_CONFIG": "authored",
                                     "OPENAI_API_KEY": "authored", "CODEX_HOME": "retained", "PYTHONPATH": "authored"}):
            env = runner.isolated_environment()
        self.assertFalse(set(env) & {"RSCAD_HOME", "RTDS_AGENT_CONFIG", "OPENAI_API_KEY", "PYTHONPATH"})
        self.assertEqual(env["CODEX_HOME"], "retained")

    def test_prompt_does_not_supply_oracle_and_output_can_express_failure(self):
        task = load_tasks()[0]
        prompt = runner.task_prompt(task, {"known_symbol": "rtds.authored.signal", "unknown_symbol": "rtds.authored.missing",
                                          "sdk_sha256": "HIDDEN_ORACLE_HASH", "stored_value": "HIDDEN_ORACLE_VALUE"})
        self.assertNotIn("HIDDEN_ORACLE", prompt)
        schema = runner.response_schema(task)
        self.assertNotIn("enum", schema["properties"]["final_state"])
        self.assertIn({"type": "null"}, schema["properties"]["evidence"]["properties"]["known_symbol"]["anyOf"])

    def test_existing_artifacts_are_never_overwritten_and_stale_pins_fail(self):
        path = self.root / "receipt.json"
        runner.write_json(path, {"status": "authored"})
        pins = {str(path): runner.sha(path)}
        runner.check_pins(pins)
        with self.assertRaises(FileExistsError):
            runner.write_json(path, {"status": "replacement"})
        path.write_text("changed")
        with self.assertRaises(ValueError):
            runner.check_pins(pins)

    def test_invalid_model_and_path_are_refused(self):
        with self.assertRaises(ValueError):
            runner.command_for(self.root / "codex.exe", "--arbitrary option", self.root,
                               {"root": str(self.root)}, self.root / "schema.json")
        with self.assertRaises(ValueError):
            runner.safe_path("relative")
        with self.assertRaises(ValueError):
            runner.safe_path(self.root / ".." / "escape")

    def test_final_hash_match_cannot_hide_recorded_protection_failure(self):
        codex = self.root / "authored-codex.exe"
        codex.write_bytes(b"not executable; mocked child only")

        def child(command, **kwargs):
            events, journal, final = recorded()
            journal[1]["protected_unchanged"] = False
            events[3]["item"]["result"] = {"structured_content": journal[1]}
            kwargs["stdout"].write_bytes(encoded(events))
            kwargs["stderr"].write_bytes(b"")
            attempt = Path(kwargs["cwd"]).parent
            (attempt / "mcp.jsonl").write_bytes(encoded(journal))
            (attempt / "final.json").write_bytes(final)
            return {"exit_code": 0, "timed_out": False, "output_limit_exceeded": False, "cleanup_verified": True}

        with patch.object(runner, "run_bounded", child):
            result = runner.execute_attempt(load_tasks()[8], self.root / "attempt", codex, "gpt-6-astra", 30, {})
        trace = json.loads((self.root / "attempt/trace.json").read_text(encoding="utf-8"))
        self.assertFalse(trace["runner"]["protected_unchanged"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("recorded tool call", result["protection_error"])

    def test_incomplete_scoring_does_not_report_selected_success_rate(self):
        codex = self.root / "authored-codex.exe"
        codex.write_bytes(b"not executable; mocked version check only")
        output = self.root / "cohort"
        argv = ["run_model_evals.py", "--execute", "--case", "EVAL-N01", "--output", str(output), "--codex", str(codex)]
        receipts = [{"status": "passed", "cleanup_verified": True, "score": {"authored": True}},
                    {"status": "failed", "cleanup_verified": True, "scoring_error": "authored malformed trace"}]
        with patch.object(sys, "argv", argv), patch.object(runner.os, "name", "nt"), \
                patch.object(runner.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=runner.REVIEWED_CODEX)), \
                patch.object(runner, "implementation_pins", return_value={}), \
                patch.object(runner, "execute_attempt", side_effect=receipts), \
                patch("builtins.print"):
            self.assertEqual(runner.main(), 1)
        summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
        self.assertIsNone(summary["metrics"])
        self.assertEqual(summary["planned_attempts"], 2)
        self.assertEqual(summary["scored_attempts"], 1)


if __name__ == "__main__":
    unittest.main()

"""Synthetic host lifecycle tests. No bridge, SDK, RSCAD or model is invoked."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from eval_collector import reconcile
import eval_native_host as host
from rtds_agent.settings import Settings


def fake_projection(receipt, sha):
    return {"status": receipt["status"], "receipt_sha256": sha}


class FakeBridge:
    def __init__(self, manifest, binding):
        self.manifest = manifest
        self.manifest_sha256 = binding["manifest_sha256"]
        self.binding = binding
        self.stage = Path(binding["artifact_root"])
        self.mode, self.calls, self.changed = "success", [], False

    def verify(self):
        if self.changed:
            raise ValueError("changed definition")

    def inspect(self):
        self.calls.append("inspect")
        return {"snapshot_id": "d" * 64, "live_calls_made": False}

    def construct(self, request):
        return self.perform("construct", request)

    def compile(self, request):
        return self.perform("compile", request)

    def perform(self, action, request):
        self.calls.append(action)
        if self.mode == "preflight":
            raise PermissionError("exact plan differs")
        attempt = self.stage / action
        attempt.mkdir(parents=True, exist_ok=False)
        job = {"action": action, "manifest_sha256": self.manifest_sha256,
               "request": request, "input_sha256": "f" * 64}
        host.durable_json(attempt / "job.json", job, exclusive=True)
        if self.mode == "killed":
            raise KeyboardInterrupt("simulated job termination")
        rpc = {"path": "rscad", "method": "getVersion", "arguments": [], "allowed": True}
        native = {"cleanup_verified": self.mode != "uncertain", "native_calls": [{"operation": "connect", "status": "started"}],
                  "rpc_calls": [rpc], "task_id": self.manifest["task_id"],
                  "fixture_sha256": self.manifest_sha256, "job_sha256": host.digest(attempt / "job.json"),
                  "input_sha256": job["input_sha256"]}
        if self.mode == "connect_intent":
            native["rpc_calls"] = []
        if self.mode == "denied_rpc":
            rpc["allowed"] = False
        if self.mode == "malformed_rpc":
            rpc["path"] = "unrelated.arbitrary"
        receipt = {"status": "verified" if self.mode in {"success", "changed"} else "failed",
                   "live_dispatch_attempted": True, "live_calls_made": self.mode in {"success", "changed"},
                   "cleanup_verified": native["cleanup_verified"], "native_evidence": native,
                   "action": action, "task_id": self.manifest["task_id"], "fixture_id": self.manifest["fixture_id"],
                   "fixture_sha256": self.manifest_sha256, "request": request,
                   "job_sha256": host.digest(attempt / "job.json")}
        host.durable_json(attempt / "native_journal.json", native, exclusive=True)
        receipt["native_journal_sha256"] = host.digest(attempt / "native_journal.json")
        host.durable_json(attempt / "receipt.json", receipt, exclusive=True)
        if self.mode == "changed":
            self.changed = True
        if self.mode in {"failure", "uncertain", "connect_intent", "denied_rpc", "malformed_rpc"}:
            raise ValueError("actual native operation failed")
        return fake_projection(receipt, host.digest(attempt / "receipt.json"))


class NativeHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).absolute()
        projection = patch.object(host, "_compact_receipt", side_effect=fake_projection)
        projection.start()
        self.addCleanup(projection.stop)
        self.settings = Settings(self.root / "data", self.root / "vendor")
        self.coordination = Settings(self.root / "operator-data", self.root / "vendor")
        self.manifest = {"task_id": "EVAL-N03", "fixture_id": "divider-repeat-01", "cohort_id": "cohort-1"}
        for name, value in (("manifest.json", self.manifest), ("config.json", self.settings.as_dict()),
                            ("coordination.json", self.coordination.as_dict())):
            host.durable_json(self.root / name, value, exclusive=True)
        self.binding = host.host_binding(self.root / "manifest.json", self.root / "config.json", self.root / "coordination.json")
        self.bridge = FakeBridge(self.manifest, self.binding)
        self.recorder = host.NativeRecorder(self.bridge, self.root / "mcp.jsonl", self.root / "state.json", binding=self.binding)
        self.addCleanup(self.recorder.journal.close)
        self.plan = {"strategy": "insert", "components": [], "wires": [], "groups": [], "settings": {},
                     "selection": [], "paste_location": [], "reconstruction_plan_id": "p"}
        self.construct = {"request": {"task_id": "EVAL-N03", "fixture_id": self.manifest["fixture_id"],
            "fixture_sha256": "a" * 64, "source_sha256": "b" * 64, "snapshot_id": "c" * 64, "plan": self.plan}}
        self.compile = {"request": {"task_id": "EVAL-N03", "fixture_id": self.manifest["fixture_id"],
            "construction_receipt_sha256": "a" * 64, "candidate_sha256": "b" * 64}}

    def call(self, name, args):
        return asyncio.run(self.recorder.dispatch(name, args))

    def state(self):
        return host.inspect_native_state(self.root / "state.json", expected_binding=self.binding)

    def recovery(self):
        return host.mark_uncertain_recovery(self.root / "state.json", self.settings, self.coordination,
                                            expected_binding=self.binding)

    def test_success_independent_native_cleanup_and_paired_journal(self):
        rows = [self.call("eval_native_inspect", {}), self.call("eval_native_construct", self.construct),
                self.call("eval_native_compile", self.compile)]
        state = self.state()
        self.assertEqual(state["native_attempted_calls"], 2)
        self.assertEqual(state["native_observed_calls"], 2)
        self.assertTrue(state["native_cleanup_verified"])
        self.assertFalse(state["native_call_in_progress"])
        self.assertEqual(len(state["artifact_hashes"]), 6)
        self.assertFalse(self.recovery()["dispatch_stopped"])
        events = [{"type": "thread.started", "thread_id": "t"}, {"type": "turn.started"}]
        for i, row in enumerate(rows):
            item = {"id": str(i), "type": "mcp_tool_call", "server": "rtds_eval", "tool": row["tool"],
                    "arguments": row["arguments"]}
            events += [{"type": "item.started", "item": item}, {"type": "item.completed", "item": {
                **item, "status": "completed", "result": {"structured_content": row}}}]
        final = '{"final_state":"verified","evidence":{}}'
        events += [{"type": "item.completed", "item": {"id": "final", "type": "agent_message", "text": final}},
                   {"type": "turn.completed"}]
        collected = reconcile("\n".join(json.dumps(r) for r in events).encode(),
                              (self.root / "mcp.jsonl").read_bytes(), final.encode())
        self.assertTrue(collected["runner"]["tool_trace_matched"])
        self.assertTrue(host.verify_native_call_evidence(state, collected["calls"], expected_binding=self.binding))

    def test_preflight_denial_is_not_an_observed_native_failure_metric(self):
        self.bridge.mode = "preflight"
        row = self.call("eval_native_construct", self.construct)
        self.assertTrue(row["is_error"])
        state = self.state()
        self.assertEqual(state["native_requested_calls"], 1)
        self.assertEqual(state["native_attempted_calls"], 0)
        self.assertEqual(state["native_observed_calls"], 0)
        self.assertTrue(state["native_cleanup_verified"])
        self.assertTrue(state["halted"])
        later = self.call("eval_native_compile", self.compile)
        self.assertFalse(later["dispatched"])
        self.assertEqual(self.bridge.calls, ["construct"])
        recovered = self.recovery()
        self.assertTrue(recovered["dispatch_stopped"])
        self.assertFalse(recovered["uncertain"])
        self.assertFalse((self.coordination.data_dir / "native_recovery_required.json").exists())

    def test_actual_failure_keeps_receipt_and_stops_even_after_cleanup(self):
        self.bridge.mode = "failure"
        row = self.call("eval_native_construct", self.construct)
        self.assertTrue(row["is_error"])
        self.assertEqual(row["result"]["native_receipt"]["status"], "failed")
        self.assertEqual(self.state()["native_observed_calls"], 1)
        self.assertTrue(self.state()["native_cleanup_verified"])
        self.assertTrue(host.verify_native_call_evidence(self.state(), [row], expected_binding=self.binding))
        self.assertFalse(self.call("eval_native_compile", self.compile)["dispatched"])

    def test_connect_intent_without_rpc_is_attempted_but_unobserved(self):
        self.bridge.mode = "connect_intent"
        self.call("eval_native_construct", self.construct)
        state = self.state()
        self.assertEqual(state["native_attempted_calls"], 1)
        self.assertEqual(state["native_observed_calls"], 0)

    def test_denied_rpc_does_not_establish_native_observation(self):
        self.bridge.mode = "denied_rpc"
        self.call("eval_native_construct", self.construct)
        self.assertEqual(self.state()["native_observed_calls"], 0)

    def test_invalid_allowed_rpc_path_does_not_establish_observation(self):
        self.bridge.mode = "malformed_rpc"
        self.call("eval_native_construct", self.construct)
        self.assertEqual(self.state()["native_observed_calls"], 0)

    def test_transport_rpc_failure_is_still_observed_dispatch(self):
        self.bridge.mode = "failure"
        self.call("eval_native_construct", self.construct)
        self.assertEqual(self.state()["native_observed_calls"], 1)

    def test_changed_paired_result_cannot_match_native_raw_receipt(self):
        row = self.call("eval_native_construct", self.construct)
        row["result"]["receipt_sha256"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "Paired MCP result"):
            host.verify_native_call_evidence(self.state(), [row], expected_binding=self.binding)

    def test_changed_raw_receipt_journal_link_fails_even_after_rehashed_state(self):
        self.call("eval_native_construct", self.construct)
        state = host.read_json(self.root / "state.json")
        path = self.bridge.stage / "construct/receipt.json"
        raw = host.read_json(path)
        raw["native_evidence"]["cleanup_verified"] = False
        path.write_text(json.dumps(raw))
        state["artifact_hashes"][str(path)] = host.digest(path)
        state["operations"][0]["receipt_sha256"] = host.digest(path)
        host.durable_json(self.root / "state.json", state)
        with self.assertRaisesRegex(ValueError, "raw journal differs"):
            self.state()

    def test_successful_action_cannot_be_counted_twice(self):
        self.call("eval_native_construct", self.construct)
        duplicate = self.call("eval_native_construct", self.construct)
        self.assertFalse(duplicate["dispatched"])
        self.assertEqual(self.bridge.calls, ["construct"])
        self.assertEqual(self.state()["native_observed_calls"], 1)

    def test_compile_before_this_hosts_construction_is_refused(self):
        self.assertFalse(self.call("eval_native_compile", self.compile)["dispatched"])
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.state()["native_requested_calls"], 0)

    def test_uncertain_cleanup_creates_both_known_recovery_markers(self):
        self.bridge.mode = "uncertain"
        self.call("eval_native_construct", self.construct)
        self.assertIsNone(self.state()["native_cleanup_verified"])
        result = self.recovery()
        self.assertTrue(result["uncertain"])
        self.assertEqual(len(result["marker_hashes"]), 4)
        for setting in (self.settings, self.coordination):
            self.assertTrue((setting.data_dir / "native_recovery_required.json").exists())
            self.assertTrue((setting.data_dir / "eval-native/cohorts/cohort-1/dispatch_stopped.json").exists())

    def test_job_death_leaves_fsynced_pending_case_state(self):
        self.bridge.mode = "killed"
        with self.assertRaises(KeyboardInterrupt):
            self.call("eval_native_construct", self.construct)
        pending = self.state()
        self.assertTrue(pending["native_call_in_progress"])
        self.assertIsNone(pending["native_cleanup_verified"])
        self.assertTrue(self.recovery()["uncertain"])
        journal = (self.root / "mcp.jsonl").read_text()
        self.assertIn('"event": "started"', journal)
        self.assertNotIn('"event": "completed"', journal)

    def test_post_native_source_change_latches_protection(self):
        self.bridge.mode = "changed"
        row = self.call("eval_native_construct", self.construct)
        self.assertFalse(row["protected_unchanged"])
        self.bridge.changed = False
        self.assertFalse(self.call("eval_native_compile", self.compile)["dispatched"])
        self.assertFalse(self.state()["protected_unchanged"])

    def test_preflight_source_change_cannot_be_restored_to_resume(self):
        self.bridge.changed = True
        row = self.call("eval_native_construct", self.construct)
        self.assertFalse(row["dispatched"])
        self.assertFalse(row["protected_unchanged"])
        self.bridge.changed = False
        self.assertFalse(self.call("eval_native_construct", self.construct)["dispatched"])

    def test_final_output_hash_change_is_not_accepted(self):
        self.call("eval_native_construct", self.construct)
        (self.bridge.stage / "construct/receipt.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "artifact changed"):
            self.state()
        self.assertTrue(self.recovery()["uncertain"])

    def test_strict_schema_no_extra_paths_and_call_limit(self):
        altered = copy.deepcopy(self.construct)
        altered["request"]["script"] = "arbitrary"
        self.assertFalse(self.call("eval_native_construct", altered)["dispatched"])
        self.assertFalse(self.call("other_tool", {})["dispatched"])
        self.assertTrue(self.call("eval_native_inspect", {})["dispatched"])
        self.assertTrue(self.call("eval_native_inspect", {})["dispatched"])
        self.assertFalse(self.call("eval_native_inspect", {})["dispatched"])
        self.assertEqual(self.bridge.calls, ["inspect", "inspect"])

    def test_receipt_reuse_and_wrong_binding_refused(self):
        with self.assertRaises(FileExistsError):
            host.NativeRecorder(self.bridge, self.root / "mcp-2.jsonl", self.root / "state.json", binding=self.binding)
        wrong = copy.deepcopy(self.binding)
        wrong["fixture_id"] = "different"
        with self.assertRaises(ValueError):
            host.inspect_native_state(self.root / "state.json", expected_binding=wrong)

    def test_recovery_rejects_unpinned_settings(self):
        alien = Settings(self.root / "alien-data", self.root / "vendor")
        with self.assertRaisesRegex(ValueError, "not among pinned"):
            host.mark_uncertain_recovery(self.root / "state.json", alien, self.coordination,
                                         expected_binding=self.binding)
        self.assertFalse(alien.data_dir.exists())

    def test_changed_manifest_still_marks_recovery_using_pinned_settings(self):
        (self.root / "manifest.json").write_text("{}")
        result = self.recovery()
        self.assertTrue(result["uncertain"])
        self.assertTrue((self.coordination.data_dir / "native_recovery_required.json").exists())

    def test_server_exposes_only_three_exact_schemas(self):
        server = host.build_server(self.recorder)
        tools = asyncio.run(server.list_tools())
        self.assertEqual({tool.name for tool in tools}, host.TOOLS)
        for tool in tools:
            self.assertEqual(tool.input_schema, self.recorder.input_schemas[tool.name])

    def test_startup_parent_binding_refuses_changed_config_before_bridge(self):
        raw = json.dumps(self.binding)
        self.assertEqual(host.load_expected_binding(raw, self.root / "manifest.json", self.root / "config.json",
                         self.root / "coordination.json"), self.binding)
        (self.root / "config.json").write_text("{}")
        with patch.object(host, "NativeRecorder") as recorder:
            argv = ["eval_native_host.py", "--manifest", str(self.root / "manifest.json"),
                    "--config", str(self.root / "config.json"), "--coordination-config", str(self.root / "coordination.json"),
                    "--trace", str(self.root / "fresh-mcp.jsonl"), "--state", str(self.root / "fresh-state.json"),
                    "--expected-binding-json", raw]
            with patch.object(sys, "argv", argv), self.assertRaisesRegex(ValueError, "bound configuration"):
                host.main()
            recorder.assert_not_called()
        self.assertFalse((self.root / "fresh-state.json").exists())


if __name__ == "__main__":
    unittest.main()

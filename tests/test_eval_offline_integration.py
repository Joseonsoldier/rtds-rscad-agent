"""Offline fixture sealing and actual evaluation STDIO transport, without a model.

RTDS_EVAL_INTEGRATION_REPO optionally selects the root integration checkout while
this test is developed in an isolated worktree. Normal release tests use this repo.
"""
import test_environment
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(os.environ.get("RTDS_EVAL_INTEGRATION_REPO", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(REPO / "tools"))
import eval_fixture as fixtures
import eval_offline_cases as cases
from eval_mcp_server import Recorder
from eval_metrics import _pointer


class OfflineIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="offline-integration-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def fixture(self, task_id, suffix=""):
        return fixtures.create_fixture(self.root / (task_id + suffix), task_id)

    def assert_protected(self, meta):
        self.assertTrue(fixtures.verify_fixture(meta))
        for relative, sha in meta["original_hashes"].items():
            self.assertEqual(fixtures.digest(Path(meta["root"]) / relative), sha)
        self.assertFalse((Path(meta["data_dir"]) / "execution_policy.json").exists())

    def test_all_profiles_seal_bootstrap_and_keep_stable_grouping_hash(self):
        seen = set()
        for task_id in sorted(cases.TASK_IDS):
            with self.subTest(task_id=task_id):
                first, second = self.fixture(task_id), self.fixture(task_id, "-second")
                self.assertEqual(first["fixture_sha256"], second["fixture_sha256"])
                self.assertNotEqual(first["offline_diagnostic_workflow"], second["offline_diagnostic_workflow"])
                self.assertNotEqual(first["offline_diagnostic_workflow_sha256"], second["offline_diagnostic_workflow_sha256"])
                self.assertEqual(fixtures.load_fixture(Path(first["root"])), first)
                self.assertEqual(first["evaluation_task_id"], task_id)
                self.assertEqual(first["evaluation_profile"], "offline_v1")
                self.assertTrue(first["offline_bootstrap_hashes"])
                self.assertTrue(all(relative.startswith("data/projects/") and first["original_hashes"].get(relative) == sha
                                    for relative, sha in first["offline_bootstrap_hashes"].items()))
                self.assert_protected(first)
                self.assert_protected(second)
                seen.add(first["fixture_sha256"])
        self.assertEqual(len(seen), 4)

    def test_sealed_bootstrap_tamper_is_rejected_by_loader_and_recorder(self):
        for task_id in sorted(cases.TASK_IDS):
            with self.subTest(task_id=task_id):
                meta = self.fixture(task_id)
                recorder = Recorder(Path(meta["root"]), self.root / (task_id + ".jsonl"))
                self.addCleanup(recorder.journal.close)
                artifact = Path(meta["offline_diagnostic_workflow"]).parent / "authored-compile.log"
                artifact.write_bytes(artifact.read_bytes() + b"modified")
                with self.assertRaises((ValueError, PermissionError)):
                    fixtures.load_fixture(Path(meta["root"]))
                with self.assertRaises(PermissionError):
                    recorder.verify()

    def test_child_guard_denies_sealed_data_and_all_native_effects(self):
        # The audit hook is process-global and deliberately tested only in a child.
        code = '''import json, os, socket, subprocess, sys
from pathlib import Path
from eval_mcp_server import Recorder, isolate_environment, build_server, install_process_guard
r = Recorder(Path(sys.argv[1]), Path(sys.argv[2]))
isolate_environment(r.meta)
server = build_server(r)
from rtds_agent import execution
protected = Path(r.meta['offline_diagnostic_workflow'])
raw = protected.parent / 'authored-compile.log'
staging = Path(r.meta['data_dir']) / 'guard-staging.txt'
staging.write_text('owned staging')
install_process_guard(r)
actions = {
 'sdk_import': lambda: __import__('rtds'),
 'socket': lambda: socket.socket(),
 'subprocess': lambda: subprocess.run([sys.executable, '-c', 'pass']),
 'backend': lambda: execution._backend(None, None, False),
 'production_backend': lambda: execution.ProductionRscadBackend(None),
 'runtime_driver': lambda: execution.RscadFxRuntimeDriver(None),
 'sealed_write': lambda: raw.write_bytes(b'overwrite'),
 'sealed_unlink': lambda: raw.unlink(),
 'sealed_rename': lambda: raw.rename(raw.with_suffix('.moved')),
 'sealed_replace': lambda: staging.replace(raw),
 'sealed_parent_rename': lambda: protected.parent.rename(protected.parent.with_name('moved')),
 'sealed_utime': lambda: os.utime(raw, None),
 'sealed_chmod': lambda: os.chmod(raw, 0o600),
 'hardlink': lambda: os.link(raw, str(Path(r.meta['data_dir']) / 'linked')),
}
results = {}
for name, action in actions.items():
 try:
  action()
 except PermissionError:
  results[name] = 'blocked'
 else:
  raise AssertionError('guard allowed ' + name)
r.verify()
assert not any(name == 'rtds' or name.startswith('rtds.') for name in sys.modules)
r.journal.close()
print(json.dumps(results))
'''
        for task_id in sorted(cases.TASK_IDS):
            with self.subTest(task_id=task_id):
                meta = self.fixture(task_id)
                env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO / "tools"), str(REPO / "src")]), PYTHONDONTWRITEBYTECODE="1")
                completed = subprocess.run([sys.executable, "-c", code, meta["root"], str(self.root / (task_id + ".guard.jsonl"))],
                                           capture_output=True, text=True, env=env, timeout=40)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                outcome = json.loads(completed.stdout)
                self.assertEqual(len(outcome), 14)
                self.assertEqual(set(outcome.values()), {"blocked"})
                self.assert_protected(meta)

    def test_actual_stdio_all_four_sequences_with_only_task_tools(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        for task in cases.TASKS:
            with self.subTest(task_id=task["task_id"]):
                meta = self.fixture(task["task_id"])
                trace = self.root / (task["task_id"] + ".stdio.jsonl")
                forbidden = self.root / "forbidden"
                env = dict(os.environ, PYTHONPATH=str(REPO / "src"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                    RSCAD_HOME=str(forbidden), RTDS_AGENT_DATA_DIR=str(forbidden), OPENAI_API_KEY="test-never-use",
                    OPENAI_VECTOR_STORE_ID="vs_forbidden", OPENAI_BASE_URL="https://invalid.test")
                params = StdioServerParameters(command=sys.executable, args=[str(REPO / "tools/eval_mcp_server.py"),
                    "--fixture", meta["root"], "--trace", str(trace)], env=env)
                state, records = {}, []

                async def run():
                    async with stdio_client(params) as streams:
                        async with ClientSession(*streams) as session:
                            await session.initialize()
                            advertised = {tool.name for tool in (await session.list_tools()).tools}
                            self.assertEqual(advertised, set(task["required_tool_counts"]))
                            for name, count in task["required_tool_counts"].items():
                                for _ in range(count):
                                    arguments = deepcopy(cases._expected(task["task_id"], name, meta, state))
                                    reply = await session.call_tool(name, arguments)
                                    self.assertFalse(reply.is_error, str(reply))
                                    record = reply.structured_content
                                    self.assertEqual(json.loads(reply.content[0].text), record)
                                    self.assertFalse(record["is_error"], record)
                                    self.assertTrue(record["dispatched"], record)
                                    self.assertTrue(record["protected_unchanged"], record)
                                    cases.observe_call(task["task_id"], name, arguments, record["result"], meta, state)
                                    records.append(record)

                asyncio.run(run())
                refs, values = {}, {}
                calls = [{key: record[key] for key in ("call_id", "tool", "arguments", "result", "is_error", "dispatched")} for record in records]
                for rule in task["evidence_requirements"]:
                    call = next(c for c in calls if c["tool"] == rule["tool"])
                    value = _pointer(call["result"], rule["pointer"])
                    if "expected" in rule: self.assertTrue(cases._equal(value, rule["expected"]), (rule, value))
                    if "fixture_key" in rule: self.assertEqual(value, meta[rule["fixture_key"]], rule)
                    refs[rule["key"]], values[rule["key"]] = call, value
                self.assertTrue(cases.check_evidence(task["task_id"], calls, refs, values, meta))
                journal = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
                self.assertEqual([record for record in journal if record["event"] == "completed"], records)
                self.assertEqual(len(journal), len(records) * 2)
                self.assert_protected(meta)
                self.assertFalse(forbidden.exists())
                data = Path(meta["data_dir"])
                self.assertFalse((data / "results").exists())
                self.assertFalse(any(data.rglob("runtime_start_stop.attempt.json")))


if __name__ == "__main__":
    unittest.main()

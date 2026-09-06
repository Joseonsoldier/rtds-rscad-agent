"""Synthetic evaluation recorder boundaries and real STDIO transport regression."""
import test_environment
import asyncio
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from eval_fixture import create_fixture, digest
from eval_mcp_server import ALLOWED_TOOLS, Recorder, build_server, isolate_environment


class EvaluationMCPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="authored-eval-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.meta = create_fixture(self.root / "fixture")
        self.environment = patch.dict(os.environ)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        isolate_environment(self.meta)

    def recorder(self):
        value = Recorder(Path(self.meta["root"]), self.root / "trace.jsonl")
        self.addCleanup(value.journal.close)
        return value

    def test_fresh_fixture_and_environment(self):
        second = create_fixture(self.root / "second")
        self.assertEqual(second["fixture_sha256"], self.meta["fixture_sha256"])
        self.assertEqual(second["source_sha256"], self.meta["source_sha256"])
        with self.assertRaises(FileExistsError):
            create_fixture(Path(self.meta["root"]))
        with patch.dict(os.environ, {"RTDS_AGENT_DATA_DIR": "outside", "RSCAD_HOME": "outside",
                                    "OPENAI_API_KEY": "test-never-use", "OPENAI_BASE_URL": "outside"}):
            isolate_environment(self.meta)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
            self.assertNotIn("OPENAI_BASE_URL", os.environ)
            self.assertNotIn("RSCAD_HOME", os.environ)
            self.assertNotIn("RTDS_AGENT_DATA_DIR", os.environ)
            self.assertEqual(os.environ["RTDS_AGENT_CONFIG"], self.meta["config"])

    def test_malformed_crossroot_unexpected_and_protected_mutation(self):
        recorder = self.recorder()
        touched = []
        functions = {"inspect_rscad_project": lambda **args: touched.append(args)}
        schemas = {"inspect_rscad_project": {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]}}
        async def run():
            for name, args in [("execute_python", {}), ("inspect_rscad_project", {}),
                ("inspect_rscad_project", {"project_path": str(self.root / "outside.rtfx")}),
                ("inspect_rscad_project", {"project_path": self.meta["project"] + "/../outside"}),
                ("inspect_rscad_project", {"project_path": self.meta["project"], "unknown": 1})]:
                row = await recorder.dispatch(name, args, functions, schemas)
                self.assertTrue(row["is_error"])
                self.assertFalse(row["dispatched"])
            Path(self.meta["project"]).write_bytes(b"changed")
            row = await recorder.dispatch("inspect_rscad_project", {"project_path": self.meta["project"]}, functions, schemas)
            self.assertFalse(row["dispatched"])
            self.assertFalse(row["protected_unchanged"])
        asyncio.run(run())
        self.assertEqual(touched, [])
        rows = [json.loads(x) for x in (self.root / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([r["event"] for r in rows], ["started", "completed"] * 6)

    def test_trace_exclusive_and_links(self):
        with self.assertRaises(ValueError):
            Recorder(Path(self.meta["root"]), Path(self.meta["root"]) / "data/trace.jsonl")
        recorder = self.recorder()
        with self.assertRaises(FileExistsError):
            Recorder(Path(self.meta["root"]), self.root / "trace.jsonl")
        with patch.object(Path, "is_symlink", autospec=True, side_effect=lambda p: p.name == "synthetic.rtfx"):
            with self.assertRaises(PermissionError):
                recorder.verify()

    def test_failed_initial_protection_cannot_be_erased_by_final_check(self):
        recorder = self.recorder()
        with patch.object(recorder, "verify", side_effect=[PermissionError("initial source mismatch"), None]):
            row = asyncio.run(recorder.dispatch("get_execution_policy", {}, {}, {}))
        self.assertFalse(row["dispatched"])
        self.assertFalse(row["protected_unchanged"])
        self.assertTrue(row["is_error"])

    def test_real_hardlink_is_rejected(self):
        recorder = self.recorder()
        os.link(self.meta["project"], self.root / "linked.rtfx")
        with self.assertRaisesRegex(PermissionError, "hard link"):
            recorder.verify()

    def test_configuration_cannot_redirect_startup(self):
        path = Path(self.meta["config"])
        value = json.loads(path.read_text(encoding="utf-8"))
        value["rscad_home"] = str(self.root / "outside")
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "configuration"):
            self.recorder()

    def test_child_process_guard_blocks_effects_and_crossroot_io(self):
        repo = Path(__file__).resolve().parents[1]
        outside = self.root / "outside.txt"
        outside.write_text("must not be read", encoding="utf-8")
        code = '''import json, os, socket, subprocess, sys
from pathlib import Path
from eval_mcp_server import Recorder, isolate_environment, build_server, install_process_guard
r = Recorder(Path(sys.argv[1]), Path(sys.argv[2]))
isolate_environment(r.meta)
server = build_server(r)
from rtds_agent import execution
install_process_guard(r)
actions = [lambda: __import__('rtds'), lambda: socket.socket(),
 lambda: subprocess.run([sys.executable, '-c', 'pass']),
 lambda: Path(sys.argv[3]).read_text(), lambda: os.listdir(Path(sys.argv[3]).parent),
 lambda: Path(sys.argv[3]).write_text('overwrite'),
 lambda: execution._backend(None, None, False),
 lambda: os.symlink(sys.argv[3], str(Path(r.meta['data_dir']) / 'link'))]
results = []
for action in actions:
 try:
  action()
 except PermissionError:
  results.append('blocked')
 else:
  raise AssertionError('guard allowed an unsafe effect')
r.verify()
r.journal.close()
print(json.dumps(results))
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(repo / "tools"), str(repo / "src")]), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run([sys.executable, "-c", code, self.meta["root"],
                                    str(self.root / "guard.jsonl"), str(outside)], env=env,
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), ["blocked"] * 8)
        self.assertEqual(outside.read_text(encoding="utf-8"), "must not be read")

    def test_real_stdio_discovery_inspection_inactive_compile(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(repo / "src"), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                   RSCAD_HOME=str(self.root / "forbidden"), RTDS_AGENT_DATA_DIR=str(self.root / "forbidden"),
                   OPENAI_API_KEY="test-never-use", OPENAI_VECTOR_STORE_ID="vs_forbidden")
        trace = self.root / "stdio.jsonl"
        params = StdioServerParameters(command=sys.executable, args=[str(repo / "tools/eval_mcp_server.py"),
                                      "--fixture", self.meta["root"], "--trace", str(trace)], env=env)
        records = []
        async def run():
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self.assertEqual({t.name for t in (await session.list_tools()).tools}, ALLOWED_TOOLS)
                    async def call(name, args, error=False):
                        reply = await session.call_tool(name, args)
                        self.assertEqual(reply.is_error, error, str(reply))
                        record = reply.structured_content
                        self.assertEqual(record["is_error"], error)
                        self.assertEqual(json.loads(reply.content[0].text), record)
                        records.append(record)
                        return record["result"]
                    await call("get_capabilities", {})
                    await call("list_rscad_projects", {"source_root": self.meta["source_root"]})
                    await call("inspect_rscad_project", {"project_path": self.meta["project"]})
                    await call("find_components", {"project_path": self.meta["project"], "query": "synthetic_gain"})
                    await call("get_component", {"project_path": self.meta["project"], "component_id": 1, "context": "subsystem:0"})
                    await call("search_rscad_api", {"query": "signal"})
                    known = await call("lookup_rscad_api", {"symbol": self.meta["known_symbol"]})
                    self.assertEqual(known["status"], "found")
                    self.assertFalse(known["sdk_imported"])
                    missing = await call("lookup_rscad_api", {"symbol": self.meta["unknown_symbol"]})
                    self.assertEqual(missing["status"], "unresolved")
                    detail = await call("get_component_parameters", {"project_path": self.meta["project"],
                        "component_id": 1, "context": "subsystem:0"})
                    self.assertEqual(detail["component"]["parameters"]["Gain"], "1")
                    self.assertEqual((await call("get_execution_policy", {}))["status"], "inactive")
                    prepared = await call("prepare_workflow", {k: self.meta[k] for k in ("test_spec", "grounding_paths")}
                                          | {"source_project": self.meta["project"]})
                    denial = await call("compile_project", {"workflow_path": prepared["workflow_path"]}, True)
                    self.assertEqual(denial["message"], "compile is not enabled by the local operator; no live calls made")
                    self.assertEqual(denial["error_type"], "PermissionError")
                    await call("compile_project", {"workflow_path": str(Path(self.meta["data_dir"]) / "forged.json")}, True)
                    self.assertFalse(records[-1]["dispatched"])
                    await call("execute_python", {"code": "never"}, True)
                    self.assertFalse(records[-1]["dispatched"])
                    await call("inspect_rscad_project", {"project_path": str(self.root / "outside")}, True)
                    self.assertFalse(records[-1]["dispatched"])
        asyncio.run(run())
        journal = [json.loads(x) for x in trace.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([x for x in journal if x["event"] == "completed"], records)
        self.assertEqual(len(journal), len(records) * 2)
        self.assertTrue(all(x["protected_unchanged"] for x in records))
        for relative, expected in self.meta["original_hashes"].items():
            self.assertEqual(digest(Path(self.meta["root"]) / relative), expected)
        self.assertFalse((self.root / "forbidden").exists())


if __name__ == "__main__":
    unittest.main()

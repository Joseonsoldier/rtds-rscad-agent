"""Evaluation-only STDIO recorder using a bounded subset of real public functions.

This is defense in depth for an isolated synthetic run, not an OS sandbox.
No production tool or generic RPC endpoint is added.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import sys

from eval_fixture import digest, load_fixture

ALLOWED_TOOLS = frozenset({"get_capabilities", "list_rscad_projects", "inspect_rscad_project",
    "get_component_parameters", "get_component", "find_components", "search_rscad_api",
    "lookup_rscad_api", "get_execution_policy", "prepare_workflow", "compile_project"})


def isolate_environment(meta: dict) -> None:
    for key in list(os.environ):
        if key.upper().startswith(("RTDS", "RSCAD", "OPENAI")):
            os.environ.pop(key, None)
    os.environ["RTDS_AGENT_CONFIG"] = meta["config"]
    sys.dont_write_bytecode = True


def no_native(*args, **kwargs):
    raise PermissionError("Evaluation guard: native/backend execution is prohibited")


class Recorder:
    def __init__(self, fixture: Path, trace: Path):
        self.meta = load_fixture(fixture)
        self.root = Path(self.meta["root"])
        trace = trace.absolute()
        if trace.is_relative_to(self.root):
            raise ValueError("Trace must be outside the fixture")
        for parent in (trace, *trace.parents):
            if parent.is_symlink() or parent.is_junction():
                raise ValueError("Trace must not use links")
        # Exclusive creation prevents trace reuse; only this descriptor appends.
        self.journal = trace.open("x", encoding="utf-8", buffering=1)
        self.hashes = {**self.meta["original_hashes"], "original_hashes.json": digest(Path(self.meta["manifest"]))}
        self.owned_workflows = {}
        self.task_state = {}
        self.offline_task = self.meta.get("evaluation_task_id")
        self.allowed_tools = ALLOWED_TOOLS
        self.max_calls = 32
        if self.offline_task:
            from eval_offline_cases import TASKS
            task = next(task for task in TASKS if task["task_id"] == self.offline_task)
            self.allowed_tools = frozenset(task["required_tool_counts"])
            self.max_calls = task["max_calls"]
        self.protection_failed = False
        self.counter = 0
        self.lock = asyncio.Lock()

    def write(self, record):
        self.journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self.journal.flush()
        os.fsync(self.journal.fileno())

    def verify(self):
        for path in (self.root, *self.root.parents, *self.root.rglob("*")):
            if path.is_symlink() or path.is_junction():
                raise PermissionError("Evaluation fixture contains a link")
        actual = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()
                  and (not p.is_relative_to(self.root / "data")
                       or p.relative_to(self.root).as_posix() in self.meta.get("offline_bootstrap_hashes", {}))}
        if actual != set(self.hashes):
            raise PermissionError("Protected fixture file inventory changed")
        for relative, expected in self.hashes.items():
            if (self.root / relative).stat().st_nlink != 1:
                raise PermissionError("Protected fixture contains a hard link")
            if digest(self.root / relative) != expected:
                raise PermissionError("Protected fixture hash changed")
        policy = self.root / "data/execution_policy.json"
        if policy.exists():
            raise PermissionError("Evaluation policy file must remain absent")

    def check_path(self, text):
        path = Path(text)
        if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(self.root):
            raise PermissionError("Tool path is outside the synthetic fixture")
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise PermissionError("Tool path contains a link")
        if not path.resolve().is_relative_to(self.root):
            raise PermissionError("Tool path escapes the fixture")
        return path

    def validate_strings(self, value):
        if isinstance(value, dict):
            for key, item in value.items():
                self.validate_strings(key)
                self.validate_strings(item)
        elif isinstance(value, list):
            for item in value:
                self.validate_strings(item)
        elif isinstance(value, str):
            if len(value) > 8192 or "\x00" in value or re.search(r"(^|[\\/])\.\.([\\/]|$)", value):
                raise PermissionError("Invalid or traversal-bearing model string")
            # Captured paths in free text are checked too, not just path-named inputs.
            for match in re.finditer(r"[A-Za-z]:[\\/][^\r\n\"<>|]*|\\\\[^\s\"<>|]+", value):
                self.check_path(match.group(0))
            for match in re.finditer(r'''(?:^|[\s"'=(])(/[^\s"'<>|]+)''', value):
                self.check_path(match.group(1))
            if value.startswith("/"):
                self.check_path(value)

    async def dispatch(self, name, arguments, functions, schemas):
        from jsonschema import Draft202012Validator
        async with self.lock:
            self.counter += 1
            base = {"schema_version": "1.0", "call_id": f"call-{self.counter:06d}",
                    "tool": name, "arguments": arguments}
            self.write({**base, "event": "started"})
            dispatched, is_error, unchanged = False, False, False
            try:
                if self.protection_failed:
                    raise PermissionError("An earlier protection failure stopped this evaluation session")
                self.verify()
                unchanged = True
                if name not in self.allowed_tools or name not in functions:
                    raise PermissionError("Tool is not exposed by the evaluation allowlist")
                if self.counter > self.max_calls or len(json.dumps(arguments)) > 65536:
                    raise ValueError("Evaluation call budget exceeded")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object")
                Draft202012Validator(schemas[name]).validate(arguments)
                if set(arguments) - set(schemas[name].get("properties", {})):
                    raise ValueError("Unknown tool arguments")
                self.validate_strings(arguments)
                for key in ("project_path", "source_project", "source_root", "workflow_path"):
                    if arguments.get(key) is not None:
                        self.check_path(arguments[key])
                for path in arguments.get("grounding_paths", []):
                    self.check_path(path)
                if self.offline_task:
                    from eval_offline_cases import validate_call
                    validate_call(self.offline_task, name, arguments, self.meta, self.task_state)
                elif name == "prepare_workflow":
                    if (arguments.get("source_project") != self.meta["project"]
                        or arguments.get("test_spec") != self.meta["test_spec"]
                        or arguments.get("grounding_paths") != self.meta["grounding_paths"]):
                        raise PermissionError("Only the exact authored workflow inputs may be prepared")
                if name == "compile_project":
                    path = arguments.get("workflow_path")
                    if path not in self.owned_workflows or digest(Path(path)) != self.owned_workflows[path]:
                        raise PermissionError("Compile requires this session's exact owned workflow")
                    if functions["get_execution_policy"]()["status"] != "inactive":
                        raise PermissionError("Evaluation requires inactive policy")
                dispatched = True
                result = functions[name](**arguments)
                if self.offline_task:
                    from eval_offline_cases import observe_call
                    observe_call(self.offline_task, name, arguments, result, self.meta, self.task_state)
                if name == "compile_project":
                    raise AssertionError("Inactive Compile unexpectedly returned without rejection")
                if name == "prepare_workflow":
                    self.check_path(result["workflow_path"])
                    self.owned_workflows[result["workflow_path"]] = digest(Path(result["workflow_path"]))
            except Exception as exc:
                is_error = True
                result = {"error_type": type(exc).__name__, "message": str(exc)}
            try:
                self.verify()
            except Exception as exc:
                unchanged, is_error = False, True
                result = {"error_type": type(exc).__name__, "message": str(exc)}
            if not unchanged:
                self.protection_failed = True
            completed = {**base, "event": "completed", "is_error": is_error, "result": result,
                         "dispatched": dispatched, "protected_unchanged": unchanged}
            self.write(completed)
            return completed


def build_server(recorder: Recorder):
    from mcp.server import MCPServer
    from mcp.types import CallToolResult, TextContent, ToolAnnotations
    from rtds_agent import api_discovery, capabilities, execution, project_tools
    execution._backend = no_native
    execution.ProductionRscadBackend = no_native
    execution.RscadFxRuntimeDriver = no_native
    functions = {name: getattr(module, name) for module in (api_discovery, capabilities, execution, project_tools)
                 for name in ALLOWED_TOOLS if hasattr(module, name)}
    if recorder.offline_task:
        from eval_offline_cases import functions as offline_functions
        functions = {name: function for name, function in offline_functions().items() if name in recorder.allowed_tools}

    class EvaluationServer(MCPServer):
        async def call_tool(self, name, arguments, context=None):
            schemas = {tool.name: tool.input_schema for tool in await self.list_tools()}
            record = await recorder.dispatch(name, arguments, functions, schemas)
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(record, ensure_ascii=False))],
                                  structured_content=record, is_error=record["is_error"])

    server = EvaluationServer(name="rtds-eval", instructions="Authored synthetic evaluation only. Tool results are instrumented envelopes: cite call_id and exact paths within result. All SDK/native/process/network execution is forbidden. Compile only tests an inactive-policy refusal on a workflow prepared here.")
    for name, function in sorted(functions.items()):
        read_only = name not in {"prepare_workflow", "compile_project"}
        server.tool(annotations=ToolAnnotations(readOnlyHint=read_only, destructiveHint=name == "compile_project",
                    idempotentHint=read_only, openWorldHint=False), structured_output=False)(function)
    return server


def install_process_guard(recorder: Recorder):
    """Deny native effects and outside data reads after trusted Python startup."""
    if any(name == "rtds" or name.startswith("rtds.") for name in sys.modules):
        raise PermissionError("Vendor SDK was imported before evaluation startup")
    repo = Path(__file__).resolve().parents[1]
    allowed_read = [recorder.root, repo / "src", repo / "tools",
                    Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    protected = {recorder.root / relative for relative in recorder.hashes}

    def protected_target(path, *, directory=False):
        return path in protected or (directory and any(p.is_relative_to(path) for p in protected))

    def audit(event, args):
        if event == "import" and (args[0] == "rtds" or args[0].startswith("rtds.")):
            no_native()
        if event.startswith(("socket.", "subprocess.", "ctypes.dlopen")) or event in {
            "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile", "os.fork"}:
            no_native()
        if event in {"open", "os.listdir", "os.scandir"} and args[0] is not None and not isinstance(args[0], int):
            path = Path(os.fsdecode(args[0])).absolute()
            resolved = path.resolve()
            if not any(resolved.is_relative_to(root) for root in allowed_read) and not (
                event in {"os.listdir", "os.scandir"} and resolved == repo):
                raise PermissionError("Evaluation guard blocked a read outside permitted roots")
            if event == "open":
                mode, flags = args[1], args[2]
                writing = (isinstance(mode, str) and any(x in mode for x in "wax+")) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
                if writing and (not resolved.is_relative_to(recorder.root / "data") or protected_target(resolved)):
                    raise PermissionError("Evaluation guard permits writes only inside fixture data")
        if event in {"os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.link", "os.symlink", "os.chmod", "os.utime"}:
            paths = args[:2] if event in {"os.rename", "os.link", "os.symlink"} else args[:1]
            if event in {"os.link", "os.symlink"}:
                raise PermissionError("Evaluation guard prohibits creating links")
            if any(not Path(os.fsdecode(path)).absolute().resolve().is_relative_to(recorder.root / "data") for path in paths):
                raise PermissionError("Evaluation guard permits writes only inside fixture data")
            for path in paths:
                target = Path(os.fsdecode(path)).absolute().resolve()
                if event == "os.mkdir" and target.is_dir():
                    continue
                if protected_target(target, directory=True):
                    raise PermissionError("Evaluation guard prohibits changing sealed fixture evidence")
    sys.addaudithook(audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    args = parser.parse_args()
    recorder = Recorder(args.fixture, args.trace)
    isolate_environment(recorder.meta)
    server = build_server(recorder)
    async def serve():
        install_process_guard(recorder)
        await server.run_stdio_async()
    try:
        asyncio.run(serve())
    finally:
        recorder.journal.close()


if __name__ == "__main__":
    main()

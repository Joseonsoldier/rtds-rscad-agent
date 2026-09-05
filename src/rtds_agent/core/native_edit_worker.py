"""Private, process-isolated SDK host for the fixed native edit protocol."""
from __future__ import annotations
import ipaddress
import json
from pathlib import Path
import re
import sys

from ..settings import get_settings, within
from ..safety import ToolSafetyError, sha256_file
from .native_edit import NativeJournal, edit_case, inspect_native_sdk


def main():
    job_path = Path(sys.argv[1]).resolve()
    settings = get_settings()
    if not within(job_path, settings.data_dir / ".native-editor-staging"):
        raise ToolSafetyError("Native worker job is outside the private staging root")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    from ..model_editor import validate_edit
    validate_edit(job["request"])
    stage = job_path.parent
    inp, out = Path(job["input_path"]), Path(job["output_path"])
    if (not within(inp, stage / "input") or not within(out, stage / "working") or out.exists()
            or sha256_file(inp) != job["request"]["source_sha256"]):
        raise ToolSafetyError("Native worker isolated path/hash mismatch")
    journal = NativeJournal(stage / "native_journal.json")
    sdk = inspect_native_sdk(settings)
    if sdk != job["sdk"] or not sdk["available"]:
        raise ToolSafetyError("Native worker SDK evidence changed or incomplete")
    journal.value.update(sdk=sdk, source_sha256=job["request"]["source_sha256"])
    journal.flush()
    return run_isolated_sdk(settings, inp, out, job["request"]["operations"], journal, sdk)


def run_isolated_sdk(settings, inp, out, operations, journal, sdk):
    """Internal adapter entry for the worker and explicitly authorized local trials."""
    if inspect_native_sdk(settings) != sdk or not sdk["available"]:
        raise ToolSafetyError("SDK evidence changed before native import")
    sys.dont_write_bytecode = True

    def audit(event, args):
        if event in {"socket.connect", "socket.bind"}:
            address = args[1]
            if not isinstance(address, tuple) or not ipaddress.ip_address(address[0]).is_loopback:
                raise ToolSafetyError("Native editor permits only loopback Python sockets")
    sys.addaudithook(audit)
    sys.path.insert(0, str(settings.sdk_root))
    import rtds.rscadfx as fx
    import rtds.comms.connection_setup as setup
    from rtds.comms._comms import Communicator
    setup.executable = settings.rscad_home / "BIN/RSCAD_FX.exe"
    setup.setup_host, setup.setup_port = "127.0.0.1", 0
    setup.in_existing, setup.timeout = True, 20
    original_send = Communicator.send_message
    ids = {op["component_id"] for op in operations}

    def guarded(self, message):
        if message == b"\n": return original_send(self, message)
        instruction = json.loads(message.decode())["instruction"]
        path, method = instruction["path"], instruction["method"]
        args = [a["value"] for a in instruction.get("args", [])]
        pending = journal.value["native_calls"][-1] if journal.value["native_calls"] else {}
        allowed = False
        if path == "rscad":
            if method in {"ping", "getMinimumApiVersion", "getApiVersion", "getVersion"}: allowed = not args
            if method == "getCaseNamed": allowed = args in ([str(inp), False], [str(out), False])
            if method == "openCase":
                allowed = pending.get("status") == "started" and ((pending.get("operation") == "open_case" and args == [str(inp)]) or (pending.get("operation") == "reopen" and args == [str(out)]))
        else:
            match = re.fullmatch(r"rscad\.case:(\d+)(.*)", path)
            if match and int(match[1]) == journal.value["owned_case"]:
                suffix = match[2]
                if suffix == "":
                    allowed = method in {"getFile", "getModified", "getRunState"} and not args
                    if method == "saveAs": allowed = args == [str(out)] and not out.exists() and pending.get("operation") == "save_as" and pending.get("status") == "started"
                    if method == "close": allowed = args == [False] and pending.get("operation") in {"close", "cleanup_close"} and pending.get("status") == "started"
                if suffix == ".draft" and method == "getComponent": allowed = len(args) == 1 and args[0] in ids
                component = re.fullmatch(r"\.draft\.comp_id:(\d+)", suffix)
                if component and int(component[1]) in ids:
                    allowed = method in {"getComponentType", "getLocation"} and not args
                    if method == "getParameter":
                        allowed = any(op.get("parameter") and args == [op["parameter"]] for op in operations if op["component_id"] == int(component[1]))
                    if pending["status"] == "started" and pending["mutation"]:
                        op = pending["arguments"]
                        if isinstance(op, dict) and op.get("component_id") == int(component[1]):
                            if method == "setParameter": allowed = args == [op.get("parameter"), op.get("new_value")]
                            if method == "setLocation": allowed = args == [op.get("location")]
        journal.value.setdefault("rpc_calls", []).append({"path": path, "method": method, "arguments": args, "allowed": allowed})
        journal.flush()
        if not allowed:
            journal.value["rejected_rpc"] = {"path": path, "method": method, "arguments": args}
            journal.flush()
            raise ToolSafetyError("Native editor rejected an out-of-scope SDK call")
        return original_send(self, message)
    # This process alone wraps transport; no installed SDK source is changed.
    Communicator.send_message = guarded
    try:
        edit_case(fx.remote_connection(), inp, out, operations, journal)
        if inspect_native_sdk(settings) != sdk: raise ToolSafetyError("SDK changed during native edit")
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

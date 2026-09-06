"""Narrow SDK editor protocol and durable mutation journal, not a generic RPC API.

The first adapter scope is existing flat Draft parameter/location edits. Native
construction, grouped edits and compilation require separate qualification.
"""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path

from ..safety import ToolSafetyError, sha256_file
from .state_machine import sha256_json

OPERATIONS = frozenset({"set_parameter", "set_selector", "set_string", "rename_component", "move_component"})
DECLARATIONS = {
    "rscadfx.py": {"RSCADFX": ["connect", "disconnect", "get_version", "open_case", "get_case", "new_case", "_new_case"]},
    "case.py": {"Case": ["file", "save", "_save_as", "close"], "State": ["run_state", "modified"]},
    "draft.py": {"Draft": ["get_object"]},
    "component.py": {"DraftComponent": ["component_type", "get_parameter", "set_parameter", "location", "orientation", "mirrored"]},
    "component_compatible.py": {"ComponentCompatible": ["_insert_component", "create_wire", "_create_wire", "select_area", "copy", "_paste"]},
    "subtab.py": {"Subtab": ["num_subpages", "get_subpage"]},
    "case_settings.py": {"CaseSettings": ["timestep", "title", "realtime"]},
}


def inspect_native_sdk(settings):
    """Hash all imported vendor sources and inspect fixed declarations without import."""
    from ..api_discovery import _inventory
    root = settings.sdk_root / "rtds"
    evidence = {"sdk_version": "unknown", "sources": {}, "missing": [],
                "supported_operations": sorted(OPERATIONS), "integration_qualified": False,
                "adapter_sha256": sha256_file(Path(__file__)),
                "worker_sha256": sha256_file(Path(__file__).with_name("native_edit_worker.py"))}
    evidence["reconstruction_sources"] = {name:sha256_file(Path(__file__).with_name(name)) for name in ("native_rebuild.py", "native_rebuild_adapter.py", "native_temp.py")}
    evidence["reconstruction_strategies"] = ["insert", "clipboard"]
    if not settings.rscad_home or not root.is_dir():
        evidence["missing"].append("installed_sdk")
    else:
        trees, total = {}, 0
        for path in _inventory(root, settings.rscad_home):
            size = path.stat().st_size
            total += size
            if size > 2*1024*1024 or total > 32*1024*1024:
                raise ToolSafetyError("Native SDK source bounds exceeded")
            raw = path.read_bytes()
            import hashlib
            digest = hashlib.sha256(raw).hexdigest()
            if sha256_file(path) != digest:
                raise ToolSafetyError("SDK changed while inspecting")
            name = path.relative_to(root).as_posix()
            evidence["sources"][name] = digest
            trees[name] = ast.parse(raw.decode("utf-8-sig"))
        for node in getattr(trees.get("__init__.py"), "body", []):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
                if isinstance(node.value, ast.Constant): evidence["sdk_version"] = str(node.value.value)
        for file, classes in DECLARATIONS.items():
            for owner, names in classes.items():
                found = {n.name for cls in getattr(trees.get(file), "body", [])
                         if isinstance(cls, ast.ClassDef) and cls.name == owner
                         for n in cls.body if isinstance(n, ast.FunctionDef)}
                evidence["missing"].extend(f"{file}:{owner}.{name}" for name in names if name not in found)
    executable = settings.rscad_home / "BIN/RSCAD_FX.exe" if settings.rscad_home else None
    if executable and executable.is_file() and executable.resolve().is_relative_to(settings.rscad_home.resolve()) and not executable.is_symlink():
        evidence["executable_sha256"] = sha256_file(executable)
    else:
        evidence["missing"].append("RSCAD_FX.exe")
    evidence["available"] = not evidence["missing"] and evidence["sdk_version"] == "1.1"
    evidence["evidence_id"] = sha256_json(evidence)
    return evidence


def values_equal(actual, expected, numeric=False):
    if numeric:
        try:
            a, b = Decimal(str(actual)), Decimal(str(expected))
            return a.is_finite() and b.is_finite() and a == b
        except InvalidOperation:
            return False
    return str(actual) == str(expected)


class NativeJournal:
    """Persist intent BEFORE a potentially mutating call; never retry on failure."""
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists(): raise ToolSafetyError("Native journal already exists; never resume an attempt")
        self.value = {"schema_version": "1.0", "status": "prepared", "native_mutation_possible": False,
                      "owned_case": None, "identity_verified": False, "cleanup_verified": False,
                      "last_operation": None, "native_calls": [], "readbacks": [], "cleanup": [],
                      "integration_qualified": False}
        self.flush()

    def flush(self):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self.value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def call(self, name, function, *, mutation=False, arguments=None):
        if self.value["status"] == "operator_recovery_required":
            raise ToolSafetyError("Native identity lost; operator recovery required")
        self.value["last_operation"] = name
        if mutation: self.value["native_mutation_possible"] = True
        row = {"operation": name, "arguments": arguments, "status": "started", "mutation": mutation}
        self.value["native_calls"].append(row)
        self.flush()
        try:
            result = function()
        except Exception as exc:
            row.update(status="failed", error_type=type(exc).__name__)
            self.flush()
            raise
        row["status"] = "returned"
        self.flush()
        return result

    def lost_identity(self):
        self.value.update(identity_verified=False, status="operator_recovery_required")
        self.flush()


def paste_ids(canvas, location, journal):
    """SDK 1.1 adapter workaround: -1 denotes GROUP, not a component handle.

    This does not establish success. The caller must verify the saved group and
    member structure before publication. No vendor file or class is patched.
    """
    if type(journal.value["owned_case"]) is not int or not journal.value["identity_verified"]:
        raise ToolSafetyError("Paste requires a verified owned native case")
    ids = journal.call("paste", lambda: canvas._paste(tuple(location), canvas.identifier),
                       mutation=True, arguments={"location": list(location)})
    if not isinstance(ids, list) or any(type(i) is not int or i < -1 for i in ids):
        raise ToolSafetyError("Unsupported native paste return; mutation may have occurred")
    positive = [i for i in ids if i >= 0]
    if len(positive) != len(set(positive)):
        raise ToolSafetyError("Duplicate native paste identity")
    return {"component_ids": positive, "group_sentinels": ids.count(-1), "structure_verified": False}


def edit_case(app, input_path, output_path, operations, journal):
    """Fixed adapter over an owned isolated case. No Compile/Runtime/rack calls."""
    input_path, output_path = Path(input_path).resolve(), Path(output_path).resolve()
    if input_path == output_path or output_path.exists():
        raise ToolSafetyError("Native output must be a new isolated file")
    if any(op["op"] not in OPERATIONS or op["context"] != "subsystem:0" for op in operations):
        raise ToolSafetyError("Native editor currently supports existing flat Draft parameter/location edits only")
    case = None
    connected = False
    closed, disconnected = False, False

    def identity(expected, *, clean=False):
        try:
            valid = (case.caseid == journal.value["owned_case"] and
                     Path(case.file).resolve() == expected and case.state.run_state == "stopped")
            if not valid: raise ToolSafetyError("Native case identity/state mismatch")
            if clean and case.state.modified is not False:
                raise ToolSafetyError("Owned native case has unsaved changes")
            journal.value["identity_verified"] = True
            journal.flush()
        except Exception:
            journal.lost_identity()
            raise

    def observe(op, expected):
        c = case.draft.get_object(op["component_id"])
        if c is None or c.unique_id != op["component_id"] or c.component_type != op["component_type"]:
            raise ToolSafetyError("Native component identity mismatch")
        value = list(c.location) if op["op"] == "move_component" else c.get_parameter(op["parameter"])
        matches = value == expected if isinstance(expected, list) else values_equal(value, expected, op["op"] == "set_parameter")
        journal.value["readbacks"].append({"component_id": op["component_id"], "context": op["context"],
            "field": op.get("parameter", "location"), "expected": expected, "actual": value, "matches": matches})
        journal.flush()
        if not matches: raise ToolSafetyError("Native expected value/readback mismatch")
        return c

    try:
        # A failed connection can still own SDK resources, so cleanup attempts it.
        connected = True
        journal.call("connect", app.connect)
        journal.value["observed_rscad_version"] = app.get_version()
        if str(journal.value["observed_rscad_version"]) not in {"2.7", "2.7.3"}:
            raise ToolSafetyError("Native RSCAD version outside reviewed scope")
        for path in (input_path, output_path):
            if app.get_case(file=str(path), open_file=False) is not None:
                raise ToolSafetyError("Native trial path is already open")
        case = journal.call("open_case", lambda: app.open_case(str(input_path)), mutation=True, arguments=str(input_path))
        journal.value["owned_case"] = case.caseid
        identity(input_path, clean=True)
        for op in operations:
            identity(input_path)
            old = op["expected_location"] if op["op"] == "move_component" else op["expected_old_value"]
            new = op["location"] if op["op"] == "move_component" else op["new_value"]
            c = observe(op, old)
            if op["op"] == "move_component":
                action = lambda: setattr(c, "location", tuple(new))
            else:
                action = lambda: c.set_parameter(op["parameter"], new)
            journal.call(op["op"], action, mutation=True, arguments=op)
            observe(op, new)
        identity(input_path)
        journal.call("save_as", lambda: case.save(str(output_path)), mutation=True, arguments=str(output_path))
        identity(output_path, clean=True)
        digest = sha256_file(output_path)
        if journal.call("close", lambda: case.close(force=False)) is not True:
            raise ToolSafetyError("Native close was not confirmed")
        closed = True
        case = None
        if app.get_case(file=str(output_path), open_file=False) is not None:
            raise ToolSafetyError("Closed native case is still present")
        journal.value["closed_before_reopen"] = True
        closed = False
        case = journal.call("reopen", lambda: app.open_case(str(output_path)), mutation=True, arguments=str(output_path))
        journal.value["owned_case"] = case.caseid
        identity(output_path, clean=True)
        # Several edits may address distinct fields on one component.
        for op in operations:
            observe(op, op["location"] if op["op"] == "move_component" else op["new_value"])
        if sha256_file(output_path) != digest: raise ToolSafetyError("Reopen changed candidate bytes")
        journal.value.update(status="verified_edit", candidate_sha256=digest, reopened=True)
    except Exception as exc:
        journal.value.update(error_type=type(exc).__name__, error=str(exc))
        if journal.value["status"] != "operator_recovery_required": journal.value["status"] = "failed"
        raise
    finally:
        if case is not None and journal.value["status"] != "operator_recovery_required":
            try:
                expected = output_path if output_path.exists() else input_path
                identity(expected, clean=True)
                closed = journal.call("cleanup_close", lambda: case.close(force=False)) is True
                if closed and app.get_case(file=str(expected), open_file=False) is not None: closed = False
                journal.value["cleanup"].append({"action": "close", "verified": closed})
            except Exception as exc:
                journal.value["cleanup"].append({"action": "close", "verified": False, "error": str(exc)})
        if connected:
            try:
                app.disconnect(terminate=False)
                disconnected = True
                journal.value["cleanup"].append({"action": "disconnect", "verified": True, "terminate": False})
            except Exception as exc:
                journal.value["cleanup"].append({"action": "disconnect", "verified": False, "error": str(exc)})
        journal.value["cleanup_verified"] = closed and disconnected
        if journal.value["native_mutation_possible"] and not journal.value["cleanup_verified"]:
            journal.value["status"] = "operator_recovery_required"
        journal.flush()
    if not journal.value["cleanup_verified"]: raise ToolSafetyError("Native cleanup was not verified")
    return journal.value

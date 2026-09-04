"""Static binding audit for the installed RSCAD FX Python Runtime API.

The audit parses source files with ``ast``.  It never imports ``rtds``, creates
a connection, queries racks, opens a case, or calls Runtime.
"""

from __future__ import annotations

import ast
import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from rtds_agent.core.state_machine import sha256_file, sha256_json


SCHEMA_VERSION = "1.0"
DEFAULT_SITE_PACKAGES = None
HERE = Path(__file__).resolve().parent
DEFAULT_ADAPTER = HERE / "runtime_backend.py"
OUTPUT = HERE / "runtime_api_surface_validation.json"


class RuntimeApiSurfaceError(RuntimeError):
    """Raised when installed API source cannot be audited."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _ref(path: Path) -> dict[str, Any]:
    target = path.resolve()
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "bytes": target.stat().st_size,
    }


def _parse(path: Path) -> tuple[ast.Module, str]:
    if not path.is_file():
        raise RuntimeApiSurfaceError(f"API source is missing: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        return ast.parse(text, filename=str(path)), text
    except SyntaxError as exc:
        raise RuntimeApiSurfaceError(f"API source is not valid Python: {path}") from exc


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise RuntimeApiSurfaceError(f"class is missing from installed API: {name}")


def _function(container: ast.Module | ast.ClassDef, name: str) -> ast.FunctionDef:
    for node in container.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise RuntimeApiSurfaceError(f"function is missing from installed API: {name}")


def _function_info(node: ast.FunctionDef) -> dict[str, Any]:
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults: dict[str, str] = {}
    if node.args.defaults:
        for arg, value in zip(positional[-len(node.args.defaults):], node.args.defaults):
            defaults[arg.arg] = ast.unparse(value)
    for arg, value in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if value is not None:
            defaults[arg.arg] = ast.unparse(value)
    decorators = [ast.unparse(item) for item in node.decorator_list]
    return {
        "name": node.name,
        "arguments": [item.arg for item in positional + node.args.kwonlyargs],
        "defaults": defaults,
        "return_annotation": (
            ast.unparse(node.returns) if node.returns is not None else None
        ),
        "decorators": decorators,
    }


def _version(tree: ast.Module) -> str | None:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        value = node.value
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
            if isinstance(value, ast.Constant):
                return str(value.value)
    return None


def _imports_rtds(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            item.name == "rtds" or item.name.startswith("rtds.")
            for item in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "rtds" or node.module.startswith("rtds."))
        ):
            return True
    return False


def _payload_sha256(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    payload.get("integrity", {}).pop("payload_sha256", None)
    return sha256_json(payload)


def inspect_runtime_api_surface(
    *,
    site_packages: str | Path,
    adapter_path: str | Path = DEFAULT_ADAPTER,
) -> dict[str, Any]:
    root = Path(site_packages).resolve()
    adapter = Path(adapter_path).resolve()
    sources = {
        "package": root / "rtds" / "__init__.py",
        "application": root / "rtds" / "rscadfx.py",
        "case": root / "rtds" / "case.py",
        "case_settings": root / "rtds" / "case_settings.py",
        "component": root / "rtds" / "component.py",
        "runtime": root / "rtds" / "rtx.py",
        "connection_setup": root / "rtds" / "comms" / "connection_setup.py",
    }
    parsed: dict[str, ast.Module] = {}
    texts: dict[str, str] = {}
    for name, path in {**sources, "adapter": adapter}.items():
        parsed[name], texts[name] = _parse(path)

    application = _class(parsed["application"], "RSCADFX")
    rack = _class(parsed["application"], "Rack")
    case = _class(parsed["case"], "Case")
    state = _class(parsed["case"], "State")
    settings = _class(parsed["case_settings"], "CaseSettings")
    signal = _class(parsed["component"], "Signal")
    io_component = _class(parsed["component"], "IOComponent")
    io_positional = _class(parsed["component"], "IOPositionalComponent")
    methods = {
        "remote_connection": _function_info(
            _function(parsed["application"], "remote_connection")
        ),
        "connect": _function_info(_function(application, "connect")),
        "disconnect": _function_info(_function(application, "disconnect")),
        "get_version": _function_info(_function(application, "get_version")),
        "open_case": _function_info(_function(application, "open_case")),
        "get_case": _function_info(_function(application, "get_case")),
        "get_available_racks": _function_info(
            _function(application, "get_available_racks")
        ),
        "case_close": _function_info(_function(case, "close")),
        "case_run": _function_info(_function(case, "run")),
        "case_stop": _function_info(_function(case, "stop")),
        "case_update_plots": _function_info(_function(case, "update_plots")),
        "case_get_signal": _function_info(_function(case, "get_signal")),
        "state_run_state": _function_info(_function(state, "run_state")),
        "settings_starting_rack": _function_info(
            _function(settings, "starting_rack")
        ),
        "signal_get_time_data": _function_info(
            _function(signal, "get_time_data")
        ),
        "signal_get_data": _function_info(_function(signal, "get_data")),
        "runtime_value": _function_info(_function(io_component, "value")),
        "runtime_position": _function_info(_function(io_positional, "position")),
    }
    adapter_text = texts["adapter"]
    required_adapter_fragments = (
        "import rtds.comms.connection_setup as connection_setup",
        "import rtds.rscadfx",
        "connection_setup.executable = self.config.rscad_executable",
        "connection_setup.in_existing = True",
        "connection_setup.timeout = self.config.connection_timeout_seconds",
        "rtds.rscadfx.remote_connection()",
        "app.connect()",
        "app.get_version()",
        "app.get_available_racks()",
        "app.get_case(file=str(working_copy), open_file=False)",
        "app.open_case(str(working_copy))",
        "case.get_signal(",
        "case.run()",
        "case.update_plots()",
        "handle.get_time_data()",
        "handle.get_data()",
        "case.stop()",
        "case.close(force=True)",
        "app.disconnect(terminate=False)",
        'setattr(handle, attribute, action["value"])',
        "setattr(handle, attribute, original_value)",
    )
    forbidden_adapter_fragments = (
        ".set_data(",
        ".import_parameters(",
        ".compile(",
        ".load_flow(",
        ".save(",
        "rack.power",
        "rack.security",
    )
    checks = {
        "api_version_1_1": _version(parsed["package"]) == "1.1",
        "remote_connection_zero_argument_factory": (
            methods["remote_connection"]["arguments"] == []
        ),
        "application_connect_returns_none": (
            methods["connect"]["return_annotation"] == "None"
        ),
        "application_disconnect_terminate_false": (
            methods["disconnect"]["defaults"].get("terminate") == "False"
        ),
        "application_version_and_case_methods_present": all(
            methods[name]["arguments"]
            for name in ("get_version", "open_case", "get_case", "get_available_racks")
        ),
        "get_case_open_file_false_supported": (
            methods["get_case"]["defaults"].get("open_file") == "True"
            and "open_file" in methods["get_case"]["arguments"]
        ),
        "rack_num_attribute_declared": "self.num: int = num" in texts["application"],
        "case_run_returns_none": methods["case_run"]["return_annotation"] == "None",
        "case_stop_returns_none": methods["case_stop"]["return_annotation"] == "None",
        "case_update_plots_returns_none": (
            methods["case_update_plots"]["return_annotation"] == "None"
        ),
        "case_close_force_false_supported": (
            methods["case_close"]["defaults"].get("force") == "False"
        ),
        "case_get_signal_returns_signal": (
            methods["case_get_signal"]["return_annotation"] == "Signal"
        ),
        "run_state_readable_property": (
            methods["state_run_state"]["return_annotation"] == "str"
            and any("ConnectedProperty(True, False)" == item for item in methods["state_run_state"]["decorators"])
        ),
        "starting_rack_integer_property": (
            methods["settings_starting_rack"]["return_annotation"] == "int"
        ),
        "signal_numeric_array_methods": (
            methods["signal_get_time_data"]["return_annotation"] == "List[float]"
            and methods["signal_get_data"]["return_annotation"] == "List[float]"
        ),
        "runtime_value_is_read_write_connected_property": (
            "ConnectedProperty(True, True)"
            in methods["runtime_value"]["decorators"]
        ),
        "runtime_position_is_read_write_connected_property": (
            "ConnectedProperty(True, True)"
            in methods["runtime_position"]["decorators"]
        ),
        "connection_setup_fields_present": all(
            token in texts["connection_setup"]
            for token in ("in_existing: bool", "executable: Optional[Path]", "timeout: float")
        ),
        "adapter_required_calls_exactly_present": all(
            token in adapter_text for token in required_adapter_fragments
        ),
        "adapter_run_success_uses_state_not_return": (
            'execution["run_state_after_start"].lower() == "running"' in adapter_text
            and "bool(run_value)" not in adapter_text
        ),
        "adapter_stop_success_uses_state_not_return": (
            'execution["run_state_after_stop"].lower() == "stopped"' in adapter_text
            and "bool(stop_value" not in adapter_text
        ),
        "adapter_forbidden_write_calls_absent": not any(
            token in adapter_text for token in forbidden_adapter_fragments
        ),
        "adapter_has_no_cli": "def main(" not in adapter_text,
        "static_parse_only": not _imports_rtds(
            ast.parse(Path(__file__).read_text(encoding="utf-8"))
        ),
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created_at": now(),
        "status": "passed" if all(checks.values()) else "failed",
        "mode": "static_installed_rscad_fx_runtime_api_surface_validation",
        "rscad_fx_version": "2.7.3",
        "python_api_version": _version(parsed["package"]),
        "source_files": {name: _ref(path) for name, path in sources.items()},
        "adapter": {
            **_ref(adapter),
            "required_fragment_count": len(required_adapter_fragments),
            "forbidden_fragment_count": len(forbidden_adapter_fragments),
        },
        "surface": methods,
        "checks": checks,
        "safety": {
            "rtds_package_imported": False,
            "rscad_connection_opened": False,
            "rack_query_called": False,
            "case_opened": False,
            "compile_called": False,
            "runtime_called": False,
            "parameter_write_called": False,
            "hardware_io_called": False,
            "vendor_source_modified": False,
        },
        "integrity": {
            "all_checks_passed": all(checks.values()),
            "payload_sha256": "",
        },
    }
    manifest["integrity"]["payload_sha256"] = _payload_sha256(manifest)
    return manifest

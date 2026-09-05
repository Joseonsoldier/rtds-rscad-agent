"""Read installed extension API declarations without importing or calling vendor code."""
from __future__ import annotations
from typing import Any
import ast
import hashlib
from html.parser import HTMLParser
from pathlib import Path
from .settings import get_settings, within
from .safety import ToolSafetyError, sha256_file
from .core.state_machine import sha256_json
from .core.runtime_api_surface import _function_info

# These are observed SDK source declarations, not an executable command registry.
ROUTES = {
    "selector_change": [("component.py", "DraftComponent", "set_parameter")],
    "insert_component": [("component_compatible.py", "ComponentCompatible", "insert_component"), ("component_compatible.py", "ComponentCompatible", "_insert_component")],
    "create_wire": [("component_compatible.py", "ComponentCompatible", "create_wire"), ("component_compatible.py", "ComponentCompatible", "_create_wire")],
    "copy_paste": [("component_compatible.py", "ComponentCompatible", name) for name in ("copy", "_copy", "paste", "_paste")],
    "save_as": [("case.py", "Case", name) for name in ("save", "_save_as")],
    "case_identity": [("rscadfx.py", "RSCADFX", name) for name in ("get_case", "_get_case_named")] + [("case.py", "Case", "file"), ("case.py", "State", "modified"), ("case.py", "State", "run_state")],
    "draft_location_selection": [("component.py", "DraftComponent", name) for name in ("location", "selected")],
    "runtime_objects": [("rtx.py", "Runtime", name) for name in ("get_objects", "get_object", "__get_component")],
    "signal_lookup": [("case.py", "Case", "get_signal"), ("rtx.py", "Runtime", "get_signal"), ("rtx.py", "Runtime", "__get_signal")],
    "connection": [("rscadfx.py", "RSCADFX", name) for name in ("connect", "disconnect", "get_version")],
}
SOURCE_FILES = sorted({file for route in ROUTES.values() for file, _, _ in route} | {"__init__.py", "comms/connector.py", "subtab.py", "draft.py", "_graphic_saver.py"})


class _Anchors(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        self.ids.update(value for key, value in attrs if key == "id" and value)


def inspect_extension_support() -> dict[str, Any]:
    """Read bounded local SDK declarations/docs; every live extension remains unqualified."""
    settings = get_settings()
    root = settings.sdk_root / "rtds"
    sources, trees = {}, {}
    for relative in SOURCE_FILES:
        path = root / relative
        if not within(path, root) or not path.is_file():
            sources[relative] = {"status": "missing_or_outside_root"}
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            sources[relative] = {"status": "unsupported_size"}
            continue
        before = sha256_file(path)
        try:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != before:
                raise ToolSafetyError("SDK bytes changed before parsing")
            tree = ast.parse(raw.decode("utf-8-sig"))
        except (SyntaxError, UnicodeError):
            sources[relative] = {"status": "unsupported_source", "sha256": before}
            continue
        if sha256_file(path) != before:
            raise ToolSafetyError("SDK changed during extension inspection")
        sources[relative] = {"status": "parsed", "sha256": before}
        trees[relative] = tree
    version = "unknown"
    for node in getattr(trees.get("__init__.py"), "body", []):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets):
            if isinstance(node.value, ast.Constant) and type(node.value.value) in (str, int, float):
                version = str(node.value.value)
    documentation = {"status": "unavailable"}
    anchors = set()
    if settings.rscad_home:
        doc = settings.rscad_home / "python/rscad-fx-python/doc/index.html"
        if within(doc, settings.rscad_home) and doc.is_file() and doc.stat().st_size <= 20 * 1024 * 1024:
            digest = sha256_file(doc)
            parser = _Anchors()
            raw_doc = doc.read_bytes()
            if hashlib.sha256(raw_doc).hexdigest() != digest:
                raise ToolSafetyError("API documentation changed before parsing")
            parser.feed(raw_doc.decode("utf-8"))
            anchors = parser.ids
            if sha256_file(doc) != digest:
                raise ToolSafetyError("API documentation changed during inspection")
            documentation = {"status": "read", "relative_path": "python/rscad-fx-python/doc/index.html", "sha256": digest}
    features = {}
    for feature, route in ROUTES.items():
        declarations = []
        for relative, owner, name in route:
            owners = [n for n in getattr(trees.get(relative), "body", []) if isinstance(n, ast.ClassDef) and n.name == owner]
            methods = [n for cls in owners for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name]
            anchor = "rtds." + relative[:-3].replace("/", ".") + "." + owner + "." + name
            declarations.append({"source": relative, "class": owner, "name": name,
                                 "status": "declared" if methods else "not_found",
                                 "definitions": [{**_function_info(n), "line": n.lineno, "end_line": n.end_lineno} for n in methods],
                                 "documentation_anchor": anchor if anchor in anchors else None})
        complete = all(d["status"] == "declared" for d in declarations)
        features[feature] = {"status": "source_declared" if complete else "incomplete_source",
                             "version_in_reviewed_scope": version == "1.1", "requires_connection": True,
                             "integration_qualified": False, "declarations": declarations}
    # A plot export is not a Draft/window screenshot API. Absence here is a
    # bounded source-audit conclusion, not a claim about all vendor interfaces.
    for relative, evidence in sources.items():
        if "sha256" in evidence and sha256_file(root / relative) != evidence["sha256"]:
            raise ToolSafetyError("SDK changed before inspection completed")
    if get_settings() != settings:
        raise ToolSafetyError("Configuration changed during extension inspection")
    evidence = {"sdk_version": version, "sources": sources, "documentation": documentation,
                "inspector_sha256": sha256_file(Path(__file__))}
    return {"status": "completed", "evidence_id": sha256_json(evidence), "evidence": evidence,
            "features": features, "rscad_running_version": "unknown", "sdk_imported": False,
            "live_calls_made": False, "integration_qualified": False,
            "draft_window_capture": {"status": "unsupported", "reason": "No reviewed Draft/window capture binding; PlotSavable.save_data is plot export only"},
            "scope": "installed source declarations only; wrappers may invoke additional remote operations",
            "limitations": ["copy/paste uses shared application clipboard", "location setters can snap to the grid",
                            "file/modified/subpage/selected properties also require a connection",
                            "No operator policy or task authorization is inferred from this report"]}

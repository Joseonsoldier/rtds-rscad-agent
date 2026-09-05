"""Bounded, read-only installed-definition catalog. Never imports vendor code."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Any
from rtds_agent.settings import get_settings, within
from rtds_agent.safety import ToolSafetyError, sha256_file
from .state_machine import sha256_json
from .topology_parser import parse_parameter_schema, parse_active_nodes

MAX_FILES = 12000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024


def inventory():
    settings = get_settings()
    root = settings.definition_root
    if root.is_symlink() or root.is_junction():
        raise ToolSafetyError("Definition catalog root cannot be a link")
    if not root.is_dir():
        return settings, [], sha256_json([])
    records, total, entries = [], 0, 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        entries += len(dirs) + len(names)
        if entries > MAX_FILES * 3 or len(Path(folder).relative_to(root).parts) > 16:
            raise ToolSafetyError("Definition catalog traversal exceeds bounds")
        for name in [*dirs, *names]:
            path = Path(folder) / name
            if path.is_symlink() or path.is_junction() or not within(path, root):
                raise ToolSafetyError("Definition catalog refuses links or escaping paths")
        for name in names:
            path = Path(folder) / name
            size = path.stat().st_size
            total += size
            if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(records) >= MAX_FILES:
                raise ToolSafetyError("Definition catalog exceeds file/count/total byte limits")
            records.append({"component_type": name, "definition_id": path.relative_to(root).as_posix(),
                            "path": str(path.resolve()), "sha256": sha256_file(path), "bytes": size})
    records.sort(key=lambda r: r["definition_id"])
    from . import topology_parser
    return settings, records, sha256_json({"root": str(root), "files": records,
        "configured_version": settings.expected_rscad_version, "reader_sha256": sha256_file(Path(__file__)),
        "parser_sha256": sha256_file(Path(topology_parser.__file__))})


def resolve_schema(component_type: str, definition_id: str | None = None,
                   parameters: dict | None = None, context: str = "subsystem:0") -> dict[str, Any]:
    settings, rows, snapshot = inventory()
    matches = [r for r in rows if r["component_type"] == component_type
               and (definition_id is None or r["definition_id"] == definition_id)]
    base = {"component_type": component_type, "catalog_snapshot_id": snapshot,
            "configured_rscad_version": settings.expected_rscad_version, "observed_rscad_version": "unknown",
            "source_type": "installed_definition", "integration_qualified": False}
    if len(matches) != 1:
        return {**base, "status": "ambiguous" if matches else "unresolved", "evidence_level": "unknown", "candidates": matches}
    ref = matches[0]
    body = Path(ref["path"]).read_bytes()
    if hashlib.sha256(body).hexdigest() != ref["sha256"]:
        raise ToolSafetyError("Definition changed during schema read")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ToolSafetyError("Definition is not supported UTF-8 text") from exc
    schema = parse_parameter_schema(text)
    if len(schema) > 500:
        raise ToolSafetyError("Definition exceeds 500 parsed parameters")
    # Do not silently accept duplicate or unsupported parameter declarations.
    from .topology_parser import _section_lines
    declarations = [s.strip() for s in _section_lines(text, "PARAMETERS") if s.strip()
                    and not s.strip().startswith(("//", "SECTION:"))]
    coverage = "parsed_subset" if len(declarations) != len(schema) else "declared_parameters_parsed"
    params = parameters or {}
    if len(params) > 500 or any(k not in schema or not isinstance(v, str) or len(v) > 500 for k, v in params.items()):
        raise ToolSafetyError("Active-node parameters must be bounded declared string values")
    nodes, warnings = parse_active_nodes(text, {"parameters": params, "context": context, "component_type": component_type})
    if len(nodes) > 2000:
        raise ToolSafetyError("Definition has too many nodes")
    clean = {key: {k: v for k, v in row.items() if k != "raw"} for key, row in schema.items()}
    from rtds_agent.input_contracts import validate
    validate({"parameters":clean,"nodes":nodes},{"type":"object"})
    if inventory()[2] != snapshot or get_settings() != settings:
        raise ToolSafetyError("Definition catalog changed during schema observation")
    return {**base, "status": "resolved", "evidence_level": "derived", "definition": ref,
            "parameters": clean, "selectors": [key for key, row in schema.items() if row["data_type"] == "TOGGLE"],
            "active_nodes": [{k: v for k, v in n.items() if k != "raw"} for n in nodes], "warnings": warnings,
            "parameter_coverage": coverage, "placement_constraints": "not_evaluated",
            "port_semantics_scope": "declared kind/direction/type/phase only; no inferred electrical meaning",
            "node_parameters": params, "context": context}


def search_component_catalog(query: str, limit: int = 20, offset: int = 0,
                             snapshot_id: str | None = None) -> dict[str, Any]:
    """Search canonical installed definition names/paths; duplicate names remain distinct."""
    if not isinstance(query, str) or not 1 <= len(query) <= 200:
        raise ToolSafetyError("query must have 1–200 characters")
    if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
        raise ToolSafetyError("Invalid catalog pagination")
    settings, rows, snapshot = inventory()
    if (offset and snapshot_id is None) or (snapshot_id is not None and snapshot_id != snapshot):
        raise ToolSafetyError("Catalog snapshot changed or missing for pagination")
    found = [r for r in rows if query.casefold() in r["definition_id"].casefold()]
    if inventory()[2] != snapshot or settings != get_settings():
        raise ToolSafetyError("Catalog changed during search")
    return {"status": "found" if found else "unresolved", "catalog_snapshot_id": snapshot,
            "definition_set_sha256": snapshot, "results": found[offset:offset+limit], "total": len(found),
            "next_offset": offset+limit if offset+limit < len(found) else None,
            "source_type": "installed_definition", "evidence_level": "direct" if found else "unknown",
            "sdk_imported": False, "live_calls_made": False}


def get_component_schema(component_type: str, definition_id: str | None = None,
                          parameters: dict[str, str] | None = None, context: str = "subsystem:0",
                          snapshot_id: str | None = None) -> dict[str, Any]:
    """Read definition parameters/selectors and active ports under explicit parameter values."""
    if not isinstance(component_type, str) or not 1 <= len(component_type) <= 200:
        raise ToolSafetyError("component_type must have 1–200 characters")
    if not isinstance(context, str) or not 1 <= len(context) <= 500:
        raise ToolSafetyError("Invalid component context")
    result = resolve_schema(component_type, definition_id, parameters, context)
    if snapshot_id is not None and result["catalog_snapshot_id"] != snapshot_id:
        raise ToolSafetyError("Catalog snapshot changed")
    return result

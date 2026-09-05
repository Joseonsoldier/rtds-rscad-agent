"""Static, non-mutating RSCAD project tools."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from rtds_agent.safety import (
    ToolSafetyError,
    resolve_rtfx_path,
    sha256_file,
)



from rtds_agent.core import topology_parser, companion_dependencies
from rtds_agent.core.topology_parser import parse_rtfx_topology, DefinitionIndex, read_rtfx_dfx, parse_dfx_components
from rtds_agent.core.companion_dependencies import discover_companion_dependencies, CompanionDiscoveryError
from rtds_agent.settings import get_settings, within
from rtds_agent.core.static_comparison import topology_signature


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _snapshot_evidence(target: Path) -> dict[str, Any]:
    """Fresh content evidence; deliberately no mtime/size parse cache."""
    settings = get_settings()
    project_hash = sha256_file(target)
    _, text, _ = read_rtfx_dfx(target)
    types = sorted({item["component_type"] for item in parse_dfx_components(text)})
    index = DefinitionIndex(settings.definition_root)
    definitions = {}
    for kind in types:
        definition, error = index.resolve(kind)
        if error:
            definitions[kind] = {"status": "unresolved", "reason": error}
        else:
            definitions[kind] = {"status": "resolved", "path": str(definition.resolve()), "sha256": sha256_file(definition)}
    try:
        discovery = discover_companion_dependencies(target, settings.definition_root, search_root=target.parent)
        companions = {key: discovery[key] for key in ("status", "discovery_sha256", "files", "missing", "blocked", "definition_errors")}
    except CompanionDiscoveryError as error:
        companions = {"status": "unsupported", "reason": str(error)}
    return {"project_path": str(target), "project_sha256": project_hash,
            "definitions": definitions, "companions": companions,
            "parser": {"snapshot_schema_version": 1,
                       "topology_parser_sha256": sha256_file(Path(topology_parser.__file__)),
                       "companion_parser_sha256": sha256_file(Path(companion_dependencies.__file__)),
                       "snapshot_implementation_sha256": sha256_file(Path(__file__))}}


def _document(project_path: str, snapshot_id: str | None = None) -> tuple[Path, str, dict[str, Any]]:
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or len(snapshot_id) != 64
                                    or any(c not in "0123456789abcdef" for c in snapshot_id)):
        raise ToolSafetyError("snapshot_id must be a lowercase SHA-256 identifier")
    target, scope = resolve_rtfx_path(project_path)
    evidence = _snapshot_evidence(target)
    document = parse_rtfx_topology(target, get_settings().definition_root).document
    if _snapshot_evidence(target) != evidence or document["source"]["rtfx_sha256"] != evidence["project_sha256"]:
        raise ToolSafetyError("Project, companion, definition or parser changed during snapshot observation")
    identifier = _digest(evidence)
    if snapshot_id is not None and snapshot_id != identifier:
        raise ToolSafetyError("Snapshot changed; restart pagination or re-inspect the project")
    identities = Counter((item["context"], item["uuid"]) for item in document["components"])
    document["snapshot_id"] = identifier
    document["source"]["snapshot_id"] = identifier
    document["snapshot"] = {"snapshot_id": identifier, "evidence": evidence, "cache": "disabled_fresh_hash_validation",
                            "evidence_level": "static_source_observation", "runtime_observed": False,
                            "parser_coverage": document["coverage"], "warnings": document["warnings"],
                            "limitations": document["limitations"],
                            "identity_ambiguities": [{"context": key[0], "uuid": key[1], "count": count}
                                                     for key, count in sorted(identities.items()) if count > 1]}
    for item in document["components"]:
        identity = {"context": item["context"], "uuid": item["uuid"]}
        item["component_key"] = _digest({"snapshot_id": identifier, **identity})
        item["comparison_identity"] = identity
        item["identity_status"] = "ambiguous" if identities[(item["context"], item["uuid"])] > 1 else "exact"
        item["parameter_origins"] = {name: "stored" for name in item["parameters"]}
    for net in document["nets"]:
        for member in net["members"]:
            member["component_key"] = _digest({"snapshot_id": identifier, "context": member["context"], "uuid": member["component_id"]})
    return target, scope, document


def _pagination(total: int, limit: int, offset: int, snapshot_id: str | None) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")
    if type(offset) is not int or offset < 0:
        raise ToolSafetyError("offset must be a non-negative integer")
    if offset and snapshot_id is None:
        raise ToolSafetyError("snapshot_id is required when offset is nonzero")
    returned = max(0, min(limit, total - offset))
    return {"offset": offset, "limit": limit, "next_offset": offset + returned if offset + returned < total else None}


def _snapshot_metadata(document: dict[str, Any]) -> dict[str, Any]:
    return {"snapshot_id": document["snapshot_id"], "snapshot": document["snapshot"],
            "source_type": "current_project", "evidence_level": "derived",
            "evidence_scope": "static parse; parameter_origins distinguish stored values from definition defaults"}


def _type_counts(document: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(
        str(item["component_type"])
        for item in document["components"]
    ).items()))


def _published_copy(candidate: Path, root: Path) -> dict[str, Any] | None:
    """Recognize a completed publication at any depth, bound to this exact file."""
    working = next((parent for parent in candidate.parents if parent.name == "working" and within(parent, root)), None)
    if working is None:
        return None
    run = working.parent
    for name in ("workflow.json", "structured_parameter_patch.json"):
        marker = run / name
        if marker.is_symlink() or not within(marker, run) or not marker.is_file() or marker.stat().st_size > 20 * 1024 * 1024:
            continue
        try:
            raw = marker.read_bytes()
            manifest = json.loads(raw)
            if name == "workflow.json":
                if manifest.get("evidence", {}).get("static_validation", {}).get("passed") is not True:
                    continue
                record = manifest["project"]
                bound_path, bound_hash = record["working_copy"], record["working_sha256"]
                kind = "workflow"
            else:
                if manifest.get("status") != "completed":
                    continue
                record = manifest["working"]
                bound_path, bound_hash = record["path"], record["sha256"]
                kind = "parameter_patch"
            if not isinstance(bound_path, str) or Path(bound_path).resolve() != candidate.resolve() or bound_hash != sha256_file(candidate):
                continue
            if marker.read_bytes() != raw:
                raise ToolSafetyError("Publication marker changed during listing")
            return {"kind": kind, "manifest_path": str(marker.resolve()), "manifest_sha256": hashlib.sha256(raw).hexdigest()}
        except (KeyError, TypeError, AttributeError, ValueError, OSError):
            continue
    return None


def list_rscad_projects(limit: int = 100, offset: int = 0, source_root: str | None = None,
                        snapshot_id: str | None = None) -> dict[str, Any]:
    """List published working copies, or one explicitly selected configured source root."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")
    settings = get_settings()
    root = settings.projects_root
    scope = "agent_working_copy"
    if source_root is not None:
        if not isinstance(source_root, str) or not Path(source_root).is_absolute():
            raise ToolSafetyError("source_root must name an absolute configured source root")
        root = Path(source_root).resolve()
        if root not in {candidate.resolve() for candidate in settings.source_roots}:
            raise ToolSafetyError("source_root is not an explicitly configured source root")
        scope = "source_read_only"
    paths = []
    publications = {}
    for candidate in root.rglob("*.rtfx"):
        if candidate.is_symlink() or not candidate.is_file() or not within(candidate, root):
            continue
        # Partial workflow setup and hidden staging artifacts are never projects.
        relative = candidate.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if scope == "agent_working_copy":
            publication = _published_copy(candidate, root)
            if publication is None:
                continue
            publications[candidate.resolve()] = publication
        paths.append(candidate.resolve())
    paths = sorted(set(paths))
    inventory = [{"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size, "publication": publications.get(p)} for p in paths]
    identifier = _digest({"root": str(root.resolve()), "scope": scope, "projects": inventory})
    if snapshot_id is not None and snapshot_id != identifier:
        raise ToolSafetyError("Project listing snapshot changed; restart pagination")
    page = _pagination(len(inventory), limit, offset, snapshot_id)
    projects = []
    for item in inventory[offset:offset + limit]:
        path = Path(item["path"])
        publication = item["publication"]
        projects.append({**item, "access_scope": scope, "source_read_only": scope == "source_read_only",
                         "latest_workflow": publication["manifest_path"] if publication and publication["kind"] == "workflow" else None})
    after = [{"path": str(p), "sha256": sha256_file(p), "bytes": p.stat().st_size,
              "publication": _published_copy(p, root) if scope == "agent_working_copy" else None} for p in paths]
    if after != inventory:
        raise ToolSafetyError("Project changed during listing")
    return {"projects_root": str(root), "access_scope": scope, "count": len(projects), "total_count": len(inventory),
            "snapshot_id": identifier, **page, "truncated": page["next_offset"] is not None,
            "projects": projects, "mutations_performed": False, "live_rscad_connection_opened": False}


def inspect_rscad_project(project_path: str, snapshot_id: str | None = None) -> dict[str, Any]:
    """Return a bounded static overview of one RTFX file."""
    target, scope, document = _document(project_path, snapshot_id)
    contexts = sorted({
        str(item["context"])
        for item in document["components"]
    })
    return {
        "status": document["status"],
        "access_scope": scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        "coverage": document["coverage"],
        "component_type_counts": _type_counts(document),
        "contexts": contexts,
        "hierarchy_links": document["hierarchy_links"],
        "warnings": document["warnings"],
        "limitations": document["limitations"],
        "source_hash_rechecked": sha256_file(target),
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
    }


def get_project_hierarchy(project_path: str, limit: int = 100, offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """Describe subsystem and hierarchy contexts from static RTFX content."""
    _pagination(0, limit, offset, snapshot_id)
    _, scope, document = _document(project_path, snapshot_id)
    rows: list[dict[str, Any]] = []
    for context in sorted({item["context"] for item in document["components"]}):
        components = [
            item for item in document["components"]
            if item["context"] == context
        ]
        rows.append({
            "context": context,
            "component_count": len(components),
            "component_types": dict(sorted(Counter(
                item["component_type"] for item in components
            ).items())),
        })
    return {
        "access_scope": scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        **_pagination(len(rows), limit, offset, snapshot_id),
        "contexts": rows[offset:offset + limit],
        "context_count": len(rows),
        "hierarchy_links": document["hierarchy_links"],
        "mutations_performed": False,
    }


def get_component_graph(
    project_path: str,
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0, snapshot_id: str | None = None, member_offset: int = 0, member_limit: int = 50) -> dict[str, Any]:
    """Return bounded static net records, optionally restricted to a hierarchy context."""
    _pagination(0, limit, offset, snapshot_id)
    _pagination(0, member_limit, member_offset, snapshot_id)
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")
    _, access_scope, document = _document(project_path, snapshot_id)
    nets = document["nets"]
    if scope:
        needle = scope.casefold()
        nets = [
            net for net in nets
            if any(needle in str(context).casefold() for context in net["contexts"])
        ]
    selected = []
    for net in nets[offset:offset + limit]:
        members = []
        for item in net["members"][member_offset:member_offset + member_limit]:
            members.append({
                key: item.get(key)
                for key in (
                    "atom",
                    "component_id",
                    "component_key",
                    "component_type",
                    "context",
                    "port",
                    "domain",
                    "phase",
                    "start",
                    "end",
                )
                if key in item
            })
        selected.append({
            "net_id": net["net_id"],
            "contexts": net["contexts"],
            "cross_context": net["cross_context"],
            "domain": net["domain"],
            "port_count": net["port_count"],
            "segment_count": net["segment_count"],
            "members": members,
            "members_truncated": len(net["members"]) > member_offset + member_limit,
            "member_count": len(net["members"]),
            "member_pagination": _pagination(len(net["members"]), member_limit, member_offset, snapshot_id),
        })
    return {
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        **_pagination(len(nets), limit, offset, snapshot_id),
        "source": document["source"],
        "scope_filter": scope,
        "total_matching_nets": len(nets),
        "returned_nets": len(selected),
        "truncated": len(nets) > offset + limit,
        "nets": selected,
        "mutations_performed": False,
    }


def find_components(
    project_path: str,
    query: str,
    limit: int = 50,
    offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """Find components by type, context, parameter name, or parameter value."""
    _pagination(0, limit, offset, snapshot_id)
    if not isinstance(query, str) or not query.strip():
        raise ToolSafetyError("query must be a non-empty string")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ToolSafetyError("limit must be an integer from 1 through 200")
    _, access_scope, document = _document(project_path, snapshot_id)
    needle = query.strip().casefold()
    matches: list[dict[str, Any]] = []
    for item in document["components"]:
        haystack = " ".join([
            str(item["component_type"]),
            str(item["context"]),
            json.dumps(item["parameters"], ensure_ascii=False),
        ]).casefold()
        if needle in haystack:
            matches.append(item)
    return {
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        **_pagination(len(matches), limit, offset, snapshot_id),
        "source": document["source"],
        "query": query,
        "match_count": len(matches),
        "returned_count": len(matches[offset:offset + limit]),
        "truncated": len(matches) > offset + limit,
        "components": matches[offset:offset + limit],
        "mutations_performed": False,
    }


def get_component(
    project_path: str,
    component_id: int,
    context: str | None = None,
    snapshot_id: str | None = None, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    """Get one or more component records matching an RSCAD UUID."""
    _pagination(0, limit, offset, snapshot_id)
    if type(component_id) is not int:
        raise ToolSafetyError("component_id must be an integer")
    _, access_scope, document = _document(project_path, snapshot_id)
    matches = [
        item for item in document["components"]
        if int(item["uuid"]) == component_id
        and (context is None or item["context"] == context)
    ]
    return {
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        "component_id": component_id,
        "context_filter": context,
        "match_count": len(matches),
        "ambiguous_without_context": context is None and len(matches) > 1,
        **_pagination(len(matches), limit, offset, snapshot_id),
        "components": matches[offset:offset + limit],
        "mutations_performed": False,
    }


def list_components(
    project_path: str,
    scope: str | None = None,
    component_type: str | None = None,
    limit: int = 100,
    offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """List bounded component summaries with optional exact context and type filters."""
    _pagination(0, limit, offset, snapshot_id)
    if scope is not None and (
        not isinstance(scope, str) or not scope.strip() or len(scope) > 500
    ):
        raise ToolSafetyError("scope must be null or a non-empty string up to 500 characters")
    if component_type is not None and (
        not isinstance(component_type, str)
        or not component_type.strip()
        or len(component_type) > 300
    ):
        raise ToolSafetyError(
            "component_type must be null or a non-empty string up to 300 characters"
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    target, access_scope, document = _document(project_path, snapshot_id)
    expected_hash = document["source"]["rtfx_sha256"]
    current_hash = sha256_file(target)
    if current_hash != expected_hash:
        raise ToolSafetyError("project hash changed during component listing")
    type_filter = component_type.strip().casefold() if component_type else None
    rows = [
        item
        for item in document["components"]
        if (scope is None or item["context"] == scope)
        and (
            type_filter is None
            or str(item["component_type"]).casefold() == type_filter
        )
    ]
    rows.sort(key=lambda item: (
        str(item["context"]),
        int(item["uuid"]),
        str(item["component_type"]),
    ))
    selected = [{
        "component_id": item["uuid"],
        "component_key": item["component_key"],
        "comparison_identity": item["comparison_identity"],
        "identity_status": item["identity_status"],
        "component_type": item["component_type"],
        "context": item["context"],
        "location": item["location"],
        "orientation": item["orientation"],
        "mirrored": item["mirrored"],
        "parameter_count": len(item["parameters"]),
        "parameter_names": sorted(item["parameters"], key=str.casefold),
    } for item in rows[offset:offset + limit]]
    return {
        "status": "completed",
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        **_pagination(len(rows), limit, offset, snapshot_id),
        "source": document["source"],
        "scope_filter": scope,
        "component_type_filter": component_type.strip() if component_type else None,
        "component_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > offset + limit,
        "components": selected,
        "source_hash_rechecked": current_hash,
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }


def get_component_parameters(
    project_path: str,
    component_id: int,
    context: str | None = None,
    snapshot_id: str | None = None) -> dict[str, Any]:
    """Return an exact component's active static parameter dictionary."""
    if not isinstance(component_id, int) or isinstance(component_id, bool):
        raise ToolSafetyError("component_id must be an integer")
    if context is not None and (
        not isinstance(context, str) or not context.strip() or len(context) > 500
    ):
        raise ToolSafetyError("context must be null or a non-empty string up to 500 characters")

    target, access_scope, document = _document(project_path, snapshot_id)
    expected_hash = document["source"]["rtfx_sha256"]
    current_hash = sha256_file(target)
    if current_hash != expected_hash:
        raise ToolSafetyError("project hash changed during component-parameter read")
    matches = [
        item
        for item in document["components"]
        if int(item["uuid"]) == component_id
        and (context is None or item["context"] == context)
    ]
    base = {
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        "component_id": component_id,
        "context_filter": context,
        "match_count": len(matches),
        "source_hash_rechecked": current_hash,
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }
    if not matches:
        return {**base, "status": "not_found", "component": None}
    if len(matches) != 1:
        return {
            **base,
            "status": "ambiguous",
            "candidate_contexts": sorted(item["context"] for item in matches),
            "component": None,
        }
    item = matches[0]
    return {
        **base,
        "status": "completed",
        "component": {
            "component_id": item["uuid"],
            "component_type": item["component_type"],
            "context": item["context"],
            "declared_parameter_count": item["declared_parameter_count"],
            "parsed_parameter_count": item["parsed_parameter_count"],
            "parameters": dict(item["parameters"]),
            "parameter_origins": dict(item["parameter_origins"]),
            "component_key": item["component_key"],
            "comparison_identity": item["comparison_identity"],
        },
        "limitations": [
            "Only active parameters emitted by the static parser are returned.",
            "No project write, Compile, Runtime, or hardware operation is performed.",
        ],
    }


def find_project_parameters(
    project_path: str,
    query: str,
    scope: str | None = None,
    component_type: str | None = None,
    limit: int = 100,
    offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """Find static project parameter names or values by case-insensitive substring."""
    _pagination(0, limit, offset, snapshot_id)
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ToolSafetyError("query must be a non-empty string up to 300 characters")
    if scope is not None and (
        not isinstance(scope, str) or not scope.strip() or len(scope) > 500
    ):
        raise ToolSafetyError("scope must be null or a non-empty string up to 500 characters")
    if component_type is not None and (
        not isinstance(component_type, str)
        or not component_type.strip()
        or len(component_type) > 300
    ):
        raise ToolSafetyError(
            "component_type must be null or a non-empty string up to 300 characters"
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    target, access_scope, document = _document(project_path, snapshot_id)
    expected_hash = document["source"]["rtfx_sha256"]
    current_hash = sha256_file(target)
    if current_hash != expected_hash:
        raise ToolSafetyError("project hash changed during project-parameter search")
    needle = query.strip().casefold()
    type_filter = component_type.strip().casefold() if component_type else None
    rows: list[dict[str, Any]] = []
    for item in document["components"]:
        if scope is not None and item["context"] != scope:
            continue
        if (
            type_filter is not None
            and str(item["component_type"]).casefold() != type_filter
        ):
            continue
        for name, value in item["parameters"].items():
            if needle not in f"{name} {value}".casefold():
                continue
            rows.append({
                "component_id": item["uuid"],
                "component_type": item["component_type"],
                "context": item["context"],
                "parameter": name,
                "parameter_origin": "stored",
                "component_key": item["component_key"],
                "value": value,
                "name_matched": needle in str(name).casefold(),
                "value_matched": needle in str(value).casefold(),
            })
    rows.sort(key=lambda item: (
        str(item["context"]),
        int(item["component_id"]),
        str(item["parameter"]).casefold(),
    ))
    selected = rows[offset:offset + limit]
    return {
        "status": "completed",
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        **_pagination(len(rows), limit, offset, snapshot_id),
        "source": document["source"],
        "query": query.strip(),
        "scope_filter": scope,
        "component_type_filter": component_type.strip() if component_type else None,
        "match_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > offset + limit,
        "parameters": selected,
        "source_hash_rechecked": current_hash,
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }


def trace_signal(
    project_path: str,
    component_id: int,
    port: str,
    context: str | None = None,
    limit: int = 100,
    offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """Trace one exact component port to its statically connected net endpoints."""
    _pagination(0, limit, offset, snapshot_id)
    if not isinstance(component_id, int) or isinstance(component_id, bool):
        raise ToolSafetyError("component_id must be an integer")
    if not isinstance(port, str) or not port.strip() or len(port) > 200:
        raise ToolSafetyError("port must be a non-empty string up to 200 characters")
    if context is not None and (
        not isinstance(context, str) or not context.strip() or len(context) > 500
    ):
        raise ToolSafetyError("context must be null or a non-empty string up to 500 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
        raise ToolSafetyError("limit must be an integer from 1 through 200")

    target, access_scope, document = _document(project_path, snapshot_id)
    expected_hash = document["source"]["rtfx_sha256"]
    current_hash = sha256_file(target)
    if current_hash != expected_hash:
        raise ToolSafetyError("project hash changed during static signal trace")

    needle = port.strip().casefold()
    seed_ports = [
        item
        for item in document["ports"]
        if int(item["component_id"]) == component_id
        and str(item["port"]).casefold() == needle
        and (context is None or item["context"] == context)
    ]
    base = {
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        "seed": {
            "component_id": component_id,
            "port": port.strip(),
            "context_filter": context,
        },
        "source_hash_rechecked": current_hash,
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }
    if not seed_ports:
        return {
            **base,
            "status": "not_found",
            "matched_seed_count": 0,
            "trace": None,
        }

    atom_to_net = {
        member["atom"]: net
        for net in document["nets"]
        for member in net["members"]
    }
    matched_nets = {
        atom_to_net[item["atom"]]["net_id"]: atom_to_net[item["atom"]]
        for item in seed_ports
        if item["atom"] in atom_to_net
    }
    if len(matched_nets) != 1:
        return {
            **base,
            "status": "ambiguous",
            "matched_seed_count": len(seed_ports),
            "candidate_nets": sorted(matched_nets),
            "trace": None,
        }

    net = next(iter(matched_nets.values()))
    port_members = [
        item for item in net["members"]
        if str(item["atom"]).startswith("port:")
    ]
    endpoint_fields = (
        "atom",
        "component_id",
        "component_key",
        "component_type",
        "context",
        "port",
        "coordinate",
        "domain",
        "phase",
        "kind",
        "direction",
        "data_type",
        "connected_name",
        "connected_mode",
        "link_by_name",
    )
    endpoints = [
        {key: item.get(key) for key in endpoint_fields}
        for item in port_members
    ]
    returned = endpoints[offset:offset + limit]

    def role(direction: Any, domain: Any) -> str:
        if str(domain).startswith("bus3:"):
            return "undirected"
        normalized = str(direction).upper() if direction is not None else ""
        if normalized == "OUTPUT":
            return "source"
        if normalized == "INPUT":
            return "sink"
        if normalized == "I/O":
            return "bidirectional"
        return "undirected"

    for endpoint in returned:
        endpoint["trace_role"] = role(endpoint.get("direction"), endpoint.get("domain"))
    roles = {
        name: [item for item in returned if item["trace_role"] == name]
        for name in ("source", "sink", "bidirectional", "undirected")
    }
    known_direction_count = sum(
        role(item.get("direction"), item.get("domain")) != "undirected" for item in endpoints
    )
    signal_labels = sorted({
        str(item["connected_name"])
        for item in port_members
        if item.get("connected_name")
    })
    return {
        **base,
        "status": "completed",
        "matched_seed_count": len(seed_ports),
        **_pagination(len(endpoints), limit, offset, snapshot_id),
        "trace": {
            "net_id": net["net_id"],
            "contexts": net["contexts"],
            "cross_context": net["cross_context"],
            "domain": net["domain"],
            "signal_labels": signal_labels,
            "endpoint_count": len(endpoints),
            "returned_endpoint_count": len(returned),
            "endpoints_truncated": len(endpoints) > offset + limit,
            "sources": roles["source"],
            "sinks": roles["sink"],
            "bidirectional": roles["bidirectional"],
            "undirected": roles["undirected"],
            "segment_count": net["segment_count"],
        },
        "direction_evidence": {
            "basis": "installed component definition node Direction fields",
            "trace_scope": "same_net_endpoints_only",
            "known_endpoint_count": known_direction_count,
            "unknown_endpoint_count": len(endpoints) - known_direction_count,
            "complete": known_direction_count == len(endpoints),
            "power_flow_inferred": False,
        },
        "limitations": [
            *document["limitations"],
            "Source and sink roles are reported only from explicit INPUT/OUTPUT/I/O definition metadata.",
            "Electrical phase ports remain undirected; definition metadata is not inferred power flow.",
        ],
    }


def find_unconnected_ports(
    project_path: str,
    scope: str | None = None,
    limit: int = 100,
    offset: int = 0, snapshot_id: str | None = None) -> dict[str, Any]:
    """Find active ports that occupy a singleton static net with no wire segment."""
    _pagination(0, limit, offset, snapshot_id)
    if scope is not None and (
        not isinstance(scope, str) or not scope.strip() or len(scope) > 500
    ):
        raise ToolSafetyError("scope must be null or a non-empty string up to 500 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    target, access_scope, document = _document(project_path, snapshot_id)
    expected_hash = document["source"]["rtfx_sha256"]
    current_hash = sha256_file(target)
    if current_hash != expected_hash:
        raise ToolSafetyError("project hash changed during unconnected-port scan")

    rows: list[dict[str, Any]] = []
    for net in document["nets"]:
        port_members = [
            item
            for item in net["members"]
            if str(item["atom"]).startswith("port:")
        ]
        if len(port_members) != 1 or int(net["segment_count"]) != 0:
            continue
        port = port_members[0]
        if scope is not None and port["context"] != scope:
            continue
        rows.append({
            "net_id": net["net_id"],
            "context": port["context"],
            "component_id": port["component_id"],
            "component_key": port["component_key"],
            "component_type": port["component_type"],
            "port": port["port"],
            "coordinate": port.get("coordinate"),
            "domain": port.get("domain"),
            "phase": port.get("phase"),
            "kind": port.get("kind"),
            "direction": port.get("direction"),
            "data_type": port.get("data_type"),
            "reason": "singleton_net_without_wire_segment",
        })
    rows.sort(key=lambda item: (
        str(item["context"]),
        int(item["component_id"]),
        str(item["port"]),
        str(item["net_id"]),
    ))
    selected = rows[offset:offset + limit]
    return {
        "status": "completed",
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        **_pagination(len(rows), limit, offset, snapshot_id),
        "source": document["source"],
        "scope_filter": scope,
        "unconnected_port_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > offset + limit,
        "ports": selected,
        "definition_coverage": document["coverage"]["definition_coverage"],
        "source_hash_rechecked": current_hash,
        "limitations": [
            *document["limitations"],
            "Only active ports on singleton nets with zero parsed wire segments are classified as unconnected.",
            "A port attached to a dangling wire segment is outside this conservative result set.",
        ],
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }


def compare_component_settings(
    project_a: str,
    project_b: str,
    component_id: int,
    context: str | None = None,
    snapshot_id_a: str | None = None, snapshot_id_b: str | None = None) -> dict[str, Any]:
    """Compare exact parameter dictionaries for one component UUID across two RTFX files."""
    if not isinstance(component_id, int) or isinstance(component_id, bool):
        raise ToolSafetyError("component_id must be an integer")
    if context is not None and (
        not isinstance(context, str) or not context.strip() or len(context) > 500
    ):
        raise ToolSafetyError("context must be null or a non-empty string up to 500 characters")

    path_a, scope_a, first = _document(project_a, snapshot_id_a)
    path_b, scope_b, second = _document(project_b, snapshot_id_b)
    hash_a = sha256_file(path_a)
    hash_b = sha256_file(path_b)
    if hash_a != first["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_a hash changed during component comparison")
    if hash_b != second["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_b hash changed during component comparison")

    def matches(document: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in document["components"]
            if int(item["uuid"]) == component_id
            and (context is None or item["context"] == context)
        ]

    first_matches = matches(first)
    second_matches = matches(second)
    base = {
        "project_a": {
            "access_scope": scope_a,
            **_snapshot_metadata(first),
            "source": first["source"],
            "source_hash_rechecked": hash_a,
        },
        "project_b": {
            "access_scope": scope_b,
            **_snapshot_metadata(second),
            "source": second["source"],
            "source_hash_rechecked": hash_b,
        },
        "component_id": component_id,
        "context_filter": context,
        "project_a_match_count": len(first_matches),
        "project_b_match_count": len(second_matches),
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }
    if not first_matches or not second_matches:
        missing = []
        if not first_matches:
            missing.append("project_a")
        if not second_matches:
            missing.append("project_b")
        return {
            **base,
            "status": "not_found",
            "missing_from": missing,
            "comparison": None,
        }
    if len(first_matches) != 1 or len(second_matches) != 1:
        return {
            **base,
            "status": "ambiguous",
            "project_a_contexts": sorted(item["context"] for item in first_matches),
            "project_b_contexts": sorted(item["context"] for item in second_matches),
            "comparison": None,
        }

    left = first_matches[0]
    right = second_matches[0]
    parameters_a = left["parameters"]
    parameters_b = right["parameters"]
    keys = sorted(parameters_a.keys() | parameters_b.keys(), key=str.casefold)
    changes = []
    unchanged = 0
    for name in keys:
        present_a = name in parameters_a
        present_b = name in parameters_b
        value_a = parameters_a.get(name)
        value_b = parameters_b.get(name)
        if present_a and present_b and value_a == value_b:
            unchanged += 1
            continue
        if not present_a:
            change_kind = "added_in_project_b"
        elif not present_b:
            change_kind = "removed_from_project_b"
        else:
            change_kind = "value_changed"
        changes.append({
            "parameter": name,
            "project_a_value": value_a,
            "project_b_value": value_b,
            "change_kind": change_kind,
        })
    return {
        **base,
        "status": "completed",
        "comparison": {
            "project_a_component": {
                "uuid": left["uuid"],
                "component_key": left["component_key"],
                "comparison_identity": left["comparison_identity"],
                "context": left["context"],
                "component_type": left["component_type"],
            },
            "project_b_component": {
                "uuid": right["uuid"],
                "component_key": right["component_key"],
                "comparison_identity": right["comparison_identity"],
                "context": right["context"],
                "component_type": right["component_type"],
            },
            "same_component_type": left["component_type"] == right["component_type"],
            "same_context": left["context"] == right["context"],
            "same_parameters": not changes,
            "parameter_count_a": len(parameters_a),
            "parameter_count_b": len(parameters_b),
            "unchanged_parameter_count": unchanged,
            "changed_parameter_count": len(changes),
            "parameter_changes": changes,
        },
        "limitations": [
            "Comparison is limited to active parameter dictionaries emitted by the static parser.",
            "Component equivalence is based on exact UUID and optional exact context; semantic replacement is not inferred.",
            "No project write, Compile, Runtime, or hardware operation is performed.",
        ],
    }


def compare_project_versions(
    project_a: str,
    project_b: str,
    limit: int = 100,
    offset: int = 0, snapshot_id_a: str | None = None, snapshot_id_b: str | None = None) -> dict[str, Any]:
    """Compare static project settings, component identities, parameters, and net signatures."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    _pagination(0, limit, offset, snapshot_id_a)
    _pagination(0, limit, offset, snapshot_id_b)
    path_a, scope_a, first = _document(project_a, snapshot_id_a)
    path_b, scope_b, second = _document(project_b, snapshot_id_b)
    hash_a = sha256_file(path_a)
    hash_b = sha256_file(path_b)
    if hash_a != first["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_a hash changed during project-version comparison")
    if hash_b != second["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_b hash changed during project-version comparison")

    if first["snapshot"]["identity_ambiguities"] or second["snapshot"]["identity_ambiguities"]:
        return {"status": "ambiguous", "reason": "Duplicate context and UUID prevents a unique comparison identity",
                "project_a": {**_snapshot_metadata(first), "source": first["source"]},
                "project_b": {**_snapshot_metadata(second), "source": second["source"]},
                "comparison": None, "mutations_performed": False, "live_rscad_connection_opened": False,
                "rack_query_called": False, "compile_called": False, "runtime_or_hardware_called": False}

    def component_map(document: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
        result: dict[tuple[str, int], dict[str, Any]] = {}
        for item in document["components"]:
            key = (str(item["context"]), int(item["uuid"]))
            if key in result:
                raise ToolSafetyError(
                    "duplicate component UUID within one context prevents deterministic comparison"
                )
            result[key] = item
        return result

    def parameter_delta(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        keys = sorted(left.keys() | right.keys(), key=str.casefold)
        for name in keys:
            present_a = name in left
            present_b = name in right
            value_a = left.get(name)
            value_b = right.get(name)
            if present_a and present_b and value_a == value_b:
                continue
            if not present_a:
                kind = "added_in_project_b"
            elif not present_b:
                kind = "removed_from_project_b"
            else:
                kind = "value_changed"
            rows.append({
                "parameter": name,
                "project_a_value": value_a,
                "project_b_value": value_b,
                "change_kind": kind,
            })
        return rows

    components_a = component_map(first)
    components_b = component_map(second)
    component_changes: list[dict[str, Any]] = []
    for key in sorted(components_a.keys() | components_b.keys()):
        left = components_a.get(key)
        right = components_b.get(key)
        context_value, uuid_value = key
        if left is None:
            component_changes.append({
                "change_kind": "component_added",
                "context": context_value,
                "component_id": uuid_value,
                "project_a_type": None,
                "project_b_type": right["component_type"],
                "parameter_changes": [],
            })
            continue
        if right is None:
            component_changes.append({
                "change_kind": "component_removed",
                "context": context_value,
                "component_id": uuid_value,
                "project_a_type": left["component_type"],
                "project_b_type": None,
                "parameter_changes": [],
            })
            continue
        parameter_changes = parameter_delta(left["parameters"], right["parameters"])
        type_changed = left["component_type"] != right["component_type"]
        if type_changed or parameter_changes:
            component_changes.append({
                "change_kind": (
                    "component_type_and_parameters_changed"
                    if type_changed and parameter_changes
                    else "component_type_changed"
                    if type_changed
                    else "parameters_changed"
                ),
                "context": context_value,
                "component_id": uuid_value,
                "project_a_type": left["component_type"],
                "project_b_type": right["component_type"],
                "parameter_changes": parameter_changes,
            })

    settings_a = first["source"]["settings"]
    settings_b = second["source"]["settings"]
    setting_changes = parameter_delta(settings_a, settings_b)
    coverage_keys = sorted(first["coverage"].keys() | second["coverage"].keys())
    coverage_changes = [
        {
            "metric": key,
            "project_a_value": first["coverage"].get(key),
            "project_b_value": second["coverage"].get(key),
        }
        for key in coverage_keys
        if first["coverage"].get(key) != second["coverage"].get(key)
    ]

    signature_a = topology_signature(first)
    signature_b = topology_signature(second)
    net_counts_a = Counter(topology_signature({"nets": [net]}) for net in first["nets"])
    net_counts_b = Counter(topology_signature({"nets": [net]}) for net in second["nets"])
    topology_changes = [{"net_signature_sha256": key, "project_a_count": net_counts_a[key], "project_b_count": net_counts_b[key]}
                        for key in sorted(net_counts_a.keys() | net_counts_b.keys()) if net_counts_a[key] != net_counts_b[key]]
    selected = component_changes[offset:offset + limit]
    return {
        "status": "completed",
        "project_a": {
            "access_scope": scope_a,
            **_snapshot_metadata(first),
            "source": first["source"],
            "source_hash_rechecked": hash_a,
            "topology_signature_sha256": signature_a,
        },
        "project_b": {
            "access_scope": scope_b,
            **_snapshot_metadata(second),
            "source": second["source"],
            "source_hash_rechecked": hash_b,
            "topology_signature_sha256": signature_b,
        },
        "same_rtfx_sha256": hash_a == hash_b,
        "same_static_topology": signature_a == signature_b,
        "comparison_identity_basis": "exact_context_and_uuid",
        "same_definition_evidence": first["snapshot"]["evidence"]["definitions"] == second["snapshot"]["evidence"]["definitions"],
        "topology_change_count": len(topology_changes),
        "topology_changes": topology_changes[offset:offset + limit],
        "topology_pagination": _pagination(len(topology_changes), limit, offset, snapshot_id_a),
        "project_setting_changes": setting_changes,
        "coverage_changes": coverage_changes,
        "component_change_count": len(component_changes),
        "returned_component_change_count": len(selected),
        **_pagination(max(len(component_changes), len(topology_changes)), limit, offset, snapshot_id_a),
        "component_changes_truncated": len(component_changes) > offset + limit,
        "component_changes": selected,
        "limitations": [
            "Version comparison uses active static parser output and exact context plus UUID identity.",
            "Topology equality is a normalized parsed-net signature, not a Compile or Runtime equivalence claim.",
            "Net numbering and stored record order are ignored; explicit wire endpoint geometry remains part of the static signature.",
            "No project write, Compile, Runtime, or hardware operation is performed.",
        ],
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }


def validate_project(project_path: str, snapshot_id: str | None = None) -> dict[str, Any]:
    """Reparse and validate static topology while proving the RTFX hash is unchanged."""
    target, access_scope = resolve_rtfx_path(project_path)
    before = sha256_file(target)
    _, _, document = _document(project_path, snapshot_id)
    after = sha256_file(target)
    coverage = document["coverage"]
    checks = {
        "source_hash_unchanged": before == after,
        "parser_declares_no_mutation": document["mutations_performed"] is False,
        "all_component_definitions_resolved": (
            coverage["definition_coverage"] == 1.0
        ),
        "no_parser_warnings": coverage["warning_count"] == 0,
        "every_port_accounted_for": (
            sum(net["port_count"] for net in document["nets"])
            == coverage["port_count"]
        ),
        "every_segment_accounted_for": (
            sum(net["segment_count"] for net in document["nets"])
            == coverage["segment_count"]
        ),
    }
    return {
        "status": "passed" if all(checks.values()) else "needs_review",
        "passed": all(checks.values()),
        "access_scope": access_scope,
        **_snapshot_metadata(document),
        "source": document["source"],
        "hash_before": before,
        "hash_after": after,
        "checks": checks,
        "coverage": coverage,
        "warnings": document["warnings"],
        "limitations": document["limitations"],
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
    }


def compare_projects(project_a: str, project_b: str, snapshot_id_a: str | None = None, snapshot_id_b: str | None = None) -> dict[str, Any]:
    """Compare two RTFX files using static structure and component-type counts."""
    _, scope_a, first = _document(project_a, snapshot_id_a)
    _, scope_b, second = _document(project_b, snapshot_id_b)
    first_counts = Counter(item["component_type"] for item in first["components"])
    second_counts = Counter(item["component_type"] for item in second["components"])
    keys = sorted(first_counts.keys() | second_counts.keys())
    component_deltas = {
        key: second_counts[key] - first_counts[key]
        for key in keys
        if second_counts[key] != first_counts[key]
    }
    coverage_keys = sorted(first["coverage"].keys() | second["coverage"].keys())
    coverage_deltas = {
        key: (
            first["coverage"].get(key),
            second["coverage"].get(key),
        )
        for key in coverage_keys
        if first["coverage"].get(key) != second["coverage"].get(key)
    }
    return {
        "project_a": {
            "access_scope": scope_a,
            **_snapshot_metadata(first),
            "source": first["source"],
        },
        "project_b": {
            "access_scope": scope_b,
            **_snapshot_metadata(second),
            "source": second["source"],
        },
        "same_rtfx_sha256": (
            first["source"]["rtfx_sha256"]
            == second["source"]["rtfx_sha256"]
        ),
        "component_type_count_deltas_b_minus_a": component_deltas,
        "coverage_changes": coverage_deltas,
        "mutations_performed": False,
    }

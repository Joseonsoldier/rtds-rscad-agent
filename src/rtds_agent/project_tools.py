"""Static, non-mutating RSCAD project tools."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from rtds_agent.safety import (
    AGENT_ROOT,
    DEFINITION_ROOT,
    WORKING_PROJECT_ROOT,
    ToolSafetyError,
    resolve_rtfx_path,
    sha256_file,
)



from rtds_agent.core.topology_parser import parse_rtfx_topology  # noqa: E402


def _cached_document(
    path_value: str,
    modified_ns: int,
    size: int,
) -> dict[str, Any]:
    del modified_ns, size
    return parse_rtfx_topology(
        Path(path_value),
        DEFINITION_ROOT,
    ).document


def _document(project_path: str) -> tuple[Path, str, dict[str, Any]]:
    target, scope = resolve_rtfx_path(project_path)
    stat = target.stat()
    document = copy.deepcopy(
        _cached_document(str(target), stat.st_mtime_ns, stat.st_size)
    )
    return target, scope, document


def _type_counts(document: dict[str, Any]) -> dict[str, int]:
    return dict(sorted(Counter(
        str(item["component_type"])
        for item in document["components"]
    ).items()))


def list_rscad_projects(limit: int = 100) -> dict[str, Any]:
    """List agent working-copy RTFX projects and their most recent workflow evidence."""
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")
    all_paths = sorted(p for p in WORKING_PROJECT_ROOT.rglob("*.rtfx") if p.resolve().is_relative_to(WORKING_PROJECT_ROOT.resolve()))
    projects: list[dict[str, Any]] = []
    for path in all_paths[:limit]:
        workflows = sorted(
            path.parent.parent.glob("workflow*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        projects.append({
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "latest_workflow": str(workflows[0].resolve()) if workflows else None,
        })
    return {
        "projects_root": str(WORKING_PROJECT_ROOT),
        "count": len(projects),
        "limit": limit,
        "truncated": len(all_paths) > limit,
        "projects": projects,
        "mutations_performed": False,
    }


def inspect_rscad_project(project_path: str) -> dict[str, Any]:
    """Return a bounded static overview of one RTFX file."""
    target, scope, document = _document(project_path)
    contexts = sorted({
        str(item["context"])
        for item in document["components"]
    })
    return {
        "status": document["status"],
        "access_scope": scope,
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


def get_project_hierarchy(project_path: str) -> dict[str, Any]:
    """Describe subsystem and hierarchy contexts from static RTFX content."""
    _, scope, document = _document(project_path)
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
        "source": document["source"],
        "contexts": rows,
        "hierarchy_links": document["hierarchy_links"],
        "mutations_performed": False,
    }


def get_component_graph(
    project_path: str,
    scope: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Return bounded static net records, optionally restricted to a hierarchy context."""
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")
    _, access_scope, document = _document(project_path)
    nets = document["nets"]
    if scope:
        needle = scope.casefold()
        nets = [
            net for net in nets
            if any(needle in str(context).casefold() for context in net["contexts"])
        ]
    selected = []
    for net in nets[:limit]:
        members = []
        for item in net["members"][:50]:
            members.append({
                key: item.get(key)
                for key in (
                    "atom",
                    "component_id",
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
            "members_truncated": len(net["members"]) > 50,
        })
    return {
        "access_scope": access_scope,
        "source": document["source"],
        "scope_filter": scope,
        "total_matching_nets": len(nets),
        "returned_nets": len(selected),
        "truncated": len(nets) > limit,
        "nets": selected,
        "mutations_performed": False,
    }


def find_components(
    project_path: str,
    query: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Find components by type, context, parameter name, or parameter value."""
    if not isinstance(query, str) or not query.strip():
        raise ToolSafetyError("query must be a non-empty string")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ToolSafetyError("limit must be an integer from 1 through 200")
    _, access_scope, document = _document(project_path)
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
        "source": document["source"],
        "query": query,
        "match_count": len(matches),
        "returned_count": min(len(matches), limit),
        "truncated": len(matches) > limit,
        "components": matches[:limit],
        "mutations_performed": False,
    }


def get_component(
    project_path: str,
    component_id: int,
    context: str | None = None,
) -> dict[str, Any]:
    """Get one or more component records matching an RSCAD UUID."""
    if not isinstance(component_id, int):
        raise ToolSafetyError("component_id must be an integer")
    _, access_scope, document = _document(project_path)
    matches = [
        item for item in document["components"]
        if int(item["uuid"]) == component_id
        and (context is None or item["context"] == context)
    ]
    return {
        "access_scope": access_scope,
        "source": document["source"],
        "component_id": component_id,
        "context_filter": context,
        "match_count": len(matches),
        "ambiguous_without_context": context is None and len(matches) > 1,
        "components": matches,
        "mutations_performed": False,
    }


def list_components(
    project_path: str,
    scope: str | None = None,
    component_type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """List bounded component summaries with optional exact context and type filters."""
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

    target, access_scope, document = _document(project_path)
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
        "component_type": item["component_type"],
        "context": item["context"],
        "location": item["location"],
        "orientation": item["orientation"],
        "mirrored": item["mirrored"],
        "parameter_count": len(item["parameters"]),
        "parameter_names": sorted(item["parameters"], key=str.casefold),
    } for item in rows[:limit]]
    return {
        "status": "completed",
        "access_scope": access_scope,
        "source": document["source"],
        "scope_filter": scope,
        "component_type_filter": component_type.strip() if component_type else None,
        "component_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > limit,
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
) -> dict[str, Any]:
    """Return an exact component's active static parameter dictionary."""
    if not isinstance(component_id, int) or isinstance(component_id, bool):
        raise ToolSafetyError("component_id must be an integer")
    if context is not None and (
        not isinstance(context, str) or not context.strip() or len(context) > 500
    ):
        raise ToolSafetyError("context must be null or a non-empty string up to 500 characters")

    target, access_scope, document = _document(project_path)
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
) -> dict[str, Any]:
    """Find static project parameter names or values by case-insensitive substring."""
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

    target, access_scope, document = _document(project_path)
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
                "value": value,
                "name_matched": needle in str(name).casefold(),
                "value_matched": needle in str(value).casefold(),
            })
    rows.sort(key=lambda item: (
        str(item["context"]),
        int(item["component_id"]),
        str(item["parameter"]).casefold(),
    ))
    selected = rows[:limit]
    return {
        "status": "completed",
        "access_scope": access_scope,
        "source": document["source"],
        "query": query.strip(),
        "scope_filter": scope,
        "component_type_filter": component_type.strip() if component_type else None,
        "match_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > limit,
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
) -> dict[str, Any]:
    """Trace one exact component port to its statically connected net endpoints."""
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

    target, access_scope, document = _document(project_path)
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
    returned = endpoints[:limit]

    def role(direction: Any) -> str:
        normalized = str(direction).upper() if direction is not None else ""
        if normalized == "OUTPUT":
            return "source"
        if normalized == "INPUT":
            return "sink"
        if normalized == "I/O":
            return "bidirectional"
        return "undirected"

    for endpoint in returned:
        endpoint["trace_role"] = role(endpoint.get("direction"))
    roles = {
        name: [item for item in returned if item["trace_role"] == name]
        for name in ("source", "sink", "bidirectional", "undirected")
    }
    known_direction_count = sum(
        role(item.get("direction")) != "undirected" for item in endpoints
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
        "trace": {
            "net_id": net["net_id"],
            "contexts": net["contexts"],
            "cross_context": net["cross_context"],
            "domain": net["domain"],
            "signal_labels": signal_labels,
            "endpoint_count": len(endpoints),
            "returned_endpoint_count": len(returned),
            "endpoints_truncated": len(endpoints) > limit,
            "sources": roles["source"],
            "sinks": roles["sink"],
            "bidirectional": roles["bidirectional"],
            "undirected": roles["undirected"],
            "segment_count": net["segment_count"],
        },
        "direction_evidence": {
            "basis": "installed component definition node Direction fields",
            "known_endpoint_count": known_direction_count,
            "unknown_endpoint_count": len(endpoints) - known_direction_count,
            "complete": known_direction_count == len(endpoints),
            "power_flow_inferred": False,
        },
        "limitations": [
            *document["limitations"],
            "Source and sink roles are reported only from explicit INPUT/OUTPUT/I/O definition metadata.",
            "Undirected electrical ports are not assigned power-flow direction.",
        ],
    }


def find_unconnected_ports(
    project_path: str,
    scope: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Find active ports that occupy a singleton static net with no wire segment."""
    if scope is not None and (
        not isinstance(scope, str) or not scope.strip() or len(scope) > 500
    ):
        raise ToolSafetyError("scope must be null or a non-empty string up to 500 characters")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    target, access_scope, document = _document(project_path)
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
    selected = rows[:limit]
    return {
        "status": "completed",
        "access_scope": access_scope,
        "source": document["source"],
        "scope_filter": scope,
        "unconnected_port_count": len(rows),
        "returned_count": len(selected),
        "truncated": len(rows) > limit,
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
) -> dict[str, Any]:
    """Compare exact parameter dictionaries for one component UUID across two RTFX files."""
    if not isinstance(component_id, int) or isinstance(component_id, bool):
        raise ToolSafetyError("component_id must be an integer")
    if context is not None and (
        not isinstance(context, str) or not context.strip() or len(context) > 500
    ):
        raise ToolSafetyError("context must be null or a non-empty string up to 500 characters")

    path_a, scope_a, first = _document(project_a)
    path_b, scope_b, second = _document(project_b)
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
            "source": first["source"],
            "source_hash_rechecked": hash_a,
        },
        "project_b": {
            "access_scope": scope_b,
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
                "context": left["context"],
                "component_type": left["component_type"],
            },
            "project_b_component": {
                "uuid": right["uuid"],
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
) -> dict[str, Any]:
    """Compare static project settings, component identities, parameters, and net signatures."""
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ToolSafetyError("limit must be an integer from 1 through 500")

    path_a, scope_a, first = _document(project_a)
    path_b, scope_b, second = _document(project_b)
    hash_a = sha256_file(path_a)
    hash_b = sha256_file(path_b)
    if hash_a != first["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_a hash changed during project-version comparison")
    if hash_b != second["source"]["rtfx_sha256"]:
        raise ToolSafetyError("project_b hash changed during project-version comparison")

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

    def topology_signature(document: dict[str, Any]) -> str:
        net_rows = []
        for net in document["nets"]:
            members = []
            for member in net["members"]:
                if str(member["atom"]).startswith("port:"):
                    members.append((
                        "port",
                        str(member["context"]),
                        int(member["component_id"]),
                        str(member["port"]),
                        str(member["domain"]),
                        str(member.get("phase")),
                    ))
                else:
                    start = tuple(member["start"])
                    end = tuple(member["end"])
                    endpoints = sorted((start, end))
                    members.append((
                        "segment",
                        str(member["context"]),
                        int(member["component_id"]),
                        str(member["domain"]),
                        str(member.get("phase")),
                        endpoints[0],
                        endpoints[1],
                    ))
            net_rows.append((
                str(net["domain"]),
                tuple(sorted(members, key=repr)),
            ))
        serialized = json.dumps(sorted(net_rows, key=repr), ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    signature_a = topology_signature(first)
    signature_b = topology_signature(second)
    selected = component_changes[:limit]
    return {
        "status": "completed",
        "project_a": {
            "access_scope": scope_a,
            "source": first["source"],
            "source_hash_rechecked": hash_a,
            "topology_signature_sha256": signature_a,
        },
        "project_b": {
            "access_scope": scope_b,
            "source": second["source"],
            "source_hash_rechecked": hash_b,
            "topology_signature_sha256": signature_b,
        },
        "same_rtfx_sha256": hash_a == hash_b,
        "same_static_topology": signature_a == signature_b,
        "project_setting_changes": setting_changes,
        "coverage_changes": coverage_changes,
        "component_change_count": len(component_changes),
        "returned_component_change_count": len(selected),
        "component_changes_truncated": len(component_changes) > limit,
        "component_changes": selected,
        "limitations": [
            "Version comparison uses active static parser output and exact context plus UUID identity.",
            "Topology equality is a normalized parsed-net signature, not a Compile or Runtime equivalence claim.",
            "Component moves that preserve parsed connectivity are not reported as topology changes.",
            "No project write, Compile, Runtime, or hardware operation is performed.",
        ],
        "mutations_performed": False,
        "live_rscad_connection_opened": False,
        "rack_query_called": False,
        "compile_called": False,
        "runtime_or_hardware_called": False,
    }


def validate_project(project_path: str) -> dict[str, Any]:
    """Reparse and validate static topology while proving the RTFX hash is unchanged."""
    target, access_scope = resolve_rtfx_path(project_path)
    before = sha256_file(target)
    _, _, document = _document(project_path)
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


def compare_projects(project_a: str, project_b: str) -> dict[str, Any]:
    """Compare two RTFX files using static structure and component-type counts."""
    _, scope_a, first = _document(project_a)
    _, scope_b, second = _document(project_b)
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
            "source": first["source"],
        },
        "project_b": {
            "access_scope": scope_b,
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

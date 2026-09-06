"""Local component-knowledge construction and source-checked, read-only queries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import BeforeValidator, WithJsonSchema

from . import project_tools
from .core import component_catalog, component_graph, component_graph_store as store
from .core.state_machine import sha256_json
from .input_contracts import validate
from .safety import ToolSafetyError, checked_file, resolve_rtfx_path
from .settings import get_settings


HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
QUERY_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["graph_id", "mode"], "properties": {
        "graph_id": HASH, "mode": {"enum": ["search", "get", "neighbors"]},
        "query": {"type": "string", "minLength": 1, "maxLength": 200},
        "node_id": {"type": "string", "minLength": 1, "maxLength": 100},
        "depth": {"type": "integer", "minimum": 1, "maximum": 2},
        "edge_kinds": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True,
            "items": {"enum": ["IS_A", "CONNECTS_TO", "REQUIRES", "ALTERNATIVE_TO", "USED_IN", "INITIALIZED_BY", "CONTROLLED_BY", "MEASURED_BY"]}},
        "offset": {"type": "integer", "minimum": 0, "maximum": 100000},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}


def validate_query(value):
    validate(value, QUERY_SCHEMA)
    mode = value["mode"]
    allowed = {"graph_id", "mode", "offset", "limit"} | ({"query"} if mode == "search" else {"node_id"})
    if mode == "neighbors":
        allowed |= {"depth", "edge_kinds"}
    if set(value) - allowed or ("query" if mode == "search" else "node_id") not in value:
        raise ValueError("Component knowledge fields do not match query mode")
    if any(isinstance(v, str) and not v.strip() for v in value.values()):
        raise ValueError("Component knowledge query fields cannot be blank")
    return value


KnowledgeQuery = Annotated[dict, BeforeValidator(validate_query), WithJsonSchema(QUERY_SCHEMA)]


def _settings_evidence(settings):
    return {"rscad_home": str(settings.rscad_home) if settings.rscad_home else None,
            "data_dir": str(settings.data_dir), "source_roots": list(map(str, settings.source_roots)),
            "document_roots": list(map(str, settings.document_roots)),
            "expected_rscad_version": settings.expected_rscad_version}


def _implementations():
    root = Path(__file__).resolve().parent
    paths = [root / name for name in ("component_knowledge.py", "project_tools.py", "settings.py", "safety.py", "input_contracts.py",
        "core/component_catalog.py", "core/component_graph.py", "core/component_graph_store.py", "core/topology_parser.py",
        "core/companion_dependencies.py", "core/static_comparison.py", "core/state_machine.py",
        "schemas/component_graph.schema.json", "schemas/component_graph_annotations.schema.json")]
    return {str(path.resolve()) for path in paths}


def _source(path, kind):
    maximum = 256 * 1024 * 1024
    if not path.is_file() or path.stat().st_size > maximum:
        raise ToolSafetyError("Component graph source exceeds 256 MiB")
    digest, size = hashlib.sha256(), 0
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            size += len(block)
            if size > maximum:
                raise ToolSafetyError("Component graph source grew beyond 256 MiB")
            digest.update(block)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest(), "bytes": size, "kind": kind}


def _context_check(context):
    settings = get_settings()
    if set(context) != {"schema_version", "settings", "catalog_snapshot_id", "source_files", "project_snapshots", "annotation_file"}:
        raise ToolSafetyError("Unsupported component graph build context")
    if context["schema_version"] != "1.0" or context["settings"] != _settings_evidence(settings):
        raise ToolSafetyError("Component graph configuration changed; rebuild explicitly")
    settings_now, definitions, snapshot = component_catalog.inventory()
    if settings_now != settings or snapshot != context["catalog_snapshot_id"]:
        raise ToolSafetyError("Component graph catalog changed; rebuild explicitly")
    rows = context["source_files"]
    if not isinstance(rows, list) or len(rows) > 30000:
        raise ToolSafetyError("Component graph source set exceeds bounds")
    seen, implementations, observed = set(), set(), {}
    implementation_paths = _implementations()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "bytes", "kind"}:
            raise ToolSafetyError("Invalid component graph source record")
        if not isinstance(row["sha256"], str) or store.IDENTITY.fullmatch(row["sha256"]) is None:
            raise ToolSafetyError("Invalid component graph source hash")
        if type(row["bytes"]) is not int or not 0 <= row["bytes"] <= 256 * 1024 * 1024:
            raise ToolSafetyError("Invalid component graph source size")
        key = (row["path"], row["kind"])
        if key in seen:
            raise ToolSafetyError("Duplicate component graph source identity")
        seen.add(key)
        kind = row["kind"]
        if kind == "implementation":
            if row["path"] not in implementation_paths:
                raise ToolSafetyError("Unrecognized graph implementation source")
            implementations.add(row["path"])
            roots = (Path(__file__).resolve().parent,)
        elif kind == "definition":
            roots = (settings.definition_root,)
        elif kind in {"project", "companion"}:
            roots = (*settings.source_roots, settings.projects_root)
        elif kind in {"annotation", "provenance"}:
            roots = (*settings.source_roots, *settings.document_roots, settings.definition_root, settings.data_dir)
        else:
            raise ToolSafetyError("Unsupported component graph source kind")
        path = checked_file(row["path"], roots)
        store.safe_path(path, next(root for root in roots if path.is_relative_to(root.resolve())))
        if row['path'] not in observed:
            if sum(item['bytes'] for item in observed.values()) + row['bytes'] > 512 * 1024 * 1024:
                raise ToolSafetyError("Component graph sources exceed 512 MiB")
            observed[row['path']] = _source(path, kind)
        actual = observed[row['path']]
        if actual['bytes'] != row['bytes'] or actual['sha256'] != row['sha256']:
            raise ToolSafetyError("Component graph source changed; rebuild explicitly")
    if implementations != implementation_paths:
        raise ToolSafetyError("Component graph implementation evidence is incomplete")
    actual_definitions = {(row['path'], row['sha256'], row['bytes']) for row in rows if row['kind'] == 'definition'}
    if actual_definitions != {(row['path'], row['sha256'], row['bytes']) for row in definitions}:
        raise ToolSafetyError("Component graph definition set is incomplete")
    if not isinstance(context["project_snapshots"], list) or len(context["project_snapshots"]) > 16:
        raise ToolSafetyError("Invalid component graph project snapshot set")
    project_paths = []
    for project in context["project_snapshots"]:
        if not isinstance(project, dict) or set(project) != {"path", "snapshot_id"}:
            raise ToolSafetyError("Invalid component graph project snapshot")
        path, _ = resolve_rtfx_path(project["path"])
        project_paths.append(str(path))
        current = project_tools._digest(project_tools._snapshot_evidence(path))
        if current != project["snapshot_id"]:
            raise ToolSafetyError("Component graph project snapshot changed; rebuild explicitly")
    if len(set(project_paths)) != len(project_paths) or set(project_paths) != {row['path'] for row in rows if row['kind'] == 'project'}:
        raise ToolSafetyError("Component graph project source set is inconsistent")
    annotation = context['annotation_file']
    annotation_sources = [row for row in rows if row['kind'] == 'annotation']
    if annotation is None:
        if annotation_sources:
            raise ToolSafetyError("Unexpected graph annotation source")
    elif (not isinstance(annotation, dict) or set(annotation) != {'path', 'sha256'} or len(annotation_sources) != 1
          or any(annotation[key] != annotation_sources[0][key] for key in annotation)):
        raise ToolSafetyError("Component graph annotation source is inconsistent")
    if get_settings() != settings:
        raise ToolSafetyError("Component graph settings changed during source verification")


def build_component_knowledge(project_paths=None, annotations_path=None):
    """Explicit local indexing only. Query calls never invoke this builder."""
    project_paths = [] if project_paths is None else project_paths
    if (not isinstance(project_paths, list) or len(project_paths) > 16
            or any(not isinstance(path, str) or not path.strip() for path in project_paths)
            or len(set(project_paths)) != len(project_paths)):
        raise ValueError("Provide up to 16 distinct source project paths")
    settings, definitions, snapshot = component_catalog.inventory()
    records, sources, projects, snapshots = [], [], [], []
    source_cache = {}
    def observe(path, kind):
        key = str(path.resolve())
        if key not in source_cache:
            if sum(row['bytes'] for row in source_cache.values()) + path.stat().st_size > 512 * 1024 * 1024:
                raise ToolSafetyError("Component graph sources exceed 512 MiB")
            source_cache[key] = _source(path, kind)
        return {**source_cache[key], 'kind': kind}
    for ref in definitions:
        with Path(ref['path']).open('rb') as stream:
            body = stream.read(component_catalog.MAX_FILE_BYTES + 1)
        records.append(component_graph.parse_definition(ref, body, settings.expected_rscad_version))
        sources.append({"path": ref["path"], "sha256": ref["sha256"], "bytes": ref["bytes"], "kind": "definition"})
    for value in project_paths:
        path, _, document = project_tools._document(value)
        store.safe_path(path, next(root for root in (*settings.source_roots, settings.projects_root) if path.is_relative_to(root.resolve())))
        projects.append(document)
        snapshots.append({"path": str(path), "snapshot_id": document["snapshot_id"]})
        sources.append(observe(path, "project"))
        if document["snapshot"]["evidence"]["companions"]["status"] != "passed":
            raise ToolSafetyError("Graph project has incomplete companion evidence")
        for companion in document["snapshot"]["evidence"]["companions"].get("files", []):
            sources.append(observe(Path(companion["path"]), "companion"))
    annotations, annotation_file = None, None
    if annotations_path is not None:
        path = checked_file(annotations_path, (*settings.source_roots, *settings.document_roots, settings.data_dir), ".json")
        annotations, digest = store.read_object(path, 1024 * 1024)
        component_graph.validate_annotations(annotations)
        annotation_file = {"path": str(path), "sha256": digest}
        sources.append({"path": str(path), "sha256": digest, "bytes": path.stat().st_size, "kind": "annotation"})
        for assertion in annotations["field_assertions"] + annotations["edge_assertions"]:
            for reference in assertion["provenance"]:
                source = checked_file(reference["source_path"], (*settings.source_roots, *settings.document_roots, settings.definition_root, settings.data_dir))
                row = observe(source, "provenance")
                if row["sha256"] != reference["source_sha256"]:
                    raise ToolSafetyError("Graph annotation provenance hash differs from current source")
                sources.append(row)
    sources.extend(observe(Path(path), "implementation") for path in sorted(_implementations()))
    unique = {}
    for row in sources:
        key = (row["path"], row["kind"])
        if key in unique and row != unique[key]:
            raise ToolSafetyError("Component graph source changed between observations")
        unique[key] = row
    context = {"schema_version": "1.0", "settings": _settings_evidence(settings), "catalog_snapshot_id": snapshot,
               "source_files": [unique[key] for key in sorted(unique)], "project_snapshots": sorted(snapshots, key=lambda p: p["path"]),
               "annotation_file": annotation_file}
    _context_check(context)
    graph = component_graph.build_graph(records, projects, annotations, context)
    published = store.publish(graph, lambda: _context_check(context))
    return {**published, "node_count": len(graph["nodes"]), "edge_count": len(graph["edges"]),
            "source_count": len(unique), "catalog_snapshot_id": snapshot, "sdk_imported": False,
            "live_calls_made": False, "integration_qualified": False}


def _load(graph_id):
    path = store.graph_path(graph_id)
    graph, digest = store.read_object(path)
    component_graph.validate_graph(graph)
    if graph.get("graph_sha256") != graph_id or sha256_json({k: v for k, v in graph.items() if k != "graph_sha256"}) != graph_id:
        raise ToolSafetyError("Component graph hash mismatch")
    _context_check(graph["build_context"])
    return graph, path, digest


def _literal_values(value):
    """Search knowledge content, excluding hashes and cache/source identifiers."""
    if isinstance(value, dict):
        return {key: _literal_values(child) for key, child in value.items()
                if not key.endswith(('sha256', 'node_id', 'snapshot_id'))
                and key not in {'source_path', 'path', 'provenance'}}
    if isinstance(value, list):
        return [_literal_values(child) for child in value]
    return value


def query_component_knowledge(request: KnowledgeQuery) -> dict[str, Any]:
    """Search or traverse a published local graph with fresh hashes; never index or invoke RSCAD."""
    validate_query(request)
    graph, path, digest = _load(request["graph_id"])
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    mode, offset, limit = request["mode"], request.get("offset", 0), request.get("limit", 20)
    result = {"graph_id": request["graph_id"], "mode": mode, "nodes": [], "edges": [],
              "live_calls_made": False, "sdk_imported": False, "mutations_performed": False,
              "integration_qualified": False, "engineering_verdict": "not_evaluated",
              "compatibility_verified": False, "cache_verification": "content_and_current_source_hashes",
              "limitations": ["Observed net membership is not engineering compatibility.",
                  "Explicit assertions are source-bound but their engineering interpretation is not authenticated."]}
    if mode == "search":
        terms = request["query"].casefold().split()
        ranked = []
        for node in graph["nodes"]:
            if node["kind"] != "definition":
                continue
            fields = {"label": node["label"], "definition_id": node['identity'].get('definition_id', ''),
                      "declarations": [row['text'] for row in node.get('declarations', [])]}
            fields.update({key: [{'value': _literal_values(row['value']), 'scope': row.get('scope', '')} for row in field['values']]
                           for key, field in node['fields'].items() if key != 'version_evidence'})
            matched = [key for key, value in fields.items() if any(term in json.dumps(value, ensure_ascii=False).casefold() for term in terms)]
            searchable = json.dumps(fields, ensure_ascii=False).casefold()
            if all(term in searchable for term in terms):
                ranked.append((len(matched), node["node_id"], node, matched))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        result["nodes"] = [row[2] for row in ranked[offset:offset + limit]]
        result["matches"] = [{"node_id": row[1], "matched_fields": row[3]} for row in ranked[offset:offset + limit]]
        total = len(ranked)
        result["ranking"] = "literal_field_matches_only_not_an_engineering_recommendation"
    else:
        node_id = request["node_id"]
        if node_id not in nodes:
            raise ToolSafetyError("Node does not belong to this component graph")
        if mode == "get":
            result["nodes"] = [nodes[node_id]][offset:offset + limit]
            total = 1
        else:
            kinds = set(request.get("edge_kinds", []))
            selected, visited, frontier = {}, {node_id}, {node_id}
            for _ in range(request.get("depth", 1)):
                reached = set()
                for edge in graph["edges"]:
                    if kinds and edge["kind"] not in kinds:
                        continue
                    if edge["source"] in frontier or edge["target"] in frontier:
                        selected[edge["edge_id"]] = edge
                        reached.update((edge["source"], edge["target"]))
                frontier = reached - visited
                visited.update(reached)
            edges = [selected[key] for key in sorted(selected)]
            result["edges"] = edges[offset:offset + limit]
            ids = {node_id} | {edge[key] for edge in result["edges"] for key in ("source", "target")}
            result["nodes"] = [nodes[key] for key in sorted(ids)]
            result["traversal"] = "incident_edges_in_both_directions; edge_direction_is_preserved"
            total = len(edges)
    result.update(status="found" if total else "unresolved", total=total,
                  next_offset=offset + limit if offset + limit < total else None)
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > 2 * 1024 * 1024:
        raise ToolSafetyError("Component knowledge response exceeds 2 MiB; reduce the page limit")
    # The entire input context is rechecked, not just the returned page.
    _context_check(graph["build_context"])
    store.safe_path(path, store.cache_root())
    if store.read_object(path)[1] != digest:
        raise ToolSafetyError("Component graph cache changed while querying")
    return result

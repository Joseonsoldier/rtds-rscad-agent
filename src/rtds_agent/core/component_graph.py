"""Pure source-bound component graph construction; no filesystem or vendor calls."""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
import hashlib
import json
import re

from jsonschema import Draft202012Validator, ValidationError

from ..input_contracts import schema
from .state_machine import sha256_json
from .topology_parser import _section_lines, parse_active_nodes, parse_parameter_schema


GRAPH_SCHEMA = schema("component_graph.schema.json")
ANNOTATIONS_SCHEMA = schema("component_graph_annotations.schema.json")
FIELDS = ("category", "engineering_role", "library", "parameter_schema", "ports", "port_semantics",
          "selector_modes", "typical_use", "compatible_neighbors", "example_projects", "manual_references", "version_evidence")
EDGE_KINDS = {"IS_A", "CONNECTS_TO", "REQUIRES", "ALTERNATIVE_TO", "USED_IN", "INITIALIZED_BY", "CONTROLLED_BY", "MEASURED_BY"}
MAX_NODES, MAX_EDGES, MAX_GRAPH_BYTES = 20000, 100000, 128 * 1024 * 1024


def _json(value, maximum):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Component knowledge must contain finite bounded JSON values") from exc
    if len(encoded) > maximum:
        raise ValueError("Component knowledge exceeds its serialized byte limit")
    return encoded


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"Invalid bounded {label}")
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise ValueError("Expected an exact lowercase SHA-256 identity")
    return value


def _provenance(path, digest, locator):
    return {"source_path": _text(path, "source path"), "source_sha256": _hash(digest), "locator": locator}


def definition_node_id(definition_id):
    return "definition:" + sha256_json(_text(definition_id, "definition ID", 1000))


def _unique_sorted(rows):
    return [row for _, row in sorted({sha256_json(row): row for row in rows}.items())]


def _validate_schema(contract, value):
    try:
        Draft202012Validator(contract).validate(value)
    except ValidationError as exc:
        location = "/".join(str(item) for item in exc.absolute_path)[:500]
        raise ValueError(f"Invalid component graph contract at {location or '/'}: {exc.validator}") from exc


def validate_annotations(value):
    _json(value, 2 * 1024 * 1024)
    _validate_schema(ANNOTATIONS_SCHEMA, value)
    if len(value["field_assertions"]) + len(value["edge_assertions"]) > 1000:
        raise ValueError("At most 1000 component knowledge assertions are supported")
    for assertion in [*value["field_assertions"], *value["edge_assertions"]]:
        for key, item in assertion.items():
            if isinstance(item, str):
                _text(item, key)
        for ref in assertion["provenance"]:
            for key, item in ref.items():
                _text(item, key)
        if "kind" in assertion:
            kind, target = assertion["kind"], assertion["target_kind"]
            allowed = {"concept"} if kind == "IS_A" else {"project"} if kind == "USED_IN" else {"definition", "concept"} if kind in {"REQUIRES", "INITIALIZED_BY"} else {"definition"}
            if target not in allowed:
                raise ValueError("Assertion target kind does not match its relation contract")
            if target == "project":
                _hash(assertion["target_id"])
    return value


def _declarations(text, ref, warnings):
    result, lines = [], text.splitlines()
    sections = {"DESCRIPTION": "description", "KEYWORDS": "keywords", "LIBRARY-DESCRIPTION": "library_description", "HELP": "help"}
    section_count = 0
    for index, line in enumerate(lines):
        heading = line.strip().removesuffix(":")
        if line == heading + ":" and heading in sections:
            section_count += 1
            if section_count > 64:
                raise ValueError("Definition exceeds 64 bounded literal declaration sections")
            body = []
            body_size = 0
            for following_index in range(index + 1, len(lines)):
                following = lines[following_index]
                if following and not following[0].isspace() and re.match(r"^[A-Z][A-Z0-9_-]*:", following):
                    break
                if following.strip():
                    body_size += len(following.strip()) + 1
                    if body_size > 2001:
                        warnings.append("literal_declaration_exceeds_bound:" + sections[heading])
                        body = []
                        break
                    body.append(following.strip())
            value = "\n".join(body)
            if not value:
                continue
            if len(value) > 2000:
                warnings.append("literal_declaration_exceeds_bound:" + sections[heading])
                continue
            result.append({"kind": sections[heading], "text": value,
                           "provenance": [_provenance(ref["path"], ref["sha256"], f"{heading}: section at line {index + 1}")]})
    for line in _section_lines(text, "COMPONENT-DESCRIPTORS"):
        match = re.match(r"\s*CLASSIFICATION:\s*(.+?)\s*$", line)
        if match:
            section_count += 1
            if section_count > 64:
                raise ValueError("Definition exceeds 64 bounded literal declarations")
            value = match.group(1)
            if len(value) > 2000:
                warnings.append("classification_literal_exceeds_bound")
            else:
                result.append({"kind": "classification", "text": value,
                               "provenance": [_provenance(ref["path"], ref["sha256"], "COMPONENT-DESCRIPTORS/CLASSIFICATION literal")]})
    if len(result) > 64:
        raise ValueError("Definition exceeds 64 bounded literal declarations")
    return _unique_sorted(result)


def parse_definition(ref, body: bytes, configured_version: str):
    """Parse one already-read definition without rescanning the catalog."""
    if not isinstance(ref, dict) or set(ref) != {"component_type", "definition_id", "path", "sha256", "bytes"}:
        raise ValueError("Definition reference must exactly match the catalog record")
    for key in ("component_type", "definition_id", "path"):
        _text(ref[key], key, 1000 if key == "definition_id" else 4000)
    _text(configured_version, "configured version", 160)
    if not isinstance(body, bytes) or len(body) > 2 * 1024 * 1024 or type(ref["bytes"]) is not int or len(body) != ref["bytes"]:
        raise ValueError("Definition body/count exceeds bounds or differs from reference")
    if hashlib.sha256(body).hexdigest() != _hash(ref["sha256"]):
        raise ValueError("Definition content hash differs from reference")
    result = {"definition": copy.deepcopy(ref), "configured_rscad_version": configured_version,
              "status": "parsed", "parameters": {}, "parameter_coverage": "unresolved", "active_nodes": [],
              "selectors": [], "declarations": [], "warnings": [], "node_parameters": {}, "context": "subsystem:0"}
    try:
        text = body.decode("utf-8-sig")
    except UnicodeError:
        result["status"] = "unsupported"
        result["warnings"] = ["definition_encoding_not_supported_utf8"]
        return result
    result["declarations"] = _declarations(text, ref, result["warnings"])
    parsed = parse_parameter_schema(text)
    if len(parsed) > 500:
        result['status'] = 'unsupported'
        result['warnings'].append('parameter_schema_unresolved_exceeds_500_parameters')
        return result
    declarations = [line.strip() for line in _section_lines(text, "PARAMETERS")
                    if line.strip() and not line.strip().startswith(("//", "SECTION:"))]
    complete = len(declarations) == len(parsed) and sum(line.strip() == "PARAMETERS:" for line in text.splitlines()) <= 1
    result["parameters"] = {name: {key: value for key, value in row.items() if key != "raw"} for name, row in parsed.items()}
    result["parameter_coverage"] = "declared_parameters_parsed" if complete else "parsed_subset"
    result["selectors"] = [{"parameter": name, "modes": row["enum_values"], "default": row["default"]}
                           for name, row in sorted(parsed.items()) if row["data_type"] == "TOGGLE"]
    if complete:
        nodes, warnings = parse_active_nodes(text, {"parameters": {}, "context": "subsystem:0", "component_type": ref["component_type"]})
        if len(nodes) > 2000:
            result['status'] = 'unsupported'
            result['warnings'].append('active_ports_unresolved_exceeds_2000_ports')
            return result
        result["active_nodes"] = [{key: value for key, value in row.items() if key != "raw"} for row in nodes]
        result["warnings"].extend(warnings)
    else:
        result["warnings"].append("active_ports_unresolved_due_parameter_coverage")
    _json(result, 2 * 1024 * 1024)
    return result


def _unresolved(reason):
    return {"status": "unresolved", "values": [], "reason": reason}


def _fact(value, provenance, scope, status="observed"):
    return {"status": status, "values": [{"value": copy.deepcopy(value), "scope": scope, "evidence_kind": status, "provenance": copy.deepcopy(provenance)}], "reason": None}


def _append_fact(node, field, value, provenance, scope, status):
    entry = node["fields"][field]
    if entry["status"] == "unresolved":
        entry.update(status=status, reason=None)
    elif entry["status"] != status:
        entry["status"] = "mixed_evidence"
    entry["values"] = _unique_sorted([*entry["values"], {"value": copy.deepcopy(value), "scope": scope, "evidence_kind": status, "provenance": copy.deepcopy(provenance)}])


def _require_definition_binding(node, provenance):
    identity = node["identity"]
    if not any(ref["source_path"] == identity["source_path"] and ref["source_sha256"] == identity["source_sha256"] for ref in provenance):
        raise ValueError("Assertion must pin the current exact definition path and hash in provenance")


def _selector_values(record, component):
    parameters = component.get("parameters", {})
    return [{"parameter": selector["parameter"],
             "value": copy.deepcopy(parameters.get(selector["parameter"], selector["default"])),
             "origin": "stored" if selector["parameter"] in parameters else "definition_default" if selector["default"] is not None else "unresolved",
             "declared_modes": copy.deepcopy(selector["modes"])} for selector in record["selectors"]]


def _definition_node(record):
    ref = record["definition"]
    provenance = [_provenance(ref["path"], ref["sha256"], "installed definition bytes")]
    fields = {name: _unresolved("No supported source-backed knowledge for this field") for name in FIELDS}
    fields["version_evidence"] = _unresolved("Product version is not observed from the definition; configured version is " + record["configured_rscad_version"] + ". Component Builder headers are format evidence only.")
    fields["library"] = _fact({"definition_id": ref["definition_id"], "directory": ref["definition_id"].rpartition("/")[0]}, provenance,
                              "Observed definition-relative directory only; not inferred library membership or engineering category")
    if record["status"] == "parsed":
        fields["parameter_schema"] = _fact({"coverage": record["parameter_coverage"], "parameters": record["parameters"]}, provenance, "Static parsed parameter declarations; unsupported declarations remain explicit")
        if record["parameter_coverage"] == "declared_parameters_parsed":
            fields["ports"] = _fact({"active_nodes": record["active_nodes"], "parameters": {}, "context": record["context"], "warnings": record["warnings"]}, provenance,
                                    "Active ports under parsed definition defaults only; other selector configurations are not enumerated")
            fields["port_semantics"] = _fact([{key: node.get(key) for key in ("name", "kind", "direction", "data_type", "phase")} for node in record["active_nodes"]], provenance,
                                             "Declared default-port kind/direction/type/phase only; no inferred electrical meaning")
            fields["selector_modes"] = _fact(record["selectors"], provenance, "Literal TOGGLE choices and defaults; mode behavior is not independently verified")
    for declaration in record["declarations"]:
        if declaration["kind"] == "classification":
            _append_fact({"fields": fields}, "category", declaration["text"], declaration["provenance"], "Literal CLASSIFICATION code, not an inferred engineering taxonomy", "observed")
        elif declaration["kind"] == "help":
            _append_fact({"fields": fields}, "manual_references", {"declared_help_locator": declaration["text"], "target_resolved": False}, declaration["provenance"], "Literal HELP reference; target document/page is not opened or verified", "observed")
    return {"node_id": definition_node_id(ref["definition_id"]), "kind": "definition", "label": ref["component_type"],
            "identity": {"definition_id": ref["definition_id"], "component_type": ref["component_type"], "source_path": ref["path"], "source_sha256": ref["sha256"]},
            "fields": fields, "declarations": copy.deepcopy(record["declarations"]), "project_evidence": [], "provenance": provenance}


def build_graph(definitions, projects, annotations, build_context):
    """Build a bounded immutable graph from previously read source records."""
    if not isinstance(definitions, list) or len(definitions) > 12000 or not isinstance(projects, list) or len(projects) > 16:
        raise ValueError("Graph exceeds 12000 definitions/16 projects")
    if not isinstance(build_context, dict):
        raise ValueError("Graph build context must be a hash-bound object")
    _json(build_context, MAX_GRAPH_BYTES)
    annotations = {"schema_version": "1.0", "field_assertions": [], "edge_assertions": []} if annotations is None else validate_annotations(annotations)
    nodes, edges, warnings = {}, {}, []
    by_definition, definition_sources, records_by_node = {}, defaultdict(list), {}
    project_semantics = {}
    unresolved_instances = 0

    def add_node(node):
        key = node["node_id"]
        if key in nodes:
            old = nodes[key]
            if any(old[field] != node[field] for field in ("kind", "identity", "fields", "declarations")):
                raise ValueError("Conflicting component graph node identity")
            old["provenance"] = _unique_sorted(old["provenance"] + node["provenance"])
            old["project_evidence"] = _unique_sorted(old["project_evidence"] + node["project_evidence"])
            return old
        if len(nodes) >= MAX_NODES:
            raise ValueError("Component graph exceeds 20000 nodes")
        nodes[key] = node
        return node

    def warn(code, details, provenance):
        if len(warnings) >= 20000:
            raise ValueError("Component graph exceeds 20000 unresolved evidence records")
        warnings.append({"code": code, "details": copy.deepcopy(details), "provenance": copy.deepcopy(provenance)})

    def add_edge(kind, source, target, evidence_kind, scope, provenance, observations):
        edge = {"kind": kind, "source": source, "target": target, "evidence_kind": evidence_kind, "scope": scope,
                "provenance": _unique_sorted(provenance), "observations": _unique_sorted(observations),
                "compatibility_verified": False, "integration_qualified": False}
        key = "edge:" + sha256_json(edge)
        if key not in edges and len(edges) >= MAX_EDGES:
            raise ValueError("Component graph exceeds 100000 edges")
        edges[key] = {"edge_id": key, **edge}

    for record in sorted(definitions, key=lambda row: row["definition"]["definition_id"]):
        _json(record, 2 * 1024 * 1024)
        ref = record["definition"]
        if ref["definition_id"] in by_definition:
            raise ValueError("Duplicate exact definition ID; basename ambiguity must remain distinct")
        node = add_node(_definition_node(record))
        records_by_node[node["node_id"]] = record
        by_definition[ref["definition_id"]] = node
        definition_sources[(ref["path"], ref["sha256"], ref["component_type"])].append(node)
        for warning in record["warnings"]:
            warn("definition_parser_limitation", {"definition_id": ref["definition_id"], "warning": warning}, node["provenance"])
    project_nodes = {}
    for document in sorted(projects, key=lambda row: (row["source"]["rtfx_sha256"], row["source"]["rtfx_path"])):
        _json(document, 20 * 1024 * 1024)
        components, nets = document["components"], document["nets"]
        if len(components) > 5000 or len(nets) > 10000:
            raise ValueError("Graph project exceeds 5000 components/10000 nets")
        project_hash = _hash(document["source"]["rtfx_sha256"])
        semantic_hash = sha256_json({"components": components, "nets": nets, "definition_evidence": document.get("definition_evidence", {})})
        if project_hash in project_semantics and project_semantics[project_hash] != semantic_hash:
            raise ValueError("Identical project bytes have conflicting parsed occurrence or net identities")
        project_semantics[project_hash] = semantic_hash
        project_provenance = [_provenance(document["source"]["rtfx_path"], project_hash, "saved project snapshot " + _hash(document["snapshot_id"]))]
        project_id = "project:" + project_hash
        project_evidence = {"snapshot_id": document["snapshot_id"], "coverage": copy.deepcopy(document.get("coverage")),
                            "warnings": copy.deepcopy(document.get("warnings", [])), "limitations": copy.deepcopy(document.get("limitations", [])),
                            "provenance": project_provenance}
        project_node = add_node({"node_id": project_id, "kind": "project", "label": "Saved project " + project_hash[:12], "identity": {"project_sha256": project_hash}, "fields": {}, "declarations": [], "project_evidence": [project_evidence], "provenance": project_provenance})
        project_nodes[project_hash] = project_node
        identity_counts = Counter((row["context"], row["uuid"]) for row in components)
        mapped = {}
        for component in components:
            identity = (component["context"], component["uuid"])
            definition = document.get("definition_evidence", {}).get(component["component_type"], {})
            matches = definition_sources.get((definition.get("path"), definition.get("sha256"), component["component_type"]), [])
            if identity_counts[identity] != 1 or len(matches) != 1:
                unresolved_instances += 1
                warn("model_instance_definition_unresolved_or_ambiguous", {"context": identity[0], "uuid": identity[1], "component_type": component["component_type"]}, project_provenance)
                continue
            node = matches[0]
            mapped[identity] = (node, component)
            occurrence = {"project_sha256": project_hash, "context": identity[0], "component_id": identity[1], "component_type": component["component_type"],
                          "selector_values": _selector_values(records_by_node[node["node_id"]], component)}
            add_edge("USED_IN", node["node_id"], project_id, "observed_usage", "Observed saved-model occurrence; not a vetted example or recommendation", project_provenance, [occurrence])
            _append_fact(node, "example_projects", {"project_node_id": project_id, "project_sha256": project_hash}, project_provenance, "Observed saved-model use only; no successful execution or suitability is inferred", "derived")
        seen_nets = set()
        for net in nets:
            net_key = _text(net["net_id"], "net ID", 1000)
            if net_key in seen_nets:
                raise ValueError("Duplicate saved net identity")
            seen_nets.add(net_key)
            members = defaultdict(list)
            for member in net["members"]:
                if not str(member.get("atom", "")).startswith("port:"):
                    continue
                identity = (member.get("context"), member.get("component_id"))
                if identity not in mapped:
                    continue
                node, component = mapped[identity]
                if member.get("component_type") != component["component_type"]:
                    warn("net_port_component_identity_mismatch", {"net_id": net_key, "atom": member.get("atom")}, project_provenance)
                    continue
                members[identity].append({key: member.get(key) for key in ("atom", "port", "coordinate", "domain", "phase", "kind", "direction", "data_type")})
            if not members:
                continue
            net_id = "net:" + sha256_json({"project_sha256": project_hash, "net_id": net_key})
            add_node({"node_id": net_id, "kind": "net", "label": net_key,
                      "identity": {"project_sha256": project_hash, "net_id": net_key, "domain": net.get("domain"), "contexts": net.get("contexts", [])},
                      "fields": {}, "declarations": [], "project_evidence": [], "provenance": project_provenance})
            for identity, ports in sorted(members.items()):
                if len(ports) > 2000:
                    raise ValueError("Observed component/net membership exceeds 2000 ports")
                node, component = mapped[identity]
                observation = {"project_sha256": project_hash, "net_id": net_key, "context": identity[0], "component_id": identity[1],
                               "component_type": component["component_type"], "ports": _unique_sorted(ports),
                               "selector_values": _selector_values(records_by_node[node["node_id"]], component)}
                add_edge("CONNECTS_TO", node["node_id"], net_id, "observed_connectivity", "Observed same-net membership only; neither pairwise compatibility nor control/measurement causality is established", project_provenance, [observation])
    for assertion in sorted(annotations["field_assertions"], key=sha256_json):
        node = by_definition.get(assertion["definition_id"])
        if node is None:
            raise ValueError("Field assertion references an absent exact definition ID")
        _require_definition_binding(node, assertion["provenance"])
        value = assertion["value"]
        if assertion["field"] == "compatible_neighbors":
            if value not in by_definition:
                raise ValueError("Compatibility assertion requires an exact existing definition ID")
            _require_definition_binding(by_definition[value], assertion["provenance"])
            value = {"definition_node_id": by_definition[value]["node_id"], "definition_id": value, "compatibility_verified": False}
        _append_fact(node, assertion["field"], value, assertion["provenance"], assertion["scope"], "asserted")
    for assertion in sorted(annotations["edge_assertions"], key=sha256_json):
        source = by_definition.get(assertion["source_definition_id"])
        if source is None:
            raise ValueError("Edge assertion references an absent exact source definition")
        _require_definition_binding(source, assertion["provenance"])
        kind, target_key = assertion["target_kind"], assertion["target_id"]
        target = by_definition.get(target_key) if kind == "definition" else project_nodes.get(target_key) if kind == "project" else None
        if kind == "concept":
            target = add_node({"node_id": "concept:" + sha256_json(target_key), "kind": "concept", "label": target_key,
                               "identity": {"label": target_key}, "fields": {}, "declarations": [], "project_evidence": [], "provenance": copy.deepcopy(assertion["provenance"])})
        if target is None:
            raise ValueError("Edge assertion references an absent exact target")
        if kind == "definition":
            _require_definition_binding(target, assertion["provenance"])
        add_edge(assertion["kind"], source["node_id"], target["node_id"], "asserted", assertion["scope"], assertion["provenance"], [])
    result = {"schema_version": "1.0", "build_context": copy.deepcopy(build_context), "nodes": [nodes[key] for key in sorted(nodes)],
              "edges": [edges[key] for key in sorted(edges)], "warnings": _unique_sorted(warnings),
              "statistics": {"definitions": len(definitions), "projects": len(project_nodes), "nodes": len(nodes), "edges": len(edges), "unresolved_model_instances": unresolved_instances},
              "limitations": ["Observed connectivity is saved same-net membership, not compatibility or engineering suitability.",
                              "Engineering roles, uses and non-observational relations require explicit source-bound assertions and remain unverified.",
                              "Definition ports are a parsed subset under defaults; selector-dependent alternatives are not exhaustively enumerated.",
                              "Literal classification/library/help declarations do not prove engineering taxonomy, library membership, manual target identity or product version.",
                              "No vendor SDK, native application, solver, Compile, Runtime, rack or hardware operation is performed."],
              "integration_qualified": False, "live_calls_made": False, "vendor_imported": False}
    _json(result, MAX_GRAPH_BYTES)
    result["graph_sha256"] = sha256_json(result)
    return validate_graph(result)


def validate_graph(graph):
    """Validate a bounded graph and its deterministic content identity; no source I/O."""
    _json(graph, MAX_GRAPH_BYTES)
    _validate_schema(GRAPH_SCHEMA, graph)
    nodes = {node["node_id"]: node for node in graph["nodes"]}
    if len(nodes) != len(graph["nodes"]) or len({edge["edge_id"] for edge in graph["edges"]}) != len(graph["edges"]):
        raise ValueError("Duplicate graph node or edge identity")
    counts = Counter(node["kind"] for node in nodes.values())
    statistics = graph["statistics"]
    if any(statistics[key] != expected for key, expected in {"nodes": len(nodes), "edges": len(graph["edges"]), "definitions": counts["definition"], "projects": counts["project"]}.items()):
        raise ValueError("Graph statistics contradict node and edge counts")
    sources = graph["build_context"].get("source_files")
    if not isinstance(sources, list):
        raise ValueError("Graph build context requires source_files provenance closure")
    permitted = {(row["path"], row["sha256"]) for row in sources}
    pending = [graph["nodes"], graph["edges"], graph["warnings"]]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if "source_path" in value and "source_sha256" in value and (value["source_path"], value["source_sha256"]) not in permitted:
                raise ValueError("Graph provenance is not closed over build_context.source_files")
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    for node in nodes.values():
        identity, kind = node["identity"], node["kind"]
        if kind == "definition":
            expected_id = definition_node_id(identity["definition_id"])
            if node["label"] != identity["component_type"]:
                raise ValueError("Definition label contradicts exact component identity")
        elif kind == "project":
            expected_id = "project:" + identity["project_sha256"]
        elif kind == "concept":
            expected_id = "concept:" + sha256_json(identity["label"])
        else:
            expected_id = "net:" + sha256_json({"project_sha256": identity["project_sha256"], "net_id": identity["net_id"]})
            if "project:" + identity["project_sha256"] not in nodes:
                raise ValueError("Net has no source project node")
        if node["node_id"] != expected_id:
            raise ValueError("Graph node identity does not match its declared identity")
        for field, fact in node["fields"].items():
            kinds = {row["evidence_kind"] for row in fact["values"]}
            expected_status = "unresolved" if not kinds else next(iter(kinds)) if len(kinds) == 1 else "mixed_evidence"
            if fact["status"] != expected_status or (expected_status == "unresolved") != (fact["reason"] is not None):
                raise ValueError("Field status contradicts its individual evidence values")
            for row in fact["values"]:
                if row["evidence_kind"] == "asserted":
                    _require_definition_binding(node, row["provenance"])
                    if field == "compatible_neighbors":
                        target = nodes.get(row["value"].get("definition_node_id"))
                        if target is None or target["kind"] != "definition" or target["identity"]["definition_id"] != row["value"].get("definition_id") or row["value"].get("compatibility_verified") is not False:
                            raise ValueError("Compatibility assertion has an invalid exact target")
                        _require_definition_binding(target, row["provenance"])
    for edge in graph["edges"]:
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("Graph edge has an unresolved endpoint")
        if edge["evidence_kind"] == "observed_connectivity" and (edge["kind"] != "CONNECTS_TO" or nodes[edge["source"]]["kind"] != "definition" or nodes[edge["target"]]["kind"] != "net"):
            raise ValueError("Observed connectivity must remain definition-to-net membership")
        source, target = nodes[edge["source"]], nodes[edge["target"]]
        if edge["evidence_kind"] == "observed_usage" and (edge["kind"] != "USED_IN" or source["kind"] != "definition" or target["kind"] != "project"):
            raise ValueError("Observed usage must remain definition-to-project occurrence")
        if edge["evidence_kind"] != "asserted":
            if not edge["observations"]:
                raise ValueError("Observed relation requires exact occurrence evidence")
            for observation in edge["observations"]:
                if observation["project_sha256"] != target["identity"]["project_sha256"] or observation["component_type"] != source["identity"]["component_type"]:
                    raise ValueError("Observed relation contradicts endpoint identity")
                if target["kind"] == "net" and observation["net_id"] != target["identity"]["net_id"]:
                    raise ValueError("Observed connectivity contradicts saved net identity")
        else:
            if source["kind"] != "definition":
                raise ValueError("Asserted relation requires exact source definition")
            allowed = {"concept"} if edge["kind"] == "IS_A" else {"project"} if edge["kind"] == "USED_IN" else {"definition", "concept"} if edge["kind"] in {"REQUIRES", "INITIALIZED_BY"} else {"definition"}
            if target["kind"] not in allowed or edge["observations"]:
                raise ValueError("Asserted relation has contradictory target or observations")
            _require_definition_binding(source, edge["provenance"])
            if target["kind"] == "definition":
                _require_definition_binding(target, edge["provenance"])
        if edge["edge_id"] != "edge:" + sha256_json({key: value for key, value in edge.items() if key != "edge_id"}):
            raise ValueError("Graph edge identity does not match its evidence")
    expected = sha256_json({key: value for key, value in graph.items() if key != "graph_sha256"})
    if graph["graph_sha256"] != expected:
        raise ValueError("Component graph content hash mismatch")
    return graph

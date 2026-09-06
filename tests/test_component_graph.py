"""Synthetic pure component graph tests; no filesystem, SDK or native execution."""
import test_environment
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rtds_agent.core.component_graph import (
    ANNOTATIONS_SCHEMA, GRAPH_SCHEMA, FIELDS, build_graph as pure_build_graph, definition_node_id,
    parse_definition, validate_annotations, validate_graph,
)
from rtds_agent.core.state_machine import sha256_json


BODY = b'''DESCRIPTION:
  Synthetic source description
KEYWORDS:
  power source fixture
LIBRARY-DESCRIPTION:
  Synthetic display description
COMPONENT-DESCRIPTORS:
  CLASSIFICATION:TEST_SOURCE
  MAINSTEP:YES
HELP:
  guide.pdf:source
PARAMETERS:
 Gain "Magnitude" "pu" REAL 1 0 10
 Mode "Selector" "First;Second" TOGGLE 0
NODES:
 A 0 0 INPUT REAL
 B 10 0 OUTPUT REAL
'''


def definition(identity="sources/source", body=BODY):
    reference = {"component_type": identity.rsplit("/", 1)[-1], "definition_id": identity,
                 "path": "C:/synthetic/MLIB/" + identity, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    return parse_definition(reference, body, "2.7.3")


def project(definitions, count=None, *, path="C:/synthetic/models/example.rtfx"):
    count = count or len(definitions)
    components, ports, evidence = [], [], {}
    for index in range(count):
        record = definitions[index % len(definitions)]
        ref = record["definition"]
        components.append({"context": "subsystem:0", "uuid": index + 1, "component_type": ref["component_type"], "parameters": {"Gain": "1", "Mode": "First"}})
        evidence[ref["component_type"]] = {"path": ref["path"], "sha256": ref["sha256"]}
        ports.append({"atom": f"port:subsystem:0:{index + 1}:A:0", "context": "subsystem:0", "component_id": index + 1,
                      "component_type": ref["component_type"], "port": "A", "coordinate": [index, 0], "domain": "signal",
                      "phase": None, "kind": "INPUT", "direction": "INPUT", "data_type": "REAL"})
    digest = sha256_json({"components": components, "ports": ports})
    return {"source": {"rtfx_path": path, "rtfx_sha256": digest}, "snapshot_id": sha256_json({"project": digest, "path": path}),
            "components": components, "ports": ports, "definition_evidence": evidence,
            "nets": [{"net_id": "net_0001", "domain": "signal", "contexts": ["subsystem:0"], "members": ports}],
            "coverage": {"definition_coverage": 1.0}, "warnings": [], "limitations": ["Synthetic parsed fixture"]}


def context():
    return {"schema_version": "1.0", "settings": {"rscad_home": "C:/synthetic", "data_dir": "C:/synthetic-data",
            "source_roots": ["C:/synthetic/models"], "document_roots": ["C:/synthetic/DOC"], "expected_rscad_version": "2.7.3"},
            "catalog_snapshot_id": "a" * 64, "source_files": [], "project_snapshots": [], "annotation_file": None}


def provenance():
    return [{"source_path": "C:/synthetic/DOC/guide.md", "source_sha256": "b" * 64, "locator": "Synthetic section 2"}]


def bound_provenance(*identities):
    return provenance() + [{"source_path": definition(identity)["definition"]["path"],
                            "source_sha256": definition(identity)["definition"]["sha256"], "locator": "Exact asserted definition version"}
                           for identity in sorted(set(identities))]


def build_graph(definitions, projects, annotations, build_context):
    """Synthetic reader fixture supplies the same closed source inventory as the public reader."""
    ctx = copy.deepcopy(build_context)
    rows = []
    for record in definitions:
        if "definition" in record:
            ref = record["definition"]
            rows.append({"path": ref["path"], "sha256": ref["sha256"], "bytes": ref["bytes"], "kind": "definition"})
    for document in projects:
        if "source" in document:
            rows.append({"path": document["source"]["rtfx_path"], "sha256": document["source"]["rtfx_sha256"], "bytes": 1, "kind": "project"})
    if annotations:
        for assertion in [*annotations["field_assertions"], *annotations["edge_assertions"]]:
            for ref in assertion["provenance"]:
                rows.append({"path": ref["source_path"], "sha256": ref["source_sha256"], "bytes": 1, "kind": "provenance"})
    ctx["source_files"] = sorted({(row["path"], row["sha256"]): row for row in rows}.values(), key=lambda row: (row["path"], row["sha256"]))
    return pure_build_graph(definitions, projects, annotations, ctx)


def annotations():
    return {"schema_version": "1.0", "field_assertions": [], "edge_assertions": []}


def field_assertion(field, value, identity="sources/source"):
    identities = [identity, value] if field == "compatible_neighbors" else [identity]
    return {"definition_id": identity, "field": field, "value": value, "scope": "Synthetic declared scope only", "provenance": bound_provenance(*identities)}


def edge_assertion(kind, target_kind, target_id, source="sources/source"):
    return {"kind": kind, "source_definition_id": source, "target_kind": target_kind, "target_id": target_id,
            "scope": "Synthetic declared relation; not qualified", "provenance": bound_provenance(source, *([target_id] if target_kind == "definition" else []))}


class DefinitionParsingTests(unittest.TestCase):
    def test_source_identity_defaults_and_literal_declarations(self):
        record = definition()
        self.assertEqual(record["parameter_coverage"], "declared_parameters_parsed")
        self.assertEqual(record["selectors"], [{"parameter": "Mode", "modes": ["First", "Second"], "default": "0"}])
        self.assertEqual([node["name"] for node in record["active_nodes"]], ["A", "B"])
        literals = {row["kind"]: row["text"] for row in record["declarations"]}
        self.assertEqual(literals["classification"], "TEST_SOURCE")
        self.assertEqual(literals["library_description"], "Synthetic display description")
        self.assertEqual(literals["help"], "guide.pdf:source")
        self.assertIn("power source", literals["keywords"])
        for declaration in record["declarations"]:
            self.assertEqual(declaration["provenance"][0]["source_sha256"], record["definition"]["sha256"])

    def test_invalid_hash_size_encoding_and_partial_schema_are_explicit(self):
        record = definition()
        ref = record["definition"]
        for change in ({"sha256": "0" * 64}, {"bytes": len(BODY) + 1}, {"bytes": True}, {"extra": "unsafe"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_definition({**ref, **change}, BODY, "2.7.3")
        unknown = definition(body=b"\xff\x00")
        self.assertEqual(unknown["status"], "unsupported")
        duplicate = definition(body=BODY.replace(b'NODES:', b' Gain "Duplicate" "pu" REAL 2 0 10\nNODES:'))
        self.assertEqual(duplicate["parameter_coverage"], "parsed_subset")
        self.assertEqual(duplicate["active_nodes"], [])
        self.assertIn("active_ports_unresolved_due_parameter_coverage", duplicate["warnings"])

    def test_parameters_and_definition_bytes_are_bounded(self):
        large = b"x" * (2 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            definition(body=large)
        many = "PARAMETERS:\n" + "\n".join(f' p{i} "Value" "pu" REAL 1 0 10' for i in range(501)) + "\nNODES:\n"
        oversized = definition(body=many.encode())
        self.assertEqual(oversized['status'], 'unsupported')
        graph = build_graph([oversized], [], None, context())
        self.assertEqual(graph['nodes'][0]['fields']['parameter_schema']['status'], 'unresolved')
        self.assertIn('parameter_schema_unresolved_exceeds_500_parameters', oversized['warnings'])
        with self.assertRaisesRegex(ValueError, "64 bounded"):
            definition(body=b"DESCRIPTION:\n" * 100000)

    def test_no_role_or_product_version_inferred_from_builder_header_or_name(self):
        body = b"Component Builder Version 9.9\nPARAMETERS:\nNODES:\n"
        graph = build_graph([definition("generators/definitely_a_generator", body)], [], None, context())
        node = graph["nodes"][0]
        self.assertEqual(node["fields"]["engineering_role"]["status"], "unresolved")
        self.assertEqual(node["fields"]["category"]["status"], "unresolved")
        self.assertEqual(node["fields"]["version_evidence"]["status"], "unresolved")
        self.assertNotIn("9.9", json.dumps(node["fields"]["version_evidence"]))


class ComponentGraphTests(unittest.TestCase):
    def test_schema_shape_and_deterministic_nonmutating_build(self):
        Draft202012Validator.check_schema(GRAPH_SCHEMA)
        Draft202012Validator.check_schema(ANNOTATIONS_SCHEMA)
        definitions = [definition(), definition("loads/load")]
        documents = [project(definitions)]
        before = copy.deepcopy((definitions, documents, context()))
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No source I/O in pure builder")):
            first = build_graph(definitions, documents, None, context())
            second = build_graph(list(reversed(definitions)), documents, None, context())
        self.assertEqual(first, second)
        self.assertEqual((definitions, documents, context()), before)
        self.assertEqual(validate_graph(first), first)
        self.assertFalse(first["integration_qualified"])
        self.assertFalse(first["live_calls_made"])
        self.assertFalse(first["vendor_imported"])
        for node in first["nodes"]:
            self.assertTrue(node["provenance"])
            self.assertEqual(set(node["fields"]), set(FIELDS) if node["kind"] == "definition" else set())

    def test_duplicate_basename_maps_only_exact_definition_path_and_hash(self):
        definitions = [definition("a/source"), definition("b/source")]
        document = project([definitions[0]])
        graph = build_graph(definitions, [document], None, context())
        usage = [edge for edge in graph["edges"] if edge["kind"] == "USED_IN"]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]["source"], definition_node_id("a/source"))
        document["definition_evidence"]["source"]["sha256"] = "0" * 64
        graph = build_graph(definitions, [document], None, context())
        self.assertEqual(graph["edges"], [])
        self.assertEqual(graph["statistics"]["unresolved_model_instances"], 1)
        with self.assertRaisesRegex(ValueError, "Duplicate exact definition ID"):
            build_graph([definitions[0], definitions[0]], [], None, context())

    def test_same_net_is_linear_membership_not_pairwise_compatibility_or_causality(self):
        definitions = [definition()]
        graph = build_graph(definitions, [project(definitions, count=100)], None, context())
        edges = [edge for edge in graph["edges"] if edge["kind"] == "CONNECTS_TO"]
        self.assertEqual(len(edges), 100)
        self.assertEqual(len([node for node in graph["nodes"] if node["kind"] == "net"]), 1)
        self.assertTrue(all(edge["evidence_kind"] == "observed_connectivity" and edge["target"].startswith("net:") for edge in edges))
        self.assertEqual({edge["observations"][0]["component_id"] for edge in edges}, set(range(1, 101)))
        self.assertTrue(all(edge["observations"][0]["ports"][0]["atom"] for edge in edges))
        node = next(node for node in graph["nodes"] if node["kind"] == "definition")
        self.assertEqual(node["fields"]["compatible_neighbors"]["status"], "unresolved")
        self.assertFalse(any(edge["kind"] in {"CONTROLLED_BY", "MEASURED_BY"} for edge in graph["edges"]))

    def test_multiple_ports_on_one_instance_remain_one_membership_with_exact_ports(self):
        definitions = [definition()]
        document = project(definitions)
        other = {**document["ports"][0], "atom": "port:subsystem:0:1:B:1", "port": "B", "coordinate": [10, 0]}
        document["nets"][0]["members"].append(other)
        graph = build_graph(definitions, [document], None, context())
        edges = [edge for edge in graph["edges"] if edge["kind"] == "CONNECTS_TO"]
        self.assertEqual(len(edges), 1)
        self.assertEqual({port["port"] for port in edges[0]["observations"][0]["ports"]}, {"A", "B"})

    def test_ambiguous_component_identity_and_wrong_net_type_are_unresolved(self):
        definitions = [definition()]
        document = project(definitions)
        document["components"].append(copy.deepcopy(document["components"][0]))
        graph = build_graph(definitions, [document], None, context())
        self.assertFalse(graph["edges"])
        self.assertEqual(graph["statistics"]["unresolved_model_instances"], 2)
        document = project(definitions)
        document["nets"][0]["members"][0]["component_type"] = "other"
        graph = build_graph(definitions, [document], None, context())
        self.assertFalse(any(edge["kind"] == "CONNECTS_TO" for edge in graph["edges"]))
        self.assertIn("net_port_component_identity_mismatch", [warning["code"] for warning in graph["warnings"]])

    def test_all_eight_explicit_relations_retain_provenance_without_qualification(self):
        definitions = [definition(), definition("loads/load")]
        document = project(definitions)
        ann = annotations()
        ann["edge_assertions"] = [edge_assertion("IS_A", "concept", "declared category"),
                                  edge_assertion("USED_IN", "project", document["source"]["rtfx_sha256"])]
        ann["edge_assertions"] += [edge_assertion(kind, "definition", "loads/load") for kind in
                                   ("CONNECTS_TO", "REQUIRES", "ALTERNATIVE_TO", "INITIALIZED_BY", "CONTROLLED_BY", "MEASURED_BY")]
        graph = build_graph(definitions, [document], ann, context())
        edges = [edge for edge in graph["edges"] if edge["evidence_kind"] == "asserted"]
        self.assertEqual(len(edges), 8)
        self.assertEqual({edge["kind"] for edge in edges}, {"IS_A", "CONNECTS_TO", "REQUIRES", "ALTERNATIVE_TO", "USED_IN", "INITIALIZED_BY", "CONTROLLED_BY", "MEASURED_BY"})
        self.assertTrue(all(provenance()[0] in edge["provenance"] for edge in edges))
        self.assertTrue(all(edge["compatibility_verified"] is False and edge["integration_qualified"] is False for edge in edges))

    def test_roles_and_compatibility_require_explicit_scoped_assertions(self):
        definitions = [definition(), definition("loads/load")]
        ann = annotations()
        ann["field_assertions"] = [field_assertion("engineering_role", "Declared test source"),
                                   field_assertion("compatible_neighbors", "loads/load"),
                                   field_assertion("typical_use", "Synthetic scenario only")]
        graph = build_graph(definitions, [], ann, context())
        node = next(node for node in graph["nodes"] if node["node_id"] == definition_node_id("sources/source"))
        self.assertEqual(node["fields"]["engineering_role"]["status"], "asserted")
        neighbor = node["fields"]["compatible_neighbors"]["values"][0]
        self.assertEqual(neighbor["value"]["definition_id"], "loads/load")
        self.assertFalse(neighbor["value"]["compatibility_verified"])
        self.assertEqual(neighbor["scope"], "Synthetic declared scope only")
        self.assertEqual(neighbor["provenance"], bound_provenance("sources/source", "loads/load"))
        self.assertFalse(graph["edges"])

    def test_multiple_assertions_are_retained_without_selecting_one(self):
        ann = annotations()
        ann["field_assertions"] = [field_assertion("category", "user category"), field_assertion("engineering_role", "role one"), field_assertion("engineering_role", "role two")]
        graph = build_graph([definition()], [], ann, context())
        node = graph["nodes"][0]
        self.assertEqual(node["fields"]["category"]["status"], "mixed_evidence")
        self.assertEqual({row["value"]: row["evidence_kind"] for row in node["fields"]["category"]["values"]}, {"TEST_SOURCE": "observed", "user category": "asserted"})
        self.assertEqual({row["value"] for row in node["fields"]["engineering_role"]["values"]}, {"role one", "role two"})
        ann["field_assertions"].reverse()
        self.assertEqual(graph, build_graph([definition()], [], ann, context()))

    def test_annotation_schema_rejects_unknown_authority_fields_unbounded_or_wrong_targets(self):
        invalid = []
        ann = annotations(); ann["integration_qualified"] = True; invalid.append(ann)
        ann = annotations(); ann["field_assertions"] = [{**field_assertion("engineering_role", "role"), "trusted": True}]; invalid.append(ann)
        ann = annotations(); ann["field_assertions"] = [field_assertion("engineering_role", " ")]; invalid.append(ann)
        ann = annotations(); ann["field_assertions"] = [field_assertion("engineering_role", "x" * 2001)]; invalid.append(ann)
        ann = annotations(); ann["edge_assertions"] = [edge_assertion("IS_A", "definition", "loads/load")]; invalid.append(ann)
        ann = annotations(); ann["edge_assertions"] = [edge_assertion("USED_IN", "project", "not-a-hash")]; invalid.append(ann)
        ann = annotations(); ann["edge_assertions"] = [edge_assertion("RUN", "definition", "loads/load")]; invalid.append(ann)
        ann = annotations(); ann["field_assertions"] = [field_assertion("engineering_role", "role")] * 2; invalid.append(ann)
        for ann in invalid:
            with self.subTest(ann=ann), self.assertRaises(Exception):
                validate_annotations(ann)

    def test_absent_assertion_endpoints_fail_instead_of_creating_fake_definitions(self):
        for assertion in (field_assertion("engineering_role", "role", "absent"), field_assertion("compatible_neighbors", "absent")):
            ann = annotations(); ann["field_assertions"] = [assertion]
            with self.assertRaises(ValueError):
                build_graph([definition()], [], ann, context())
        ann = annotations(); ann["edge_assertions"] = [edge_assertion("REQUIRES", "definition", "absent")]
        with self.assertRaises(ValueError):
            build_graph([definition()], [], ann, context())

    def test_project_hash_separates_same_named_nets(self):
        definitions = [definition()]
        first, second = project(definitions), project(definitions, count=2)
        graph = build_graph(definitions, [first, second], None, context())
        self.assertEqual(len([node for node in graph["nodes"] if node["kind"] == "net"]), 2)
        self.assertEqual(graph["statistics"]["projects"], 2)

    def test_project_parser_limitations_and_saved_selectors_remain_scoped(self):
        definitions = [definition()]
        document = project(definitions, count=2)
        document["components"][0]["parameters"]["Mode"] = "Second"
        document["components"][1]["parameters"].pop("Mode")
        document["warnings"] = ["selector expression unresolved for omitted port"]
        document["coverage"]["ports_complete"] = False
        graph = build_graph(definitions, [document], None, context())
        node = next(node for node in graph["nodes"] if node["kind"] == "project")
        evidence = node["project_evidence"][0]
        self.assertEqual(evidence["warnings"], document["warnings"])
        self.assertEqual(evidence["limitations"], document["limitations"])
        self.assertEqual(evidence["coverage"], document["coverage"])
        self.assertEqual(evidence["snapshot_id"], document["snapshot_id"])
        for edge in graph["edges"]:
            row = edge["observations"][0]
            selector = row["selector_values"][0]
            self.assertEqual(selector["parameter"], "Mode")
            self.assertEqual(selector["declared_modes"], ["First", "Second"])
            self.assertEqual((selector["value"], selector["origin"]), ("Second", "stored") if row["component_id"] == 1 else ("0", "definition_default"))

    def test_identical_project_copies_merge_provenance_and_reject_conflicting_parse(self):
        definitions = [definition()]
        first = project(definitions)
        second = project(definitions, path="C:/synthetic/models/copied.rtfx")
        graph = build_graph(definitions, [first, second], None, context())
        project_node = next(node for node in graph["nodes"] if node["kind"] == "project")
        self.assertEqual(len(project_node["provenance"]), 2)
        self.assertEqual(len(project_node["project_evidence"]), 2)
        self.assertEqual(graph["statistics"]["projects"], 1)
        second["nets"][0]["members"][0]["port"] = "Different"
        with self.assertRaisesRegex(ValueError, "conflicting parsed"):
            build_graph(definitions, [first, second], None, context())

    def test_assertions_pin_exact_definition_versions_and_all_definition_targets(self):
        ann = annotations()
        ann["field_assertions"] = [field_assertion("engineering_role", "Declared role")]
        with self.assertRaisesRegex(ValueError, "pin the current exact"):
            build_graph([definition(body=BODY + b"\n// changed version\n")], [], ann, context())
        ann["field_assertions"][0]["provenance"] = provenance()
        with self.assertRaisesRegex(ValueError, "pin the current exact"):
            build_graph([definition()], [], ann, context())
        for edge in (False, True):
            ann = annotations()
            item = edge_assertion("ALTERNATIVE_TO", "definition", "loads/load") if edge else field_assertion("compatible_neighbors", "loads/load")
            item["provenance"] = bound_provenance("sources/source")
            ann["edge_assertions" if edge else "field_assertions"] = [item]
            with self.assertRaisesRegex(ValueError, "pin the current exact"):
                build_graph([definition(), definition("loads/load")], [], ann, context())

    def test_provenance_closure_and_rehashed_identity_forgery_fail(self):
        with self.assertRaisesRegex(ValueError, "provenance is not closed"):
            pure_build_graph([definition()], [], None, context())
        graph = build_graph([definition()], [project([definition()])], None, context())
        mutations = [lambda g: g["build_context"].update(source_files=[]),
                     lambda g: g["build_context"].update(source_files=[{}]),
                     lambda g: g["build_context"].update(source_files=None),
                     lambda g: g["statistics"].update(definitions=100),
                     lambda g: next(node for node in g["nodes"] if node["kind"] == "definition")["identity"].update(definition_id="wrong"),
                     lambda g: next(edge for edge in g["edges"] if edge["kind"] == "USED_IN").update(target=next(node["node_id"] for node in g["nodes"] if node["kind"] == "net")),
                     lambda g: next(edge for edge in g["edges"] if edge["kind"] == "USED_IN")["observations"][0].update(component_type="wrong")]
        for mutate in mutations:
            changed = copy.deepcopy(graph)
            mutate(changed)
            for edge in changed["edges"]:
                edge["edge_id"] = "edge:" + sha256_json({key: value for key, value in edge.items() if key != "edge_id"})
            changed["graph_sha256"] = sha256_json({key: value for key, value in changed.items() if key != "graph_sha256"})
            with self.assertRaises(ValueError):
                validate_graph(changed)

    def test_graph_and_edge_hashes_flags_and_endpoints_are_revalidated(self):
        graph = build_graph([definition()], [project([definition()])], None, context())
        changed = copy.deepcopy(graph); changed["nodes"][0]["label"] = "tampered"
        with self.assertRaises(ValueError):
            validate_graph(changed)
        for change in (lambda g: g.update(integration_qualified=True),
                       lambda g: g["edges"][0].update(target="absent"),
                       lambda g: g["edges"][0].update(compatibility_verified=True),
                       lambda g: g["nodes"].append(copy.deepcopy(g["nodes"][0]))):
            changed = copy.deepcopy(graph); change(changed)
            with self.assertRaises(Exception):
                validate_graph(changed)

    def test_declared_bounds_and_nonfinite_build_context_fail_closed(self):
        with self.assertRaises(ValueError):
            build_graph([], [{}] * 17, None, context())
        with self.assertRaises(ValueError):
            build_graph([{}] * 12001, [], None, context())
        with self.assertRaises(ValueError):
            build_graph([], [], None, {"invalid": float("nan")})
        document = project([definition()])
        document["nets"].append(copy.deepcopy(document["nets"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate saved net"):
            build_graph([definition()], [document], None, context())
        with patch("rtds_agent.core.component_graph.MAX_NODES", 1):
            with self.assertRaisesRegex(ValueError, "20000 nodes"):
                build_graph([definition()], [project([definition()])], None, context())
        with patch("rtds_agent.core.component_graph.MAX_EDGES", 0):
            with self.assertRaisesRegex(ValueError, "100000 edges"):
                build_graph([definition()], [project([definition()])], None, context())


if __name__ == "__main__":
    unittest.main()

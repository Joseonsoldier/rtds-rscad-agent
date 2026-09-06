"""Pure bounded checks of declared initialization and supplied saved-model evidence."""
from __future__ import annotations

import copy
import math

from ..input_contracts import schema, validate
from .state_machine import sha256_json
from .static_comparison import topology_signature


INITIALIZATION_SCHEMA = schema("loadflow_initialization.schema.json")
SUPPLIED_SCHEMA = {"$defs": INITIALIZATION_SCHEMA["$defs"], "$ref": "#/$defs/supplied_document"}
QUANTITY_UNITS = {"P": {"W", "kW", "MW", "pu"}, "Q": {"var", "kvar", "Mvar", "MVAR", "pu"},
                  "V": {"V", "kV", "pu"}, "angle": {"deg", "rad"}}
MAX_DIFF = 128


def _nonblank(value):
    if isinstance(value, dict):
        for child in value.values():
            _nonblank(child)
    elif isinstance(value, list):
        for child in value:
            _nonblank(child)
    elif isinstance(value, str) and not value.strip():
        raise ValueError("Initialization text fields must not be blank")


def _point(point):
    for name, quantity in point.items():
        if quantity["units"] not in QUANTITY_UNITS[name]:
            raise ValueError(f"Unsupported {name} units; initialization performs no conversion")
        if name == "V" and quantity["value"] < 0:
            raise ValueError("Voltage magnitude must be nonnegative")


def validate_initialization(request):
    validate(request, INITIALIZATION_SCHEMA)
    _nonblank(request)
    identities, entity_ids = set(), set()
    for entity in request["entities"]:
        identity = (entity["context"], entity["component_id"])
        if identity in identities or entity["entity_id"] in entity_ids:
            raise ValueError("Duplicate initialization entity or component identity")
        identities.add(identity)
        entity_ids.add(entity["entity_id"])
        bindings = entity["parameter_bindings"]
        if len({row["quantity"] for row in bindings}) != len(bindings) or len({row["parameter"] for row in bindings}) != len(bindings):
            raise ValueError("Each operating quantity and stored parameter needs one exact binding")
        mapped = {}
        for binding in bindings:
            for field in ("parameter", "calculated_parameter"):
                parameter = binding[field]
                if parameter in mapped and mapped[parameter] != binding["quantity"]:
                    raise ValueError("One stored parameter cannot represent different operating quantities")
                mapped[parameter] = binding["quantity"]
        if {row["quantity"] for row in bindings} != set(entity["requested_operating_point"]):
            raise ValueError("Requested operating point and parameter binding quantities must match")
        _point(entity["requested_operating_point"])
    return request


def plan_sha256(request):
    return sha256_json({key: request[key] for key in ("schema_version", "input_project_sha256", "entities", "provenance")})


def validate_supplied(document):
    validate(document, SUPPLIED_SCHEMA)
    _nonblank(document)
    identities = [row["entity_id"] for row in document["calculated_states"]]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate supplied calculated-state entity")
    for row in document["calculated_states"]:
        _point(row["operating_point"])
    changes = [(row["context"], row["component_id"], row["parameter"]) for row in document["parameter_changes"]]
    if len(set(changes)) != len(changes):
        raise ValueError("Duplicate supplied parameter change")
    return document


def _numeric_text(text):
    try:
        result = float(text)
    except (ValueError, TypeError, OverflowError):
        return None
    return result if math.isfinite(result) and abs(result) <= 1e12 else None


def _component_map(document):
    if len(document["components"]) > 5000 or len(document["nets"]) > 10000:
        raise ValueError("Initialization comparison exceeds 5000 components/10000 nets")
    result = {}
    for row in document["components"]:
        key = (row["context"], row["uuid"])
        if key in result:
            raise ValueError("Duplicate model identity prevents initialization comparison")
        result[key] = row
    return result


def check_preconditions(request, document, static_report, definition_schemas=None):
    """Check supplied bindings; never infer electrical roles or solver readiness."""
    validate_initialization(request)
    components = _component_map(document)
    reasons, entities = [], []
    if document["source"]["rtfx_sha256"] != request["input_project_sha256"]:
        raise ValueError("Initialization input model hash mismatch")
    if static_report.get("status") != "no_errors_in_checked_scope":
        reasons.append("static_model_check_has_errors_or_is_unavailable")
    evidence = document.get("snapshot", {}).get("evidence", {})
    if document.get("coverage", {}).get("definition_coverage") != 1.0:
        reasons.append("component_definition_coverage_incomplete")
    if evidence.get("companions", {}).get("status") != "passed":
        reasons.append("companion_dependency_evidence_incomplete")
    for entity in request["entities"]:
        row = components.get((entity["context"], entity["component_id"]))
        findings = []
        if row is None or row["component_type"] != entity["component_type"]:
            findings.append("exact_component_identity_not_found")
        else:
            for binding in entity["parameter_bindings"]:
                declared = entity["requested_operating_point"][binding["quantity"]]
                for field in ("parameter", "calculated_parameter"):
                    parameter = binding[field]
                    definition = (definition_schemas or {}).get(entity["component_type"], {}).get(parameter)
                    if not definition or definition.get("data_type") not in {"REAL", "INTEGER"}:
                        findings.append("numeric_parameter_definition_unresolved_or_unsupported:" + parameter)
                    elif definition.get("unit") != declared["units"]:
                        findings.append("declared_units_contradict_parameter_definition:" + parameter)
                observed = row["parameters"].get(binding["parameter"])
                if observed != binding["expected_stored_value"]:
                    findings.append("stored_parameter_missing_or_changed:" + binding["parameter"])
                elif _numeric_text(observed) != entity["requested_operating_point"][binding["quantity"]]["value"]:
                    findings.append("requested_value_not_equal_to_stored_numeric_value:" + binding["parameter"])
                calculated_initial = row["parameters"].get(binding["calculated_parameter"])
                if calculated_initial != binding["expected_calculated_stored_value"] or _numeric_text(calculated_initial) is None:
                    findings.append("calculated_parameter_initial_value_missing_changed_or_nonnumeric:" + binding["calculated_parameter"])
        entities.append({"entity_id": entity["entity_id"], "identity": {key: entity[key] for key in ("context", "component_id", "component_type")},
                         "declared_role": entity["role"], "status": "blocked" if findings else "checked", "reasons": findings,
                         "requested_operating_point": copy.deepcopy(entity["requested_operating_point"]),
                         "parameter_bindings": copy.deepcopy(entity["parameter_bindings"]),
                         "unbound_quantities_not_evaluated": sorted(set(QUANTITY_UNITS) - set(entity["requested_operating_point"])),
                         "role_and_unit_semantics_independently_verified": False})
    return {"status": "blocked" if reasons or any(row["reasons"] for row in entities) else "checked",
            "reasons": reasons, "entities": entities, "static_model_check_status": static_report.get("status"),
            "coverage": copy.deepcopy(document["coverage"]), "model_warnings": copy.deepcopy(document.get("warnings", [])),
            "not_evaluated": ["electrical role and unit semantics", "slack/reference bus sufficiency", "island solvability",
                              "solver convergence", "machine/converter initialization completeness", "rack or Runtime readiness"]}


def semantic_diff(before, after):
    """Exact bounded stored-field diff with prohibited structural changes identified."""
    first, second = _component_map(before), _component_map(after)
    prohibited, changes = [], []
    for key in sorted(first.keys() | second.keys()):
        left, right = first.get(key), second.get(key)
        if left is None or right is None:
            prohibited.append({"kind": "component_added" if left is None else "component_removed", "identity": list(key)})
            continue
        for field in ("component_type", "location", "orientation", "mirrored", "declared_parameter_count", "parsed_parameter_count"):
            if left.get(field) != right.get(field):
                prohibited.append({"kind": "component_" + field + "_changed", "identity": list(key), "before": left.get(field), "after": right.get(field)})
        for parameter in sorted(left["parameters"].keys() | right["parameters"].keys()):
            old, new = left["parameters"].get(parameter), right["parameters"].get(parameter)
            if old != new:
                changes.append({"context": key[0], "component_id": key[1], "component_type": left["component_type"],
                                "parameter": parameter, "before_value": old, "after_value": new})
    same_topology = topology_signature(before) == topology_signature(after)
    if not same_topology:
        prohibited.append({"kind": "static_topology_changed"})
    for key in ("groups", "hierarchy_links", "ports", "segments"):
        if before.get(key, []) != after.get(key, []):
            prohibited.append({"kind": key + "_changed"})
    if before["source"].get("settings") != after["source"].get("settings"):
        prohibited.append({"kind": "project_settings_changed", "before": before["source"].get("settings"), "after": after["source"].get("settings")})
    truncated = len(changes) > MAX_DIFF or len(prohibited) > MAX_DIFF
    return {"parameter_changes": changes[:MAX_DIFF], "parameter_change_count": len(changes),
            "prohibited_changes": prohibited[:MAX_DIFF], "prohibited_change_count": len(prohibited),
            "same_static_topology": same_topology, "truncated": truncated,
            "comparison_identity_basis": "exact_context_and_uuid"}


def evaluate_supplied(request, supplied, before, after, archive_evidence):
    """Report consistency of caller-supplied states; no solver success is inferred."""
    validate_initialization(request)
    validate_supplied(supplied)
    if (supplied["initialization_plan_sha256"] != plan_sha256(request)
            or supplied["input_project_sha256"] != request["input_project_sha256"]
            or supplied["input_project_sha256"] != before["source"]["rtfx_sha256"]
            or supplied["after_project_sha256"] != after["source"]["rtfx_sha256"]):
        raise ValueError("Supplied initialization plan/model hash mismatch")
    entities = {row["entity_id"]: row for row in request["entities"]}
    states = {row["entity_id"]: row["operating_point"] for row in supplied["calculated_states"]}
    reasons = []
    if set(states) != set(entities):
        reasons.append("calculated_state_entities_do_not_match_declared_entities")
    bindings = {}
    for identity, entity in entities.items():
        if identity in states and set(states[identity]) != set(entity["requested_operating_point"]):
            reasons.append("calculated_quantities_do_not_match_explicit_bindings:" + identity)
        for binding in entity["parameter_bindings"]:
            key = (entity["context"], entity["component_id"], binding["calculated_parameter"])
            bindings[key] = (entity, binding)
            requested = entity["requested_operating_point"][binding["quantity"]]
            calculated = states.get(identity, {}).get(binding["quantity"])
            if calculated is not None and {k: v for k, v in requested.items() if k != "value"} != {k: v for k, v in calculated.items() if k != "value"}:
                reasons.append("calculated_state_unit_sign_or_base_mismatch:" + identity + ":" + binding["quantity"])
    diff = semantic_diff(before, after)
    def order(row):
        return row["context"], row["component_id"], row["parameter"]
    if sorted(supplied["parameter_changes"], key=order) != diff["parameter_changes"]:
        reasons.append("reported_parameter_changes_do_not_match_observed_changes")
    if diff["prohibited_change_count"] or diff["truncated"]:
        reasons.append("structural_or_unbounded_model_changes_are_unsupported")
    for change in supplied["parameter_changes"]:
        bound = bindings.get(order(change))
        if bound is None:
            reasons.append("changed_parameter_not_bound_to_declared_operating_quantity")
            continue
        entity, binding = bound
        calculated = states.get(entity["entity_id"], {}).get(binding["quantity"])
        if (change["component_type"] != entity["component_type"]
                or change["before_value"] != binding["expected_calculated_stored_value"]
                or calculated is None or _numeric_text(change["after_value"]) != calculated["value"]):
            reasons.append("changed_parameter_does_not_match_bound_initialization_state")
    after_components = _component_map(after)
    for entity in request["entities"]:
        component = after_components.get((entity["context"], entity["component_id"]))
        for binding in entity["parameter_bindings"]:
            calculated = states.get(entity["entity_id"], {}).get(binding["quantity"])
            if component is None or calculated is None or _numeric_text(component["parameters"].get(binding["calculated_parameter"])) != calculated["value"]:
                reasons.append("calculated_state_not_reflected_in_bound_after_parameter")
    if archive_evidence.get("non_dfx_unchanged") is not True:
        reasons.append("non_dfx_members_or_archive_identity_changed")
    if archive_evidence.get("dfx_changes_fully_accounted") is not True:
        reasons.append("dfx_contains_unexplained_or_unsupported_byte_changes")
    if archive_evidence.get("same_definition_and_companion_evidence") is not True:
        reasons.append("definition_or_companion_evidence_changed")
    return {"status": "inconsistent" if reasons else "consistent", "reasons": sorted(set(reasons)),
            "evidence_id": supplied["evidence_id"], "reported_convergence": copy.deepcopy(supplied["solver_report"]),
            "convergence_independently_verified": False, "python_return_used_as_convergence_evidence": False,
            "calculated_states": copy.deepcopy(supplied["calculated_states"]), "semantic_diff": diff,
            "archive_evidence": copy.deepcopy(archive_evidence), "calculated_state_provenance": "caller_supplied_hash_bound_artifact"}

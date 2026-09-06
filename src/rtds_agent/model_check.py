"""Static model rules with explicit coverage; no general engineering pass."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from typing import Any
from .project_tools import _document
from .safety import ToolSafetyError, sha256_file
from .input_contracts import validate
from .core.topology_parser import parse_parameter_schema
from .core.structured_patch import validate_new_value
from .initialization import InitializationRequest, inspect_initialization

FIELD = {"type": "object", "additionalProperties": False, "required": ["context", "component_id", "parameter", "units"],
         "properties": {"context": {"type": "string", "minLength": 1}, "component_id": {"type": "integer", "minimum": 0},
                        "parameter": {"type": "string", "minLength": 1}, "units": {"type": "string", "minLength": 1}}}
RULE = {"type": "object", "additionalProperties": False, "required": ["rule_id", "kind", "field", "provenance"],
        "properties": {"rule_id": {"type": "string", "minLength": 1}, "kind": {"enum": ["positive", "range", "equal", "ratio"]},
          "field": FIELD, "other": FIELD, "lower": {"type": "number"}, "upper": {"type": "number"},
          "expected": {"type": "number"}, "tolerance": {"type": "number", "minimum": 0},
          "provenance": {"type": "string", "minLength": 1, "maxLength": 1000}}}
RULES = {"type": "array", "maxItems": 64, "items": RULE}
from typing import Annotated
from pydantic import WithJsonSchema
ElectricalRules = Annotated[list[dict], WithJsonSchema(RULES)]


def check_document(document, electrical_rules=None):
    findings = []
    def finding(code, severity, component, evidence, cause, fix):
        findings.append({"finding": code, "severity": severity, "affected_component": component,
                         "evidence": evidence, "likely_cause": cause, "suggested_fix": fix, "autofix_available": False})
    identities = Counter((r["context"], r["uuid"]) for r in document["components"])
    for key, count in identities.items():
        if count > 1:
            finding("duplicate_identity", "error", list(key), {"count": count}, "Repeated context/UUID", "Resolve identity in an isolated model")
    schemas = {}
    for kind, ref in document.get("definition_evidence", {}).items():
        path = Path(ref["path"])
        raw = path.read_bytes()
        import hashlib
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise ToolSafetyError("Definition changed while checking model")
        schemas[kind] = parse_parameter_schema(raw.decode("utf-8-sig"))
    for row in document["components"]:
        identity = [row["context"], row["uuid"]]
        if row["declared_parameter_count"] != row["parsed_parameter_count"]:
            finding("parameter_count_mismatch", "error", identity, {"declared": row["declared_parameter_count"], "parsed": row["parsed_parameter_count"]}, "Incomplete or duplicate parameter records", "Inspect exact DFX record")
        schema = schemas.get(row["component_type"])
        if schema is None:
            continue
        for name, rule in schema.items():
            value = row["parameters"].get(name, rule["default"])
            if value is None:
                finding("missing_parameter_without_default", "warning", identity, {"parameter": name}, "No stored value or parsed default", "Consult definition for whether the parameter is required")
                continue
            try:
                if rule["data_type"] in {"INTEGER", "REAL"}:
                    validate_new_value(rule, str(value))
                elif rule["data_type"] == "TOGGLE" and str(value) not in (rule["enum_values"] or []):
                    # Definition defaults may be numeric selector indices; stored values must be exact labels.
                    if name in row["parameters"] or not str(value).isdigit() or int(value) >= len(rule["enum_values"] or []):
                        raise ValueError("Selector is outside declared labels")
            except ValueError as exc:
                symbolic = False
                if rule["data_type"] in {"INTEGER","REAL"}:
                    try: float(str(value))
                    except ValueError: symbolic = True
                finding("parameter_expression_unresolved" if symbolic else "parameter_value_invalid", "warning" if symbolic else "error", identity,
                        {"parameter": name, "value": value, "definition": document["definition_evidence"][row["component_type"]]},
                        "Symbolic numeric expression is not evaluated" if symbolic else str(exc), "Inspect the declared value and expression context")
    for net in document["nets"]:
        ports = [m for m in net["members"] if "port" in m]
        if len(ports) < 2:
            code = "potential_unconnected_port" if ports else "wire_without_parsed_port"
            finding(code, "warning", None, {"net_id": net["net_id"], "members": net["members"]}, "Static graph has fewer than two parsed endpoints", "Inspect hierarchy and intentional unused terminals before changing wires")
        data_types = {p["data_type"] for p in ports if p.get("data_type")}
        if len(data_types) > 1:
            finding("incompatible_declared_signal_types", "error", None, {"net_id": net["net_id"], "types": sorted(data_types)}, "Connected ports declare different signal types", "Review an explicit conversion component")
        if sum(p.get("direction") == "OUTPUT" for p in ports) > 1:
            finding("multiple_signal_drivers", "warning", None, {"net_id": net["net_id"]}, "Multiple declared OUTPUT ports share one net", "Verify supported multi-driver semantics")
        from .core.topology_parser import point_on_segment
        segments = [m for m in net["members"] if "start" in m]
        for segment in segments:
            for endpoint in (segment["start"],segment["end"]):
                attached = any(p["coordinate"] == endpoint for p in ports) or any(other is not segment and
                    point_on_segment(tuple(endpoint),tuple(other["start"]),tuple(other["end"])) for other in segments)
                if not attached:
                    finding("potential_dangling_wire_endpoint","warning",[segment["context"],segment["component_id"]],
                            {"coordinate":endpoint,"net_id":net["net_id"]},"No parsed port or adjacent segment touches this endpoint","Verify intentional geometry and hierarchy before rewiring")
    for warning in document["warnings"]:
        finding("parser_coverage", "warning", None, {"warning": warning}, "Unsupported or unresolved static syntax", "Read the definition/API; do not infer missing connections")
    rules = electrical_rules or []
    validate({"rules": rules}, {"type": "object", "properties": {"rules": RULES}})
    if len({r["rule_id"] for r in rules}) != len(rules):
        raise ToolSafetyError("Duplicate electrical rule ID")
    results = []
    def field_value(field):
        matches = [c for c in document["components"] if c["uuid"] == field["component_id"] and c["context"] == field["context"]]
        if len(matches) != 1:
            raise ValueError("Electrical field identity is unresolved or ambiguous")
        c = matches[0]
        schema = schemas.get(c["component_type"], {}).get(field["parameter"])
        if not schema or schema["data_type"] not in {"REAL", "INTEGER"} or schema["unit"] != field["units"]:
            raise ValueError("Electrical field numeric type/units are not verified")
        value = c["parameters"].get(field["parameter"], schema["default"])
        validate_new_value(schema, str(value))
        return float(value)
    for rule in rules:
        kind = rule["kind"]
        required = {"range": {"lower", "upper"}, "equal": {"other", "tolerance"}, "ratio": {"other", "expected", "tolerance"}, "positive": set()}[kind]
        if (set(rule) - {"rule_id", "kind", "field", "provenance"}) != required:
            raise ToolSafetyError("Electrical rule fields do not match its kind")
        if kind == "range" and rule["lower"] > rule["upper"]:
            raise ToolSafetyError("Electrical range is reversed")
        result = {"rule_id": rule["rule_id"], "criterion": rule, "status": "inconclusive", "provenance_authenticated": False}
        try:
            value = field_value(rule["field"])
            if kind == "positive": passed = value > 0
            elif kind == "range": passed = rule["lower"] <= value <= rule["upper"]
            else:
                other = field_value(rule["other"])
                if rule["field"]["units"] != rule["other"]["units"]:
                    raise ValueError("No implicit electrical unit conversion")
                if kind == "equal": passed = abs(value-other) <= rule["tolerance"]
                else:
                    if other == 0: raise ValueError("Zero denominator in ratio")
                    passed = abs(value/other-rule["expected"]) <= rule["tolerance"]
            result.update(status="passed" if passed else "failed", value=value)
            if not passed:
                finding("explicit_electrical_rule_failed", "error", rule["field"], {"criterion": rule, "value": value}, "Value violates the supplied rule", "Review source-backed engineering intent; no automatic correction")
        except (ValueError, OverflowError) as exc:
            result["reason"] = str(exc)
        results.append(result)
    return {"status": "errors_found" if any(f["severity"] == "error" for f in findings) else "no_errors_in_checked_scope",
            "findings": findings, "electrical_rules": results, "coverage": document["coverage"],
            "not_evaluated": ["electrical meaning without explicit rules", "required/optional parameter semantics", "placement restrictions",
                "RTDS timestep/subsystem/processor/rack hardware allocation", "native compile", "dynamic stability"],
            "engineering_verdict": "not_evaluated", "automatic_repairs": False, "live_calls_made": False}


def check_rscad_model(project_path: str, snapshot_id: str | None = None,
                      electrical_rules: ElectricalRules | None = None,
                      initialization: InitializationRequest | None = None) -> dict[str, Any]:
    """Check static rules and optional declared/supplied initialization evidence without live calls."""
    _, _, document = _document(project_path, snapshot_id)
    result = check_document(document, electrical_rules)
    if initialization is not None:
        result['initialization'] = inspect_initialization(project_path, document['snapshot_id'], initialization)
    _document(project_path, document["snapshot_id"])
    return {**result, "snapshot_id": document["snapshot_id"], "source": document["source"]}

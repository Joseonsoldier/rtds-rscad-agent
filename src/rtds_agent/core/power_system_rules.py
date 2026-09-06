"""Bounded caller-declared mathematical checks; no engineering or execution authority."""
from __future__ import annotations

from collections import Counter
import copy
import json
import math
import re

from ..input_contracts import schema, validate
from .state_machine import sha256_json


RULEPACK_SCHEMA = schema("power_system_rulepacks.schema.json")
DOMAINS = ("source", "transformer", "line", "synchronous_machine", "induction_machine", "converter", "gfm", "gfl", "bess", "protection")
VOLTAGE = {"voltage_ll_rms", "voltage_phase_rms", "voltage_dc"}
POWER = {"active_power", "reactive_power", "apparent_power"}
CURRENT = {"current_rms", "current_dc"}
PU_UNITS = {"pu", "p.u.", "p.u"}
UNARY = {
    "positive_voltage": (VOLTAGE, "value > 0"),
    "positive_frequency": ({"frequency"}, "value > 0"),
    "nonnegative_frequency": ({"frequency"}, "value >= 0"),
    "positive_rating": (POWER | CURRENT, "value > 0"),
    "positive_energy": ({"energy"}, "value > 0"),
    "positive_leakage_reactance": ({"reactance"}, "value > 0"),
    "nonnegative_resistance": ({"resistance"}, "value >= 0"),
}
EQUALITY = {"nominal_voltage_match": VOLTAGE, "frequency_match": {"frequency"}, "rating_match": POWER | CURRENT}
ORDERING = {"rating_relationship": POWER, "current_limit_consistency": CURRENT, "time_coordination": {"time"}}
UNITS = {
    **{quantity: {"V", "kV", "mV", "pu"} for quantity in VOLTAGE},
    **{quantity: {"A", "kA", "mA", "pu"} for quantity in CURRENT},
    "frequency": {"Hz", "Hertz", "kHz", "pu"}, "active_power": {"W", "kW", "MW", "pu"},
    "reactive_power": {"var", "kvar", "Mvar", "MVAR", "pu"},
    "apparent_power": {"VA", "kVA", "MVA", "pu"},
    **{quantity: {"ohm", "Ohm", "Ohms", "pu"} for quantity in ("resistance", "reactance", "impedance")},
    "dimensionless": {"1", "pu"}, "time": {"s", "ms", "us", "pu"}, "energy": {"J", "kJ", "Wh", "kWh", "MWh", "pu"},
}
UNITS = {quantity: units | PU_UNITS for quantity, units in UNITS.items()}
SI_FACTORS = {"W": 1.0, "kW": 1000.0, "MW": 1000000.0, "var": 1.0, "kvar": 1000.0,
              "Mvar": 1000000.0, "MVAR": 1000000.0, "VA": 1.0, "kVA": 1000.0, "MVA": 1000000.0,
              "V": 1.0, "kV": 1000.0, "mV": 0.001, "A": 1.0, "kA": 1000.0, "mA": 0.001}
FLAGS = {"source_interpretation_verified": False, "applicability_verified": False,
         "integration_qualified": False, "engineering_verdict": "not_evaluated", "automatic_repairs": False,
         "live_calls_made": False, "execution_authorized": False}
OBSERVATION_KEYS = {"status", "reason", "value", "quantity", "units", "basis", "pu_base", "origin", "evidence"}
METADATA = ("quantity", "units", "basis", "pu_base", "origin")


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _json_safe(value, bound=100000):
    try:
        return len(json.dumps(value, allow_nan=False)) <= bound
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def rulepack_catalog():
    """Fixed algorithm metadata; domains are declared organizational scope only."""
    checks = {}
    for name, (quantities, formula) in UNARY.items():
        checks[name] = {"inputs": ["value"], "quantities": sorted(quantities), "formula": formula,
                        "required_assumptions": ["declared_ac_operation"] if name == "positive_frequency" else []}
    for name, quantities in EQUALITY.items():
        checks[name] = {"inputs": ["left", "right"], "quantities": sorted(quantities), "formula": "abs(left - right) <= absolute_tolerance", "required_assumptions": []}
    for name, quantities in ORDERING.items():
        checks[name] = {"inputs": ["left", "right"], "quantities": sorted(quantities), "formula": "left + absolute_tolerance >= right, or left <= right + absolute_tolerance, as declared", "required_assumptions": []}
    checks["turns_ratio"] = {"inputs": ["numerator", "denominator"], "quantities": sorted(VOLTAGE | {"dimensionless"}), "formula": "abs(numerator / denominator - expected) <= absolute_tolerance", "required_assumptions": []}
    checks['turns_ratio']['interpretation_scope'] = ('Only a declared numeric or rated-voltage ratio is checked. '
        'Physical winding turns ratio, vector group, phase shift and tap effects are not established.')
    checks["apparent_power_rating"] = {"inputs": ["p", "q", "s"], "quantities": ["active_power", "reactive_power", "apparent_power"], "formula": "hypot(p, q) <= s + absolute_tolerance; s > 0", "required_assumptions": []}
    checks["power_current_rating"] = {"inputs": ["p", "q", "v", "i"], "quantities": ["active_power", "reactive_power", "voltage_ll_rms", "current_rms"], "formula": "hypot(P_SI, Q_SI) <= sqrt(3) * V_LL_RMS_SI * I_RMS_SI + absolute_tolerance_VA; v > 0 and i > 0", "required_assumptions": ["balanced_three_phase_sinusoidal"]}
    for check in checks.values():
        check["algorithm_provenance"] = "agent_defined_mathematical_check"
    return {"schema_version": "1.0", "domains": list(DOMAINS), "checks": checks,
            "scope": "Explicit caller-selected design criteria. Domain labels do not select components or establish parameter meaning, nominal values, AC operation, physical ratings or official requirements.",
            "comparison_units": "Exact quantity, units, basis and pu_base for pair comparisons. Nonlinear power checks require physical units and identical declared basis; no pu conversion.",
            **FLAGS}


def validate_rulepacks(request):
    validate(request, RULEPACK_SCHEMA)
    pack_ids, physical_declarations = set(), {}
    total = 0
    for pack in request["packs"]:
        if pack["pack_id"] in pack_ids:
            raise ValueError("Duplicate rule pack ID")
        pack_ids.add(pack["pack_id"])
        binding_ids, targets, rules = set(), set(), set()
        for binding in pack["bindings"]:
            if type(binding["component_id"]) is not int:
                raise ValueError("Component identity must be an integer")
            identity = (binding["context"], binding["component_id"], binding["parameter"])
            if binding["binding_id"] in binding_ids or identity in targets:
                raise ValueError("Duplicate binding ID or physical parameter identity within pack")
            binding_ids.add(binding["binding_id"])
            targets.add(identity)
            declaration = {key: value for key, value in binding.items() if key != "binding_id"}
            if identity in physical_declarations and physical_declarations[identity] != declaration:
                raise ValueError("Contradictory declarations of the same physical parameter")
            physical_declarations[identity] = declaration
            selector_names = [row["parameter"] for row in binding["selectors"]]
            if len(selector_names) != len(set(selector_names)):
                raise ValueError("Duplicate selector parameter identity")
            if binding["pu_base"] is not None and not _finite(binding["pu_base"]["value"]):
                raise ValueError("Per-unit base must be a positive finite number")
        for rule in pack["rules"]:
            if rule["rule_id"] in rules:
                raise ValueError("Duplicate rule ID within pack")
            rules.add(rule["rule_id"])
            if not set(rule["inputs"].values()) <= binding_ids:
                raise ValueError("Rule references an absent exact binding ID")
            used_ids = set(rule["inputs"].values())
            required_hashes = {row["definition_sha256"] for row in pack["bindings"] if row["binding_id"] in used_ids}
            if not required_hashes <= {row["source_sha256"] for row in rule["source"]}:
                raise ValueError("Rule source must pin every used definition hash")
            for value in rule["limits"].values():
                if not isinstance(value, str) and not _finite(value):
                    raise ValueError("Rule limits must be finite numbers, not booleans")
            if len({(ref["source_path"], ref["source_sha256"], ref["locator"]) for ref in rule["source"]}) != len(rule["source"]):
                raise ValueError("Duplicate rule source reference")
        total += len(pack["rules"])
    if total > 128:
        raise ValueError("At most 128 explicitly selected rules are supported")
    return request


def _observation(binding, raw, project_sha256):
    """Malformed observation data is inconclusive, never converted into a passing value."""
    output = {"binding": copy.deepcopy(binding), "observation": None}
    if not isinstance(raw, dict) or set(raw) != OBSERVATION_KEYS or not _json_safe(raw):
        return output, "Missing, malformed or nonfinite binding observation"
    output["observation"] = copy.deepcopy(raw)
    if raw["status"] != "resolved" or raw["reason"] is not None:
        return output, "Binding unresolved: " + str(raw.get("reason"))[:1000]
    if any(raw[key] != binding[key] for key in METADATA):
        return output, "Observation metadata contradicts the exact declared binding"
    if not isinstance(raw["evidence"], list) or not 1 <= len(raw["evidence"]) <= 32 or not all(isinstance(row, dict) and row for row in raw["evidence"]):
        return output, "Resolved binding requires bounded explicit input evidence"
    for ref in raw["evidence"]:
        if not all(isinstance(ref.get(key), str) and ref[key].strip() and len(ref[key]) <= maximum for key, maximum in (("source_path", 4000), ("source_sha256", 64), ("locator", 1000))) or not re.fullmatch("[0-9a-f]{64}", ref["source_sha256"]):
            return output, "Input evidence requires bounded source path, hash and locator"
    if not any(ref["source_sha256"] == binding["definition_sha256"] for ref in raw["evidence"]):
        return output, "Input evidence does not pin the declared definition hash"
    if not any(ref['source_sha256'] == project_sha256 for ref in raw['evidence']):
        return output, 'Input evidence does not pin the requested project hash'
    if not _finite(raw["value"]):
        return output, "Observation does not contain a finite numeric value"
    try:
        expected = float(binding["expected_value"])
    except (ValueError, OverflowError):
        return output, "Expected raw value is symbolic or unsupported"
    if not math.isfinite(expected) or raw["value"] != expected:
        return output, "Numeric observation contradicts the pinned raw value"
    if binding["units"] not in UNITS[binding["quantity"]]:
        return output, "Unit is unsupported for the explicitly declared quantity"
    base = binding["pu_base"]
    if base is not None and base["units"] not in UNITS[binding["quantity"]] - PU_UNITS:
        return output, "Per-unit base unit is unsupported for the declared quantity"
    return output, None


def _compare(check, inputs, limits):
    rows = {slot: evidence["observation"] for slot, evidence in inputs.items()}
    values = {slot: row["value"] for slot, row in rows.items()}
    computed = {"values": values}
    if check in UNARY:
        quantities, criterion = UNARY[check]
        if rows["value"]["quantity"] not in quantities:
            return "inconclusive", "Declared quantity does not match check", computed, criterion
        passed = values["value"] >= 0 if check in {"nonnegative_resistance", "nonnegative_frequency"} else values["value"] > 0
        return "passed" if passed else "failed", "Evaluated only the declared numeric criterion", computed, criterion
    tolerance = limits["absolute_tolerance"]
    if check in EQUALITY or check in ORDERING or check == "turns_ratio":
        a, b = ("numerator", "denominator") if check == "turns_ratio" else ("left", "right")
        allowed = VOLTAGE | {"dimensionless"} if check == "turns_ratio" else EQUALITY.get(check, ORDERING.get(check))
        if rows[a]["quantity"] not in allowed or any(rows[a][key] != rows[b][key] for key in ("quantity", "units", "basis", "pu_base")):
            return "inconclusive", "Comparison requires supported identical quantities, exact units, basis and per-unit base", computed, None
        if check == "turns_ratio":
            criterion = "abs(numerator / denominator - expected) <= absolute_tolerance; numerator > 0 and denominator > 0"
            if values[a] <= 0 or values[b] <= 0:
                return "failed", "Declared ratio inputs must both be positive", computed, criterion
            computed["ratio"] = values[a] / values[b]
            computed["absolute_error"] = abs(computed["ratio"] - limits["expected"])
            passed = computed["absolute_error"] <= tolerance
        elif check in EQUALITY:
            criterion = "abs(left - right) <= absolute_tolerance"
            computed["absolute_error"] = abs(values[a] - values[b])
            passed = computed["absolute_error"] <= tolerance
        else:
            criterion = "left + absolute_tolerance >= right" if limits["relation"] == "at_least" else "left <= right + absolute_tolerance"
            computed["difference"] = values[a] - values[b]
            passed = computed["difference"] >= -tolerance if limits["relation"] == "at_least" else computed["difference"] <= tolerance
        return "passed" if passed else "failed", "Evaluated only the declared numeric criterion", computed, criterion
    expected_quantities = {"p": "active_power", "q": "reactive_power", **({"s": "apparent_power"} if check == "apparent_power_rating" else {"v": "voltage_ll_rms", "i": "current_rms"})}
    if any(rows[slot]["quantity"] != quantity for slot, quantity in expected_quantities.items()) or any(row["units"] in PU_UNITS for row in rows.values()):
        return "inconclusive", "Nonlinear power checks require exact physical quantity types; per-unit mapping is unsupported", computed, None
    if len({row["basis"] for row in rows.values()}) != 1:
        return "inconclusive", "Nonlinear power checks require an identical declared reference basis", computed, None
    if check == "apparent_power_rating":
        triplet = tuple(rows[slot]["units"] for slot in ("p", "q", "s"))
        if triplet not in {("W", "var", "VA"), ("kW", "kvar", "kVA"), ("MW", "Mvar", "MVA"), ("MW", "MVAR", "MVA")}:
            return "inconclusive", "Unsupported physical power unit triplet; no implicit unit mapping", computed, None
        criterion = "hypot(p, q) <= s + absolute_tolerance; s > 0"
        if values["s"] <= 0:
            return "failed", "Declared apparent-power rating must be positive independently of tolerance", computed, criterion
        computed.update(apparent_power=math.hypot(values["p"], values["q"]), rating=values["s"], tolerance_units=rows["s"]["units"])
        passed = computed["apparent_power"] - values["s"] <= tolerance
    else:
        criterion = "hypot(P_SI, Q_SI) <= sqrt(3) * V_LL_RMS_SI * I_RMS_SI + absolute_tolerance_VA; v > 0 and i > 0"
        if values["v"] <= 0 or values["i"] <= 0:
            return "failed", "Declared voltage and current ratings must be positive independently of tolerance", computed, criterion
        factors = {slot: SI_FACTORS[row["units"]] for slot, row in rows.items()}
        converted = {slot: values[slot] * factor for slot, factor in factors.items()}
        computed.update(si_factors=factors, si_values=converted, apparent_power_va=math.hypot(converted["p"], converted["q"]), current_rating_va=math.sqrt(3.0) * converted["v"] * converted["i"], tolerance_units="VA")
        passed = computed["apparent_power_va"] - computed["current_rating_va"] <= tolerance
    return "passed" if passed else "failed", "Evaluated only the declared numeric criterion", computed, criterion


def evaluate_rulepacks(request, observations):
    """Evaluate only explicitly mapped values; source reading and selector resolution are caller seams."""
    validate_rulepacks(request)
    if not isinstance(observations, dict) or len(observations) > 320:
        raise ValueError("Observations must be a bounded mapping keyed by (pack_id, binding_id)")
    results = []
    catalog = rulepack_catalog()
    for pack in request["packs"]:
        bindings = {row["binding_id"]: row for row in pack["bindings"]}
        for rule in pack["rules"]:
            inputs, problems = {}, []
            for slot, binding_id in rule["inputs"].items():
                evidence, problem = _observation(bindings[binding_id], observations.get((pack["pack_id"], binding_id)), request['input_project_sha256'])
                inputs[slot] = evidence
                if problem:
                    problems.append(slot + ": " + problem)
            status, reason, computed, criterion = "inconclusive", "; ".join(problems), None, None
            if not problems:
                try:
                    status, reason, computed, criterion = _compare(rule["check"], inputs, rule["limits"])
                    if not _json_safe(computed):
                        status, reason, computed = "inconclusive", "Arithmetic exceeds the supported finite numeric range", None
                except (OverflowError, ZeroDivisionError):
                    status, reason, computed = "inconclusive", "Arithmetic exceeds the supported finite numeric range", None
            results.append({"pack_id": pack["pack_id"], "domain": pack["domain"], **copy.deepcopy(rule),
                            "inputs": inputs, "status": status, "reason": reason, "computed": computed, "criterion": criterion,
                            "interpretation_scope": catalog['checks'][rule['check']].get('interpretation_scope', 'Only the explicitly declared mathematical criterion is checked.'),
                            "algorithm_provenance": "agent_defined_mathematical_check", **FLAGS})
    counts = Counter(row["status"] for row in results)
    errors = sum(row["status"] == "failed" and row["severity"] == "error" for row in results)
    warnings = sum(row["status"] == "failed" and row["severity"] == "warning" for row in results)
    infos = sum(row["status"] == "failed" and row["severity"] == "info" for row in results)
    overall = "errors_found" if errors else "warnings_found" if warnings or infos else "inconclusive" if counts["inconclusive"] else "no_violations_in_declared_scope"
    return {"schema_version": "1.0", "input_project_sha256": request["input_project_sha256"], "request_sha256": sha256_json(request),
            "catalog_sha256": sha256_json(catalog), "algorithm_provenance": "agent_defined_mathematical_check",
            "status": overall, "counts": {"rules": len(results), "passed": counts["passed"], "failed": counts["failed"], "inconclusive": counts["inconclusive"],
                                           "errors": errors, "warnings": warnings, "infos": infos},
            "rules": results, **FLAGS}

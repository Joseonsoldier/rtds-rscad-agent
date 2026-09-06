"""Synthetic mathematical rule tests; no model, SDK or execution access."""
import test_environment
import copy
import math
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

from rtds_agent.core.power_system_rules import RULEPACK_SCHEMA, evaluate_rulepacks, rulepack_catalog, validate_rulepacks


def source(digest="d" * 64):
    return {"source_path": "C:/synthetic/definition", "source_sha256": digest, "locator": "Synthetic parameter declaration"}


def binding(name="a", value="1", quantity="voltage_ll_rms", units="kV", **changes):
    row = {"binding_id": name, "context": "subsystem:0", "component_id": 1, "component_type": "synthetic",
           "definition_sha256": "d" * 64, "parameter": name, "expected_value": str(value), "origin": "stored",
           "quantity": quantity, "units": units, "basis": "Declared common system basis", "pu_base": None, "selectors": []}
    row.update(changes)
    return row


def rule(check="positive_voltage", inputs=None, limits=None, **changes):
    row = {"rule_id": "rule1", "check": check, "inputs": inputs or {"value": "a"}, "limits": {} if limits is None else limits,
           "source": [source()], "scope": "Synthetic declared criterion only", "severity": "error",
           "confidence": {"level": "high", "rationale": "Caller-declared synthetic criterion"}, "assumptions": []}
    row.update(changes)
    return row


def request(bindings=None, selected=None, domain="source"):
    return {"schema_version": "1.0", "input_project_sha256": "a" * 64,
            "packs": [{"pack_id": "pack1", "domain": domain, "bindings": bindings or [binding()], "rules": [selected or rule()]}]}


def observations(req):
    return {(pack["pack_id"], b["binding_id"]): {"status": "resolved", "reason": None, "value": float(b["expected_value"]),
            **{key: copy.deepcopy(b[key]) for key in ("quantity", "units", "basis", "pu_base", "origin")},
            "evidence": [{**source(b["definition_sha256"]), "observed": {"parameter": b["parameter"], "raw_value": b["expected_value"], "selectors": b["selectors"]}},
                         {'source_path': 'C:/synthetic/project.rtfx', 'source_sha256': req['input_project_sha256'], 'locator': 'Authored saved project'}]}
            for pack in req["packs"] for b in pack["bindings"]}


def assess(req):
    return evaluate_rulepacks(req, observations(req))


def pair(check, left=1, right=1, quantity="voltage_ll_rms", units="kV", **limits):
    return request([binding("a", left, quantity, units), binding("b", right, quantity, units)],
                   rule(check, {"left": "a", "right": "b"}, {"absolute_tolerance": 0, **limits}))


class PowerSystemRuleContractTests(unittest.TestCase):
    def test_fixed_catalog_and_schema_are_strict_advisory_and_nonmutating(self):
        Draft202012Validator.check_schema(RULEPACK_SCHEMA)
        catalog = rulepack_catalog()
        self.assertEqual(len(catalog["domains"]), 10)
        self.assertEqual(len(catalog["checks"]), 16)
        req = request()
        obs = observations(req)
        original = copy.deepcopy((req, obs))
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("No source I/O")):
            first = evaluate_rulepacks(req, obs)
            self.assertEqual(first, evaluate_rulepacks(req, obs))
        self.assertEqual((req, obs), original)
        for row in (first, first["rules"][0], catalog):
            for key in ("source_interpretation_verified", "applicability_verified", "integration_qualified", "automatic_repairs", "live_calls_made", "execution_authorized"):
                self.assertIs(row[key], False)
            self.assertEqual(row["engineering_verdict"], "not_evaluated")
        self.assertEqual(first["rules"][0]["source"], req["packs"][0]["rules"][0]["source"])

    def test_unknown_domain_check_custom_code_and_authority_fields_are_rejected(self):
        mutations = [lambda r: r.update(execute=True), lambda r: r["packs"][0].update(domain="automatic"),
                     lambda r: r["packs"][0]["rules"][0].update(check="eval"),
                     lambda r: r["packs"][0]["rules"][0].update(code="1+1"),
                     lambda r: r["packs"][0]["rules"][0].update(official_rtds_requirement=True),
                     lambda r: r["packs"][0]["bindings"][0].update(origin="inferred")]
        for mutate in mutations:
            req = request(); mutate(req)
            with self.subTest(req=req), self.assertRaises(ValueError):
                validate_rulepacks(req)

    def test_exact_ids_unique_bindings_selectors_and_source_pins(self):
        mutations = [lambda p: p["bindings"].append(copy.deepcopy(p["bindings"][0])),
                     lambda p: p["rules"].append(copy.deepcopy(p["rules"][0])),
                     lambda p: p["rules"][0]["inputs"].update(value="absent"),
                     lambda p: p["rules"][0].update(source=[source("e" * 64)]),
                     lambda p: p["bindings"][0].update(selectors=[{"parameter": "Mode", "expected_value": "Yes"}] * 2),
                     lambda p: p["bindings"][0].update(component_id=True)]
        for mutate in mutations:
            req = request(); mutate(req["packs"][0])
            with self.subTest(req=req), self.assertRaises(ValueError):
                validate_rulepacks(req)
        req = request(); req["packs"].append(copy.deepcopy(req["packs"][0]))
        with self.assertRaises(ValueError): validate_rulepacks(req)
        req["packs"][1]["pack_id"] = "pack2"
        req["packs"][1]["bindings"][0]["quantity"] = "voltage_dc"
        with self.assertRaisesRegex(ValueError, "Contradictory"):
            validate_rulepacks(req)

    def test_nan_infinity_boolean_negative_tolerances_and_missing_assumptions(self):
        for value in (float("nan"), float("inf"), True, -0.1):
            req = pair("nominal_voltage_match", absolute_tolerance=value)
            with self.subTest(value=value), self.assertRaises(ValueError): validate_rulepacks(req)
        req = request([binding(quantity="frequency", units="Hz")], rule("positive_frequency"))
        with self.assertRaises(ValueError): validate_rulepacks(req)
        req["packs"][0]["rules"][0]["assumptions"] = ["declared_ac_operation"]
        self.assertEqual(assess(req)["rules"][0]["status"], "passed")

    def test_per_unit_requires_positive_physical_base_and_nonpu_forbids_it(self):
        for base in (None, {"value": 0, "units": "kV"}, {"value": True, "units": "kV"}):
            with self.subTest(base=base), self.assertRaises(ValueError):
                validate_rulepacks(request([binding(units="pu", pu_base=base)]))
        with self.assertRaises(ValueError):
            validate_rulepacks(request([binding(pu_base={"value": 10, "units": "kV"})]))
        req = request([binding(units="pu", pu_base={"value": 10, "units": "MW"})])
        self.assertEqual(assess(req)["rules"][0]["status"], "inconclusive")

    def test_observed_unit_spellings_are_supported_without_silent_normalization(self):
        for spelling in ("pu", "p.u.", "p.u"):
            with self.assertRaises(ValueError):
                validate_rulepacks(request([binding(units=spelling)]))
            req = pair("nominal_voltage_match", units=spelling)
            for b in req["packs"][0]["bindings"]:
                b["pu_base"] = {"value": 10, "units": "kV"}
            self.assertEqual(assess(req)["status"], "no_violations_in_declared_scope")
            req["packs"][0]["bindings"][1]["units"] = "p.u." if spelling == "pu" else "pu"
            self.assertEqual(assess(req)["status"], "inconclusive")
        req = pair("frequency_match", quantity="frequency", units="Hertz")
        self.assertEqual(assess(req)["status"], "no_violations_in_declared_scope")
        req["packs"][0]["bindings"][1]["units"] = "Hz"
        self.assertEqual(assess(req)["status"], "inconclusive")
        self.assertEqual(assess(request([binding(value=0, quantity="resistance", units="Ohms")], rule("nonnegative_resistance")))["status"], "no_violations_in_declared_scope")

    def test_total_rule_and_json_bounds(self):
        req = request()
        req["packs"] = [{**copy.deepcopy(req["packs"][0]), "pack_id": f"p{i}"} for i in range(5)]
        for pack in req["packs"]:
            pack["rules"] = [{**rule(), "rule_id": f"r{i}"} for i in range(26)]
        with self.assertRaisesRegex(ValueError, "128"):
            validate_rulepacks(req)
        req = request(); req["packs"][0]["rules"][0]["scope"] = "x" * 100001
        with self.assertRaisesRegex(ValueError, "100,000"):
            validate_rulepacks(req)


class PowerSystemRuleEvaluationTests(unittest.TestCase):
    def test_observations_cannot_be_relabelled_as_a_different_project(self):
        req = request()
        observed = observations(req)
        req['input_project_sha256'] = 'b' * 64
        result = evaluate_rulepacks(req, observed)
        self.assertEqual(result['counts']['inconclusive'], 1)
        self.assertIn('project hash', result['rules'][0]['reason'])

    def test_explicit_zero_permitting_and_positive_criteria(self):
        for check, quantity, units, expected in (("nonnegative_frequency", "frequency", "Hz", "passed"),
                                                ("nonnegative_resistance", "resistance", "ohm", "passed"),
                                                ("positive_leakage_reactance", "reactance", "ohm", "failed"),
                                                ("positive_voltage", "voltage_ll_rms", "kV", "failed"),
                                                ("positive_rating", "apparent_power", "MVA", "failed"),
                                                ("positive_energy", "energy", "MWh", "failed")):
            with self.subTest(check=check):
                self.assertEqual(assess(request([binding(value=0, quantity=quantity, units=units)], rule(check)))["rules"][0]["status"], expected)

    def test_missing_unresolved_selector_nonnumeric_nonfinite_and_no_evidence_are_inconclusive(self):
        req = request()
        bad = [None, {"status": "resolved"}]
        original = observations(req)[("pack1", "a")]
        bad += [{**original, **change} for change in ({"status": "unresolved", "reason": "selector mismatch"}, {"value": "1"},
                {"value": True}, {"value": float("nan")}, {"value": 2}, {"evidence": []}, {"evidence": [{"invented": True}]},
                {"origin": "definition_default"}, {"units": "V"}, {"reason": "not resolved"})]
        for observation in bad:
            result = evaluate_rulepacks(req, {("pack1", "a"): observation})
            self.assertEqual(result["status"], "inconclusive")
            self.assertEqual(result["rules"][0]["status"], "inconclusive")
        req["packs"][0]["bindings"][0]["expected_value"] = "Gain * 2"
        self.assertEqual(evaluate_rulepacks(req, {("pack1", "a"): original})["status"], "inconclusive")

    def test_pairwise_comparisons_require_exact_quantity_unit_basis_and_base(self):
        for change in ({"units": "V"}, {"quantity": "voltage_phase_rms"}, {"basis": "Other reference"}):
            req = pair("nominal_voltage_match")
            req["packs"][0]["bindings"][1].update(change)
            self.assertEqual(assess(req)["status"], "inconclusive")
        req = pair("nominal_voltage_match", units="pu")
        for index, b in enumerate(req["packs"][0]["bindings"]):
            b["pu_base"] = {"value": 10 + index, "units": "kV"}
        self.assertEqual(assess(req)["status"], "inconclusive")
        req["packs"][0]["bindings"][1]["pu_base"]["value"] = 10
        self.assertEqual(assess(req)["status"], "no_violations_in_declared_scope")

    def test_equal_zero_is_only_equality_not_implicit_positivity(self):
        req = pair("frequency_match", 0, 0, quantity="frequency", units="Hz")
        self.assertEqual(assess(req)["status"], "no_violations_in_declared_scope")
        for difference, expected in ((0.125, "passed"), (0.25, "failed")):
            req = pair("nominal_voltage_match", 1, 1 + difference, absolute_tolerance=0.125)
            self.assertEqual(assess(req)["rules"][0]["status"], expected)

    def test_declared_ordering_relations_and_domain_labels_do_not_add_rules(self):
        for check, quantity, units in (("rating_relationship", "apparent_power", "MVA"), ("current_limit_consistency", "current_rms", "A"), ("time_coordination", "time", "s")):
            for relation, expected in (("at_least", "passed"), ("at_most", "failed")):
                req = pair(check, 2, 1, quantity, units, relation=relation)
                self.assertEqual(assess(req)["rules"][0]["status"], expected)
        for domain in rulepack_catalog()["domains"]:
            req = request(domain=domain)
            self.assertEqual(assess(req)["counts"]["rules"], 1)

    def test_turns_ratio_zero_and_negative_denominators_fail_without_tolerance_escape(self):
        for numerator, denominator, expected in ((10, 2, "passed"), (10, 0, "failed"), (-10, -2, "failed"), (10, -2, "failed")):
            req = request([binding("a", numerator), binding("b", denominator)],
                          rule("turns_ratio", {"numerator": "a", "denominator": "b"}, {"expected": 5, "absolute_tolerance": 0}))
            self.assertEqual(assess(req)["rules"][0]["status"], expected)
            self.assertIn('Physical winding turns ratio', assess(req)['rules'][0]['interpretation_scope'])

    def test_apparent_power_rating_exact_triplets_signs_and_positive_rating(self):
        for units in (("W", "var", "VA"), ("kW", "kvar", "kVA"), ("MW", "MVAR", "MVA"), ("MW", "Mvar", "MVA")):
            req = request([binding("p", -3, "active_power", units[0]), binding("q", -4, "reactive_power", units[1]), binding("s", 5, "apparent_power", units[2])],
                          rule("apparent_power_rating", {"p": "p", "q": "q", "s": "s"}, {"absolute_tolerance": 0}))
            result = assess(req)["rules"][0]
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["computed"]["apparent_power"], 5)
            for rating in (0, -10):
                req["packs"][0]["bindings"][2]["expected_value"] = str(rating)
                req["packs"][0]["rules"][0]["limits"]["absolute_tolerance"] = 10000
                self.assertEqual(assess(req)["rules"][0]["status"], "failed")

    def test_power_nonlinear_no_pu_or_mixed_triplet_mapping(self):
        req = request([binding("p", 3, "active_power", "MW"), binding("q", 4, "reactive_power", "kvar"), binding("s", 5, "apparent_power", "MVA")],
                      rule("apparent_power_rating", {"p": "p", "q": "q", "s": "s"}, {"absolute_tolerance": 0}))
        self.assertEqual(assess(req)["status"], "inconclusive")
        for spelling in ("pu", "p.u.", "p.u"):
            changed = copy.deepcopy(req)
            for b in changed["packs"][0]["bindings"]:
                b["pu_base"] = {"value": 1, "units": b["units"]}; b["units"] = spelling
            self.assertEqual(assess(changed)["status"], "inconclusive")

    def test_balanced_three_phase_power_current_uses_explicit_rms_types_and_si_factors(self):
        req = request([binding("p", 3, "active_power", "MW"), binding("q", 4, "reactive_power", "MVAR"),
                       binding("v", 10, "voltage_ll_rms", "kV"), binding("i", 1, "current_rms", "kA")],
                      rule("power_current_rating", {"p": "p", "q": "q", "v": "v", "i": "i"}, {"absolute_tolerance": 0}, assumptions=["balanced_three_phase_sinusoidal"]), domain="gfm")
        row = assess(req)["rules"][0]
        self.assertEqual(row["status"], "passed")
        self.assertEqual(row["computed"]["si_factors"], {"p": 1e6, "q": 1e6, "v": 1e3, "i": 1e3})
        self.assertEqual(row["computed"]["apparent_power_va"], 5e6)
        self.assertAlmostEqual(row["computed"]["current_rating_va"], math.sqrt(3) * 1e7)
        for quantity in ("voltage_phase_rms", "voltage_dc"):
            changed = copy.deepcopy(req); changed["packs"][0]["bindings"][2]["quantity"] = quantity
            self.assertEqual(assess(changed)["status"], "inconclusive")
        for index in (2, 3):
            changed = copy.deepcopy(req); changed["packs"][0]["bindings"][index]["expected_value"] = "0"
            changed["packs"][0]["rules"][0]["limits"]["absolute_tolerance"] = 1e10
            self.assertEqual(assess(changed)["rules"][0]["status"], "failed")
        req["packs"][0]["rules"][0]["assumptions"] = []
        with self.assertRaises(ValueError): validate_rulepacks(req)

    def test_overflow_is_inconclusive_and_failed_info_never_reports_no_violations(self):
        req = pair("nominal_voltage_match", 1e308, -1e308)
        self.assertEqual(assess(req)["status"], "inconclusive")
        req = request([binding(value=0)], rule(severity="info"))
        self.assertEqual(assess(req)["status"], "warnings_found")
        self.assertEqual(assess(req)["counts"]["infos"], 1)
        req["packs"][0]["rules"][0]["severity"] = "warning"
        self.assertEqual(assess(req)["counts"]["warnings"], 1)


if __name__ == "__main__":
    unittest.main()

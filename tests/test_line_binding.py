"""Authored byte-level hybrid line projection fixtures; no native API calls."""
import test_environment
import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from rtds_agent.core.line_binding import prepare_line_binding, project_line_binding, calculation_declarations
from test_line_constants import TLI, TLO


DEFINITION = b'''Component Builder 2.3r
PARAMETERS:
  tlb "Companion" " " 10 NAME old_line
  LENGTH "Length" " " 10 REAL 0
  ZM "Impedance" " " 10 REAL_ARRAY 0,0,0
  TM "Time" " " 10 REAL_ARRAY 0,0,0
  R "Resistance" " " 10 REAL_ARRAY 0,0,0
  TI "Transform" " " 10 REAL_ARRAY 0,0,0,0,0,0,0,0,0
  Tnam1 "Line identity" " " 10 NAME LINE#
  endsr "Endpoint" "SENDING;RECEIVING" 0 TOGGLE 0 0 1
  numc "Conductors" "1 to 18" 2 INTEGER 3 1 18
  PERCENT_OF_LINE "Percent" " " 10 REAL 100
NODES:
'''


def component(uuid, end, *, line_name="LINE#", old_basename="old_line"):
    params = {"tlb": old_basename, "LENGTH": "50000.0", "ZM": "600,300,300", "TM": "0.5,0.4,0.4",
              "R": "0.0003,0.0002,0.0002", "TI": "0,0,0,0,0,0,0,0,0", "Tnam1": line_name,
              "endsr": end, "numc": "3", "PERCENT_OF_LINE": "100.0"}
    text = f"COMPONENT_TYPE=lf_rtds_sharc_sld_TLINE\n\t0 32 0 0 {len(params)}\n\tPARAMETERS-START:\n"
    text += "".join(f"\t{key}\t:  {value} \t\n" for key, value in params.items())
    return (text + f"\tPARAMETERS-END:\n\tUUID:\t{uuid}\n").encode()


def source():
    # Runtime and unknown fields are intentionally not interpreted or recreated.
    prefix = "DRAFT 2.2\nDATA:\n TITLE: Authored\n TIME-STEP: 5e-5\n RTDS-RACK: 1\nRUNTIME:\n GROUP: retained-group\n LENGTH: 999\n arbitrary: Ω and 한글\nSUBSYSTEM-START:\n".encode()
    return prefix + component(11, "RECEIVING") + component(12, "SENDING") + b"SUBSYSTEM-END:\nOPAQUE-FOOTER: preserved\n"


def plan_for(raw=None, **kwargs):
    return prepare_line_binding(source() if raw is None else raw, kwargs.get("tli", TLI), kwargs.get("tlo", TLO),
                                kwargs.get("definition", DEFINITION), kwargs.get("endpoint_ids", [11, 12]),
                                kwargs.get("companion_basename", "new_line"))


def readbacks(plan):
    return [{"component_id": row["component_id"], "parameter": row["parameter"],
             "before": row.get("expected_old_api_value", row["expected_old_value"]), "after": row["new_value"]} for row in plan["operations"]]


# Authored fixture descriptions and values; only exact declaration identifiers,
# enum syntax and the supported duplicate-section condition are contractual.
CALC_KINDS = {
    "Name": "NAME", "Dnm1": "NAME", "cntyp": "TOGGLE", "pptline": "TOGGLE", "Icon": "TOGGLE",
    "elimCrtLag": "TOGGLE", "dataType": "TOGGLE", "exclu": "TOGGLE", "AorM": "TOGGLE", "CARD": "INTEGER",
    "Rprc": "TOGGLE", "AM": "TOGGLE", "CORE": "INTEGER", "rdData": "TOGGLE", "note1": "CHAR", "note2": "CHAR",
    "pp_var": "REAL", "hmnpp": "TOGGLE", "frcpi": "TOGGLE", "alwpi": "TOGGLE", "raistt": "TOGGLE", "Ph": "TOGGLE",
    "final_tl_berg_format_tlbclb_tloclo_or_tlines_012": "INTEGER", "final_tl_berg_percentage_line_length": "REAL",
    "final_tl_constants_file_name_cw_sufx": "CHAR", "Type": "TOGGLE", "num_normal_dt_in_SE_dt": "INTEGER",
    "num_normal_dt_in_RE_dt": "INTEGER", "enDebug": "TOGGLE", "local_nmcond": "INTEGER", "Lgrd": "REAL",
    "Rgrd": "REAL", "Laer": "REAL", "Raer": "REAL"}
CALC_VALUES = {name: "0" for name in CALC_KINDS} | {
    "Name": "LINE#", "Dnm1": "old_line#", "cntyp": "Bergeron", "pptline": "No", "dataType": "File",
    "rdData": "tlo/clo", "Type": "TLINE", "pp_var": "100", "hmnpp": "(pp_var)%", "note1": "", "note2": ""}
CALC_CHOICES = {"Name": " ", "Dnm1": "Omit .xxx", "cntyp": "Bergeron;Fre-Dep;Fre-Phase", "pptline": "No;Yes",
                "dataType": "File;Local", "rdData": "tlb/cbl;tlo/clo", "Type": "TLINE;CABLE", "pp_var": "%",
                "hmnpp": "(pp_var)%;(100-pp_var)%"}
CALC_REPEATED = ("pp_var", "hmnpp", "frcpi", "alwpi", "raistt")


def calc_definition():
    def decl(name):
        default = "" if name in {"note1", "note2"} else " " + (CALC_VALUES[name] or "0")
        return f'  {name} "Authored" "{CALC_CHOICES.get(name, "")}" 0 {CALC_KINDS[name]}{default}\n'
    body = 'Component Builder 0.1.0\nPARAMETERS:\n SECTION: "CONFIGURATION"\n'
    body += "".join(decl(name) for name in CALC_KINDS if name not in CALC_REPEATED)
    body += ' SECTION: "OPTIONS WHEN USING BERGERON DATA" cntyp<1 && (getBoxParentType()!=2  || dataType == 0)\n'
    body += "".join(decl(name) for name in CALC_REPEATED)
    body += ' SECTION: "OPTIONS" cntyp>0 & pptline=1\n'
    body += "".join(decl(name) for name in CALC_REPEATED)
    return (body + "GRAPHICS:\n").encode()


def calc_component(uid=18, **overrides):
    values = CALC_VALUES | overrides
    text = f"COMPONENT_TYPE=lf_rtds_sharc_sld_TL16CAL\n 0 32 0 0 {len(values)}\n PARAMETERS-START:\n"
    text += "".join(f" {name}: {value} \t\n" for name, value in values.items())
    return (text + f" PARAMETERS-END:\n UUID: {uid}\n").encode()


def complete_source(**overrides):
    return source().replace(b"SUBSYSTEM-END:", calc_component(**overrides) + b"SUBSYSTEM-END:")


class LineBindingTests(unittest.TestCase):
    def project(self, raw=None, plan=None, observations=None, **kwargs):
        raw = source() if raw is None else raw
        plan = plan_for(raw) if plan is None else plan
        observations = readbacks(plan) if observations is None else observations
        return project_line_binding(raw, kwargs.get("tli", TLI), kwargs.get("tlo", TLO),
                                    kwargs.get("definition", DEFINITION), plan, observations)

    def test_plan_is_deterministic_exactly_twelve_fields_and_source_bound(self):
        plan = plan_for()
        self.assertEqual(plan, plan_for(endpoint_ids=[12, 11]))
        self.assertEqual(len(plan["operations"]), 12)
        self.assertEqual(plan["source_component_count"], 2)
        self.assertEqual(plan["source_dfx_sha256"], hashlib.sha256(source()).hexdigest())
        self.assertEqual(plan["definition_sha256"], hashlib.sha256(DEFINITION).hexdigest())
        self.assertEqual(plan["constants_comparison"]["checks"], 24)
        for operation in plan["operations"]:
            old = source()[operation["source_byte_start"]:operation["source_byte_end"]].decode()
            self.assertEqual(old, operation["expected_old_value"])
        json.dumps(plan, allow_nan=False)

    def test_projection_preserves_bom_crlf_runtime_and_every_unrequested_byte(self):
        raw = b"\xef\xbb\xbf" + source().replace(b"\n", b"\r\n")
        plan = plan_for(raw)
        report, candidate = self.project(raw, plan)
        self.assertEqual(report["status"], "projected_in_memory")
        self.assertTrue(candidate.startswith(b"\xef\xbb\xbfDRAFT 2.2\r\n"))
        self.assertIn(b" GROUP: retained-group\r\n LENGTH: 999", candidate)
        self.assertIn("arbitrary: Ω and 한글".encode(), candidate)
        rebuilt = candidate
        for change in reversed(report["changes"]):
            self.assertEqual(candidate[change["candidate_byte_start"]:change["candidate_byte_end"]].decode(), change["new_value"])
            rebuilt = rebuilt[:change["candidate_byte_start"]] + change["expected_old_value"].encode() + rebuilt[change["candidate_byte_end"]:]
        self.assertEqual(rebuilt, raw)
        self.assertEqual(report["candidate_dfx_sha256"], hashlib.sha256(candidate).hexdigest())

    def test_matching_observations_never_authenticate_api_or_publication(self):
        plan = plan_for()
        with (patch("socket.socket", side_effect=AssertionError("socket")),
              patch("subprocess.Popen", side_effect=AssertionError("process")),
              patch("builtins.open", side_effect=AssertionError("file I/O"))):
            report, _ = self.project(plan=plan, observations=list(reversed(readbacks(plan))))
        self.assertEqual(report["backend"], "hybrid_api_observed_source_patch")
        for flag in ("observations_authenticated", "native_serialized_output", "definition_identity_authenticated",
                     "filesystem_name_uniqueness_verified", "integration_qualified", "execution_authorized",
                     "live_calls_made", "compile_called", "runtime_called", "automatic_retry"):
            self.assertIs(report[flag], False)
        self.assertEqual(report["files_written"], 0)
        self.assertEqual(report["engineering_verdict"], "not_evaluated")

    def test_each_bound_input_change_invalidates_plan(self):
        plan = plan_for()
        variants = [(source() + b"\n", TLI, TLO, DEFINITION),
                    (source(), TLI + b"\n", TLO, DEFINITION),
                    (source(), TLI, TLO + b"\n", DEFINITION),
                    (source(), TLI, TLO, DEFINITION + b"\n")]
        for values in variants:
            with self.subTest(hash=hashlib.sha256(b"".join(values)).hexdigest()), self.assertRaises(ValueError):
                project_line_binding(*values, plan, readbacks(plan))

    def test_plan_mutation_extra_keys_and_boolean_number_aliases_refused(self):
        original = plan_for()
        for mutate in (lambda p: p.update(plan_id="0" * 64), lambda p: p.update(extra=True),
                       lambda p: p["operations"][0].update(new_value="different"),
                       lambda p: p["operations"][0].update(source_byte_start=1),
                       lambda p: p.update(files_written=False), lambda p: p.update(endpoint_ids=[True, 12])):
            plan = copy.deepcopy(original)
            mutate(plan)
            with self.subTest(plan_id=plan["plan_id"]), self.assertRaises(ValueError):
                self.project(plan=plan, observations=readbacks(original))

    def test_missing_duplicate_extra_and_wrong_identity_observations_refused(self):
        plan = plan_for()
        valid = readbacks(plan)
        variants = [[], valid[:-1], valid + valid[:1], valid[:-1] + valid[:1]]
        for field, value in (("component_id", 99), ("component_id", True), ("parameter", "OTHER"), ("authenticated", True)):
            changed = copy.deepcopy(valid)
            changed[0][field] = value
            variants.append(changed)
        for records in variants:
            with self.subTest(records=len(records)), self.assertRaises(ValueError):
                self.project(plan=plan, observations=records)

    def test_wrong_old_new_rounded_and_vector_permutation_readbacks_refused(self):
        plan = plan_for()
        for parameter, field, value in (("tlb", "before", "other_line"), ("tlb", "after", "other_line"),
                                        ("LENGTH", "after", "10000.00000000000000001"),
                                        ("ZM", "after", "200,1000,200"), ("TI", "after", "0,0,0"),
                                        ("R", "after", "NaN,1,1"), ("LENGTH", "after", True)):
            records = readbacks(plan)
            next(row for row in records if row["parameter"] == parameter)[field] = value
            with self.subTest(parameter=parameter, field=field), self.assertRaises(ValueError):
                self.project(plan=plan, observations=records)

    def test_endpoint_roles_names_phase_and_line_percent_are_explicit(self):
        for old, new in ((b"RECEIVING", b"SENDING"), (b"numc\t:  3", b"numc\t:  6"),
                         (b"numc\t:  3", b"numc\t:  3.0"),
                         (b"PERCENT_OF_LINE\t:  100.0", b"PERCENT_OF_LINE\t:  50"),
                         (b"Tnam1\t:  LINE#", b"Tnam1\t:  ../line")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                plan_for(source().replace(old, new, 1))
        for changed in (component(11, "RECEIVING", line_name="OTHER#") + component(12, "SENDING"),
                        component(11, "RECEIVING", old_basename="other") + component(12, "SENDING")):
            raw = b"SUBSYSTEM-START:\n" + changed + b"SUBSYSTEM-END:\n"
            with self.assertRaises(ValueError):
                plan_for(raw)

    def test_more_endpoints_same_saved_line_are_ambiguous(self):
        raw = source().replace(b"SUBSYSTEM-END:", component(13, "SENDING") + b"SUBSYSTEM-END:")
        with self.assertRaises(ValueError):
            plan_for(raw)

    def test_duplicate_uuids_parameter_lines_and_sections_refused(self):
        cases = [source().replace(b"UUID:\t12", b"UUID:\t11"),
                 source().replace(b"\tUUID:\t11", b"\tUUID:\t11\n\tUUID:\t11"),
                 source().replace(b"\tLENGTH\t:  50000.0 \t", b"\tLENGTH\t:  50000.0\n\tLENGTH:50000.0", 1),
                 source().replace(b"\tPARAMETERS-START:", b"\tPARAMETERS-START:\n\tPARAMETERS-START:", 1),
                 source().replace(b"0 32 0 0 10", b"0 32 0 0 9", 1)]
        for raw in cases:
            with self.subTest(raw=len(raw)), self.assertRaises(ValueError):
                plan_for(raw)

    def test_groups_hierarchy_context_aliases_and_wrong_component_type_refused(self):
        for raw in (source().replace(b"SUBSYSTEM-START:", b"SUBSYSTEM-START:\nHIERARCHY-START:"),
                    source().replace(b"SUBSYSTEM-START:", b"SUBSYSTEM-START:\nCOMPONENT_TYPE=GROUP"),
                    source().replace(b"SUBSYSTEM-END:", b"SUBSYSTEM-END:\nSUBSYSTEM-START:\nSUBSYSTEM-END:"),
                    source().replace(b"COMPONENT_TYPE=", b" COMPONENT_TYPE=", 1),
                    source().replace(b"lf_rtds_sharc_sld_TLINE", b"TLINE", 1)):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                plan_for(raw)

    def test_definition_missing_duplicate_wrong_type_and_unit_refused(self):
        variants = [DEFINITION.replace(b"  LENGTH", b"  OTHER", 1),
                    DEFINITION.replace(b"NODES:", b'  LENGTH "Duplicate" " " 10 REAL 0\nNODES:'),
                    DEFINITION.replace(b'LENGTH "Length" " " 10 REAL', b'LENGTH "Length" " " 10 NAME'),
                    DEFINITION.replace(b'LENGTH "Length" " "', b'LENGTH "Length" "km"'),
                    DEFINITION.replace(b'"SENDING;RECEIVING"', b'"RECEIVING;SENDING"'),
                    DEFINITION + b"PARAMETERS:\n"]
        for definition in variants:
            with self.subTest(size=len(definition)), self.assertRaises(ValueError):
                plan_for(definition=definition)

    def test_unsafe_existing_or_ambiguous_companion_names_refused(self):
        for name in ("../new", "sub/new", "new.tli", "new line", "CON", "nul", "new#", "old_line", "OLD_LINE", "1line", "x" * 81, "한글"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                plan_for(companion_basename=name)
        with self.assertRaises(ValueError):
            plan_for(source() + b"unparsed_reference:new_line.tlo\n")

    def test_constants_must_be_current_numerically_consistent_and_representable(self):
        with self.assertRaises(ValueError):
            plan_for(tli=TLI.replace(b"Length = 10", b"Length = 11"))
        with self.assertRaises(ValueError):
            plan_for(tlo=TLO.replace(b" 200 ", b" 201 "))
        # Core comparison tolerates this tiny difference, but one R cache value
        # cannot exactly represent disagreeing duplicated resistance columns.
        with self.assertRaises(ValueError):
            plan_for(tlo=TLO.replace(b"0.0004 0.0004", b"0.0004 0.0004000000000001"))

    def test_old_values_must_be_strict_finite_scalar_array_tokens(self):
        for old, new in ((b"50000.0", b"1e999"), (b"600,300,300", b"600,300"),
                         (b"600,300,300", b"600, 300,300"), (b"0.5,0.4,0.4", b"NaN,0.4,0.4")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                plan_for(source().replace(old, new, 1))

    def test_bounded_inputs_and_invalid_endpoint_types(self):
        for ids in ([11], [11, 11], [True, 12], [11, 12, 13], (11, 12), [11, "12"]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                plan_for(endpoint_ids=ids)
        for kwargs in ({"tli": b" " * 65537}, {"tlo": b" " * 65537}, {"definition": b" " * (2 * 1024 * 1024 + 1)}):
            with self.assertRaises(ValueError):
                plan_for(**kwargs)
        with self.assertRaises(ValueError):
            plan_for(b" " * (8 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            plan_for(source() + b"\x00")


class CompleteLineBindingTests(unittest.TestCase):
    def prepare(self, raw=None, definition=None, **kwargs):
        return prepare_line_binding(complete_source() if raw is None else raw, TLI, TLO, DEFINITION,
                                    [11, 12], "new_line", calculation_definition=calc_definition() if definition is None else definition,
                                    calculation_id=kwargs.get("calculation_id", 18))

    def project(self, raw=None, plan=None, records=None, definition=None):
        raw = complete_source() if raw is None else raw
        definition = calc_definition() if definition is None else definition
        plan = self.prepare(raw, definition) if plan is None else plan
        return project_line_binding(raw, TLI, TLO, DEFINITION, plan, readbacks(plan) if records is None else records,
                                    calculation_definition=definition, calculation_id=18)

    def test_complete_plan_has_distinct_raw_and_api_old_binding(self):
        plan = self.prepare()
        self.assertEqual(len(plan["operations"]), 13)
        self.assertEqual(plan["binding_scope"], "endpoint_and_calculation_parameters")
        self.assertFalse(plan["compiler_dependency_binding_verified"])
        op = plan["operations"][-1]
        self.assertEqual((op["component_id"], op["parameter"], op["expected_old_value"], op["expected_old_api_value"], op["new_value"]),
                         (18, "Dnm1", "old_line#", "old_line", "new_line"))
        self.assertEqual(plan["calculation_definition_sha256"], hashlib.sha256(calc_definition()).hexdigest())
        evidence = plan["calculation_definition_evidence"]
        self.assertEqual(len(evidence["declarations"]), 34)
        self.assertEqual(len(evidence["inactive_declarations"]), 5)
        self.assertIsNone(evidence["declarations"]["note1"]["default"])
        self.assertEqual(plan["source_calculation_parameters"]["note1"], "")
        legacy = plan_for()
        self.assertEqual(legacy["binding_scope"], "endpoint_parameters_only")
        self.assertFalse(legacy["compiler_dependency_binding_verified"])

    def test_thirteen_exact_spans_and_opaque_bytes_are_preserved(self):
        raw = b"\xef\xbb\xbf" + complete_source().replace(b"\n", b"\r\n")
        plan = self.prepare(raw)
        report, candidate = self.project(raw, plan)
        self.assertEqual(report["observation_count"], 13)
        self.assertIn(b" Dnm1: new_line \t\r\n", candidate)
        self.assertIn(b" Name: LINE# \t\r\n", candidate)
        self.assertIn(b" note1:  \t\r\n", candidate)
        reconstructed = candidate
        for change in reversed(report["changes"]):
            reconstructed = reconstructed[:change["candidate_byte_start"]] + change["expected_old_value"].encode() + reconstructed[change["candidate_byte_end"]:]
        self.assertEqual(reconstructed, raw)
        self.assertFalse(report["observations_authenticated"])
        self.assertFalse(report["compiler_dependency_binding_verified"])
        self.assertFalse(report["compile_called"])

    def test_unadorned_old_calculation_basename_is_explicitly_supported(self):
        raw = complete_source(Dnm1="old_line")
        report, candidate = self.project(raw)
        self.assertEqual(report["changes"][-1]["expected_old_value"], "old_line")
        self.assertIn(b" Dnm1: new_line ", candidate)

    def test_calculation_identity_name_companion_and_selector_mismatches_refused(self):
        for overrides in ({"uid": 19}, {"Name": "OTHER#"}, {"Name": "LINE"}, {"Dnm1": "other#"},
                          {"Dnm1": "old_line##"}, {"cntyp": "Fre-Dep"}, {"pptline": "Yes"}, {"dataType": "Local"},
                          {"rdData": "tlb/cbl"}, {"Type": "CABLE"}, {"pp_var": "99.9999999999999999999"},
                          {"hmnpp": "(100-pp_var)%"}, {"note1": "unexpected"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.prepare(complete_source(**overrides))
        for raw in (source(), complete_source().replace(b"lf_rtds_sharc_sld_TL16CAL", b"other_type"),
                    complete_source().replace(b"SUBSYSTEM-END:", calc_component(19) + b"SUBSYSTEM-END:")):
            with self.assertRaises(ValueError): self.prepare(raw)

    def test_definition_and_id_are_paired_strict_explicit_arguments(self):
        for kwargs in ({"calculation_id": 18}, {"calculation_definition": calc_definition()},
                       {"calculation_id": True, "calculation_definition": calc_definition()},
                       {"calculation_id": 11, "calculation_definition": calc_definition()}):
            with self.assertRaises(ValueError):
                prepare_line_binding(complete_source(), TLI, TLO, DEFINITION, [11, 12], "new_line", **kwargs)
        plan = self.prepare()
        with self.assertRaises(ValueError):
            project_line_binding(complete_source(), TLI, TLO, DEFINITION, plan, readbacks(plan))

    def test_definition_extra_duplicate_changed_scope_or_type_refused(self):
        definition = calc_definition()
        for altered in (definition.replace(b'cntyp>0 & pptline=1', b'cntyp>0 | pptline=1'),
                        definition.replace(b'Dnm1 "Authored" "Omit .xxx" 0 NAME', b'Dnm1 "Authored" "Omit .xxx" 0 REAL'),
                        definition.replace(b'Bergeron;Fre-Dep;Fre-Phase', b'Fre-Dep;Bergeron;Fre-Phase'),
                        definition.replace(b'GRAPHICS:', b' Dnm1 "Dup" "Omit .xxx" 0 NAME old_line\nGRAPHICS:'),
                        definition.replace(b'GRAPHICS:', b' unexpected "Extra" "" 0 REAL 0\nGRAPHICS:'),
                        definition.replace(b'  note1 "Authored" "" 0 CHAR\n', b''),
                        definition + b'PARAMETERS:\n'):
            with self.subTest(size=len(altered)), self.assertRaises(ValueError): self.prepare(definition=altered)
        for values in (CALC_VALUES | {"extra": "0"}, {k: v for k, v in CALC_VALUES.items() if k != "note1"},
                       CALC_VALUES | {"pp_var": float("nan")}, CALC_VALUES | {"pp_var": "NaN"}):
            with self.assertRaises(ValueError): calculation_declarations(definition, values)

    def test_calculation_definition_source_hash_and_plan_tampering_refused(self):
        plan = self.prepare()
        with self.assertRaises(ValueError): self.project(plan=plan, definition=calc_definition() + b"\n")
        for key, value in (("expected_old_api_value", "other"), ("expected_old_value", "old_line"), ("new_value", "other")):
            altered = copy.deepcopy(plan)
            altered["operations"][-1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.project(plan=altered)
        altered = copy.deepcopy(plan)
        altered["compiler_dependency_binding_verified"] = True
        with self.assertRaises(ValueError): self.project(plan=altered)

    def test_calculation_readback_must_match_exact_api_value_and_identity(self):
        plan = self.prepare()
        for key, value in (("before", "old_line#"), ("before", "other"), ("after", "new_line#"),
                           ("after", "../new_line"), ("component_id", 11), ("component_id", True), ("parameter", "Name")):
            records = readbacks(plan)
            records[-1][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.project(plan=plan, records=records)
        for records in (readbacks(plan)[:-1], readbacks(plan) + readbacks(plan)[-1:], readbacks(plan)[:-1] + readbacks(plan)[:1]):
            with self.assertRaises(ValueError): self.project(plan=plan, records=records)
        reordered = list(reversed(readbacks(plan)))
        self.assertEqual(self.project(plan=plan, records=reordered), self.project(plan=plan))


if __name__ == "__main__":
    unittest.main()

"""Synthetic fake SDK/archives only. No installed SDK, socket or application."""
import test_environment
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from rtds_agent.core.line_binding import _source, prepare_line_binding
from rtds_agent.core.line_binding_native import bind_line_case, allow_line_binding_rpc
from rtds_agent.core.native_edit import NativeJournal
from rtds_agent.safety import ToolSafetyError
from test_line_constants import TLI, TLO


BASE = {
    "tlb": ("NAME", "old_line"), "LENGTH": ("REAL", "50000.0"),
    "ZM": ("REAL_ARRAY", "600,300,300"), "TM": ("REAL_ARRAY", "0.5,0.4,0.4"),
    "R": ("REAL_ARRAY", "0.0003,0.0002,0.0002"), "TI": ("REAL_ARRAY", "0,0,0,0,0,0,0,0,0"),
    "Tnam1": ("NAME", "LINE#"), "endsr": ("TOGGLE", "0"),
    "numc": ("INTEGER", "3"), "PERCENT_OF_LINE": ("REAL", "100.0"),
    **{f"kept{i}": ("REAL", str(i)) for i in range(102)},
}
ADDED = {f"added{i}": ("NAME", f"EXTRA{i}#") if i < 10 else ("REAL", "0.0") for i in range(24)}
DEFINITION = ("Component Builder 2.3r\nPARAMETERS:\n" + "".join(
    f' {name} "Authored" "' + ("SENDING;RECEIVING" if name == "endsr" else " ") +
    f'" 10 {kind} {default}\n' for name, (kind, default) in (BASE | ADDED).items()) + "NODES:\n").encode()

# Authored declarations use the fixed source identifiers and selector grammar,
# with synthetic descriptions and values. No vendor definition is loaded.
CALC = {
    "Name": ("NAME", "LINE#", " "), "Dnm1": ("NAME", "old_line", "Omit .xxx"),
    "cntyp": ("TOGGLE", "Bergeron", "Bergeron;Fre-Dep;Fre-Phase"),
    "pptline": ("TOGGLE", "No", "No;Yes"), "Icon": ("TOGGLE", "Small", "Small;Large"),
    "elimCrtLag": ("TOGGLE", "No", "No;Yes"), "dataType": ("TOGGLE", "File", "File;Local"),
    "exclu": ("TOGGLE", "No", "No;Yes"), "AorM": ("TOGGLE", "Automatic", "Automatic;Manual"),
    "CARD": ("INTEGER", "1", " "), "Rprc": ("TOGGLE", "A", "A;B"),
    "AM": ("TOGGLE", "NO", "NO;YES"), "CORE": ("INTEGER", "1", " "),
    "rdData": ("TOGGLE", "tlo/clo", "tlb/cbl;tlo/clo"),
    "note1": ("CHAR", None, ""), "note2": ("CHAR", None, ""),
    "pp_var": ("REAL", "100.0", "%"), "hmnpp": ("TOGGLE", "(pp_var)%", "(pp_var)%;(100-pp_var)%"),
    "frcpi": ("TOGGLE", "No", "No;Yes"), "alwpi": ("TOGGLE", "No", "No;Yes"),
    "raistt": ("TOGGLE", "ERROR", "ERROR;RaiseTT"), "Ph": ("TOGGLE", "Yes", "No;Yes"),
    "final_tl_berg_format_tlbclb_tloclo_or_tlines_012": ("INTEGER", "0", ""),
    "final_tl_berg_percentage_line_length": ("REAL", "0.0", ""),
    "final_tl_constants_file_name_cw_sufx": ("CHAR", "0", ""),
    "Type": ("TOGGLE", "TLINE", "TLINE;CABLE"),
    "num_normal_dt_in_SE_dt": ("INTEGER", "0", ""), "num_normal_dt_in_RE_dt": ("INTEGER", "0", ""),
    "enDebug": ("TOGGLE", "No", "No;Yes"), "local_nmcond": ("INTEGER", "1", ""),
    "Lgrd": ("REAL", "0.001", "Henries"), "Rgrd": ("REAL", "0.0", "Ohms"),
    "Laer": ("REAL", "0.00099", "Henries"), "Raer": ("REAL", "0.0", "Ohms"),
}
REPEATED = ("pp_var", "hmnpp", "frcpi", "alwpi", "raistt")
CALC_VALUES = {name: default if default is not None else "" for name, (_, default, _) in CALC.items()}
CALC_VALUES["Dnm1"] = "old_line#"


def calculation_definition():
    def declaration(name):
        kind, default, choices = CALC[name]
        return f' {name} "Authored" "{choices}" 10 {kind}' + (" " + default if default is not None else "") + "\n"
    result = 'Component Builder 0.1.0\nPARAMETERS:\n SECTION: "CONFIGURATION"\n'
    result += "".join(declaration(n) for n in CALC if n not in REPEATED)
    result += ' SECTION: "OPTIONS WHEN USING BERGERON DATA" cntyp<1 && (getBoxParentType()!=2  || dataType == 0)\n'
    result += "".join(declaration(n) for n in REPEATED)
    result += ' SECTION: "OPTIONS" cntyp>0 & pptline=1\n'
    result += "".join(declaration(n) for n in REPEATED)
    return (result + "NODES:\n").encode()


def component(uid, params, kind="lf_rtds_sharc_sld_TLINE"):
    return (f"COMPONENT_TYPE={kind}\n 0 32 0 0 {len(params)}\n PARAMETERS-START:\n" +
            "".join(f" {name}: {value} \t\n" for name, value in params.items()) +
            f" PARAMETERS-END:\n UUID: {uid}\n").encode()


def source(complete=False):
    prefix = "DRAFT 2.2\nDATA:\n TITLE: Authored\n TIME-STEP: 5e-5\n RTDS-RACK: 1\nRUNTIME:\n GROUP: retained\n opaque: Ω 한글\nSUBSYSTEM-START:\n".encode()
    rows = []
    for uid, end in ((11, "RECEIVING"), (12, "SENDING")):
        values = {name: val for name, (_, val) in BASE.items()}
        values["endsr"] = end
        rows.append(component(uid, values))
    if complete:
        rows.append(component(18, CALC_VALUES, "lf_rtds_sharc_sld_TL16CAL"))
    return prefix + b"".join(rows) + b"SUBSYSTEM-END:\nOPAQUE-FOOTER: keep exact bytes\n"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeComponent:
    def __init__(self, case, uid, params, kind="lf_rtds_sharc_sld_TLINE"):
        self.case, self.unique_id, self.values = case, uid, params
        self.kind = kind

    def rpc(self, method, args):
        self.case.app.rpc(f"rscad.case:{self.case.caseid}.draft.comp_id:{self.unique_id}", method, args)

    @property
    def component_type(self):
        self.rpc("getComponentType", [])
        return "wrong" if (self.case.app.mode == "wrong_component" or
                           (self.unique_id == 18 and self.case.app.mode == "wrong_calculation_type")) else self.kind

    @property
    def parameters(self):
        self.rpc("getParameters", [])
        result = list(self.values)
        return result + ["unbound"] if (self.case.app.mode == "extra_parameter" or
                                       (self.unique_id == 18 and self.case.app.mode == "calc_extra_parameter")) else result

    def get_parameter(self, name):
        self.rpc("getParameter", [name])
        value = self.values[name].replace("#", "7")
        mode = self.case.app.mode
        if self.unique_id == 18:
            if name == "Dnm1" and self.values[name] == "old_line#":
                value = "old_line" if mode != "calc_old_api_mismatch" else "old_line7"
            if name == "Name" and mode == "calc_name_mismatch":
                value = "OTHER7"
            if name == "note1" and mode == "calc_blank_mismatch":
                value = "0"
            if name == "alwpi" and ((mode == "calc_after_drift" and self.case.app.sets) or
                                   (mode == "calc_reopen_drift" and self.case.app.opens == 2)):
                value = "Yes"
        if name == "kept0" and mode == "baseline_stored_drift":
            return "1"
        if name == "added10" and mode == "baseline_default_drift":
            return "1"
        if name == "numc" and mode == "wrong_phases":
            return "6"
        if name == "PERCENT_OF_LINE" and mode == "wrong_percent":
            return "50.0"
        if name == "endsr" and mode == "wrong_direction":
            return "SENDING"
        if name == "kept0" and ((mode == "after_drift" and self.case.app.sets) or
                                 (mode == "reopen_drift" and self.case.app.opens == 2)):
            return "999"
        if name == "Tnam1" and mode == "bad_pair" and self.unique_id == 12:
            return "OTHER7"
        return value

    def set_parameter(self, name, value):
        self.rpc("setParameter", [name, value])
        self.values[name] = value
        self.case.dirty = True
        self.case.app.sets += 1
        if self.case.app.mode == "source_race" and self.case.app.sets == 1:
            with self.case.app.inp.open("ab") as stream:
                stream.write(b"race")
        if self.case.app.mode == "set_error":
            raise RuntimeError("injected set error after mutation")


class FakeState:
    def __init__(self, case):
        self.case = case

    @property
    def run_state(self):
        self.case.rpc("getRunState", [])
        return "stopped"

    @property
    def modified(self):
        self.case.rpc("getModified", [])
        return self.case.dirty


class FakeDraft:
    def __init__(self, case, rows):
        self.case = case
        self.items = {}
        for row in rows:
            defaults = CALC_VALUES if row["component_type"] == "lf_rtds_sharc_sld_TL16CAL" else {
                name: default for name, (_, default) in (BASE | ADDED).items()}
            values = defaults | row["parameters"]
            self.items[row["uuid"]] = FakeComponent(case, row["uuid"], values, row["component_type"])

    def num_subpages(self):
        self.case.app.rpc(f"rscad.case:{self.case.caseid}.draft", "numSubpages", [])
        return 1

    def get_object(self, uid):
        self.case.app.rpc(f"rscad.case:{self.case.caseid}.draft", "getComponent", [uid])
        return self.items[uid]


class FakeCase:
    def __init__(self, app, path):
        self.app, self.path, self.caseid, self.dirty = app, path, 100 + app.opens, False
        with zipfile.ZipFile(path) as z:
            self.raw = z.read("model.dfx")
        self.draft = FakeDraft(self, _source(self.raw)[1])
        self.state = FakeState(self)

    def rpc(self, method, args):
        self.app.rpc(f"rscad.case:{self.caseid}", method, args)

    @property
    def file(self):
        self.rpc("getFile", [])
        return str(self.path.with_name("wrong.rtfx")) if self.app.mode == "wrong_identity" else str(self.path)

    def save(self, path):
        self.rpc("saveAs", [path])
        self.app.saves += 1
        if self.app.mode == "save_error":
            raise RuntimeError("injected uncertain save")
        prefix = self.raw.split(b"COMPONENT_TYPE=", 1)[0].replace(b"DRAFT 2.2", b"DRAFT 2.7")
        content = prefix
        for uid, item in self.draft.items.items():
            values = dict(item.values)
            if self.app.mode == "export_mismatch" and uid == 11:
                values["LENGTH"] = "777"
            if self.app.mode == "calc_export_mismatch" and uid == 18:
                values["Dnm1"] = "wrong_line"
            content += component(uid, values, item.kind)
        content += b"SUBSYSTEM-END:\nMIGRATED-FOOTER: native\n"
        with zipfile.ZipFile(path, "x") as z:
            z.writestr("model.dfx", content)
            z.writestr("model.rtx", b"MIGRATED NONEMPTY RUNTIME")
            z.writestr("model.inf2", b"")
        self.path, self.dirty = Path(path), False

    def close(self, force=False):
        self.rpc("close", [force])
        if force or self.dirty:
            raise AssertionError("unsafe close")
        self.app.closes += 1
        if self.app.mode == "close_error":
            raise RuntimeError("injected uncertain close")
        self.app.case = None
        if self.app.mode == "final_hash_error" and self.app.opens == 2:
            self.app.candidate.unlink()
        return True


class FakeApp:
    def __init__(self, journal, inp, export, candidate, mode=None):
        self.journal, self.inp, self.export, self.candidate, self.mode = journal, inp, export, candidate, mode
        self.case = None
        self.connects = self.opens = self.sets = self.saves = self.closes = self.disconnects = 0
        self.requests = []

    def rpc(self, path, method, args):
        allowed = allow_line_binding_rpc(path, method, args, self.journal, self.inp, self.export, self.candidate)
        self.requests.append((path, method, args, allowed))
        if not allowed:
            raise AssertionError(f"RPC refused: {path} {method} {args}")

    def connect(self):
        self.connects += 1
        self.rpc("rscad", "getMinimumApiVersion", [])

    def get_version(self):
        self.rpc("rscad", "getVersion", [])
        return "2.7.3"

    def get_case(self, *, file, open_file):
        self.rpc("rscad", "getCaseNamed", [file, open_file])
        return self.case if self.case and str(self.case.path) == file else None

    def open_case(self, path):
        self.rpc("rscad", "openCase", [path])
        self.opens += 1
        if self.mode == "reopen_error" and self.opens == 2:
            raise RuntimeError("injected unconfirmed reopen")
        self.case = FakeCase(self, Path(path))
        if self.mode == "candidate_race" and self.opens == 2:
            with self.candidate.open("ab") as stream:
                stream.write(b"race")
        return self.case

    def disconnect(self, terminate=False):
        self.rpc("rscad", "ping", [])
        if terminate:
            raise AssertionError("terminate forbidden")
        self.disconnects += 1
        if self.mode == "disconnect_error":
            raise RuntimeError("injected disconnect error")


class NativeLineBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inp = self.root / "input" / "model.rtfx"
        self.inp.parent.mkdir()
        self.export = self.root / "export" / "model.rtfx"
        self.candidate = self.root / "candidate" / "model.rtfx"
        with zipfile.ZipFile(self.inp, "x") as z:
            z.comment = b"Authored archive comment"
            z.writestr("model.dfx", source())
            z.writestr("model.rtx", b"NONEMPTY RUNTIME exact original bytes")
            z.writestr("unknown.bin", b"\x00\xffOpaque payload")
        (self.inp.parent / "new_line.tli").write_bytes(TLI)
        (self.inp.parent / "new_line.tlo").write_bytes(TLO)
        self.digest = sha(self.inp)
        self.plan = prepare_line_binding(source(), TLI, TLO, DEFINITION, [11, 12], "new_line")
        self.journal = NativeJournal(self.root / "journal.json")

    def run_adapter(self, mode=None, **changes):
        self.app = FakeApp(self.journal, self.inp, self.export, self.candidate, mode)
        args = dict(app=self.app, input_path=self.inp, export_path=self.export, candidate_path=self.candidate,
                    source_sha256=self.digest, tli=TLI, tlo=TLO, definition=DEFINITION, plan=self.plan, journal=self.journal)
        if hasattr(self, "calc_definition"):
            args.update(calculation_definition=self.calc_definition, calculation_id=18)
        args.update(changes)
        return bind_line_case(**args)

    def complete_fixture(self):
        self.calc_definition = calculation_definition()
        with zipfile.ZipFile(self.inp, "w") as archive:
            archive.comment = b"Authored archive comment"
            archive.writestr("model.dfx", source(complete=True))
            archive.writestr("model.rtx", b"NONEMPTY RUNTIME exact original bytes")
            archive.writestr("unknown.bin", b"\x00\xffOpaque payload")
        self.digest = sha(self.inp)
        self.plan = prepare_line_binding(source(complete=True), TLI, TLO, DEFINITION, [11, 12], "new_line",
                                         calculation_definition=self.calc_definition, calculation_id=18)

    def test_complete_hybrid_preserves_source_runtime_opaque_and_all_parameters(self):
        result = self.run_adapter()
        self.assertEqual(result["status"], "verified_hybrid_binding")
        self.assertEqual(result["native_parameter_count"], 136)
        self.assertTrue(result["cleanup_verified"])
        self.assertEqual((self.app.opens, self.app.sets, self.app.saves, self.app.closes, self.app.disconnects), (2, 12, 1, 2, 1))
        self.assertEqual(sha(self.inp), self.digest)
        for stage in ("before", "after", "candidate_reopen"):
            self.assertEqual([len(v) for v in result["observations"][stage].values()], [136, 136])
            self.assertEqual(result["observations"][stage]["11"]["Tnam1"], "LINE7")
        with zipfile.ZipFile(self.candidate) as c, zipfile.ZipFile(self.inp) as original, zipfile.ZipFile(self.export) as e:
            self.assertEqual(c.comment, original.comment)
            self.assertEqual(c.namelist(), original.namelist())
            for name in ("model.rtx", "unknown.bin"):
                self.assertEqual(c.read(name), original.read(name))
            self.assertNotEqual(c.read("model.rtx"), e.read("model.rtx"))
            self.assertIn(b"OPAQUE-FOOTER: keep exact bytes", c.read("model.dfx"))
            self.assertIn("opaque: Ω 한글".encode(), c.read("model.dfx"))
            self.assertEqual(len(_source(c.read("model.dfx"))[1][0]["parameters"]), 112)
            self.assertEqual(len(_source(e.read("model.dfx"))[1][0]["parameters"]), 136)
        self.assertEqual((self.candidate.parent / "new_line.tli").read_bytes(), TLI)
        self.assertFalse(result["native_serialized_output"])
        self.assertFalse(result["compile_called"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["binding_scope"], "endpoint_parameters_only")
        self.assertFalse(result["compiler_dependency_binding_verified"])

    def test_complete_three_component_binding_observes_918_values_and_projects_13_fields(self):
        self.complete_fixture()
        result = self.run_adapter()
        self.assertEqual(self.app.sets, 13)
        self.assertEqual(result["binding_scope"], "endpoint_and_calculation_parameters")
        self.assertTrue(result["compiler_dependency_binding_verified"])
        self.assertFalse(result["native_serialized_output"])
        self.assertFalse(result["integration_qualified"])
        self.assertFalse(result["compile_called"])
        self.assertEqual(result["native_parameter_counts"], {"11": 136, "12": 136, "18": 34})
        self.assertEqual(sum(len(v) for stage in result["observations"].values() for v in stage.values()), 918)
        self.assertEqual(result["observations"]["before"]["18"]["Dnm1"], "old_line")
        for stage in ("before", "after", "candidate_reopen"):
            self.assertEqual(result["observations"][stage]["18"]["Name"], result["observations"][stage]["11"]["Tnam1"])
            self.assertEqual(result["observations"][stage]["18"]["note1"], "")
            self.assertEqual(result["observations"][stage]["18"]["note2"], "")
        for stage in ("after", "candidate_reopen"):
            self.assertEqual(result["observations"][stage]["18"]["Dnm1"], "new_line")
        self.assertEqual(len(result["calculation_definition_evidence"]["inactive_declarations"]), 5)
        self.assertIsNone(result["calculation_definition_evidence"]["declarations"]["note1"]["default"])
        with zipfile.ZipFile(self.candidate) as z:
            raw = z.read("model.dfx")
            self.assertNotIn(b"old_line#", raw)
            self.assertIn(b"Dnm1: new_line", raw)
            self.assertEqual(len(_source(raw)[1][2]["parameters"]), 34)
            self.assertEqual(z.read("model.rtx"), b"NONEMPTY RUNTIME exact original bytes")
        self.assertFalse((self.candidate.parent / "old_line.tlo").exists())

    def test_calculation_definition_and_conditional_inventory_refused_before_sdk(self):
        self.complete_fixture()
        for kwargs in (
            {"calculation_definition": None}, {"calculation_id": None}, {"calculation_id": True},
            {"calculation_definition": self.calc_definition.replace(b'pptline=1', b'pptline=0')},
            {"calculation_definition": self.calc_definition.replace(b' note1 "Authored" "" 10 CHAR\n', b'')},
        ):
            with self.subTest(kwargs=list(kwargs)), self.assertRaises((ValueError, ToolSafetyError)):
                self.run_adapter(**kwargs)
            self.assertEqual(self.app.connects, 0)

    def test_calculation_old_api_value_must_match_observed_profile_not_raw_hash_text(self):
        self.complete_fixture()
        self.failure("calc_old_api_mismatch", False)
        self.assertEqual(self.app.sets, 0)

    def test_calculation_name_must_match_endpoint_pair(self):
        self.complete_fixture()
        self.failure("calc_name_mismatch", False)
        self.assertEqual(self.app.sets, 0)

    def test_calculation_explicit_blank_char_is_not_an_inferred_zero(self):
        self.complete_fixture()
        self.failure("calc_blank_mismatch", False)
        self.assertEqual(self.app.sets, 0)

    def test_calculation_nonselected_post_edit_drift_requires_recovery(self):
        self.complete_fixture()
        self.failure("calc_after_drift", True)

    def test_calculation_nonselected_reopen_drift_refused(self):
        self.complete_fixture()
        self.failure("calc_reopen_drift", False)
        self.assertFalse(self.journal.value["compiler_dependency_binding_verified"])

    def test_calculation_export_must_contain_exact_new_companion(self):
        self.complete_fixture()
        self.failure("calc_export_mismatch", False)

    def test_calculation_extra_parameter_inventory_refused_before_setters(self):
        self.complete_fixture()
        self.failure("calc_extra_parameter", False)
        self.assertEqual(self.app.sets, 0)

    def test_calculation_wrong_component_type_refused_before_setters(self):
        self.complete_fixture()
        self.failure("wrong_calculation_type", False)
        self.assertEqual(self.app.sets, 0)

    def test_preconditions_refuse_before_sdk(self):
        for label in ("source_hash", "plan", "boolean_alias", "companion", "fresh_path"):
            with self.subTest(label=label):
                # These failures leave the journal and SDK untouched, so reuse is safe here.
                changes = {}
                if label == "source_hash": changes["source_sha256"] = "0" * 64
                if label == "plan":
                    plan = copy.deepcopy(self.plan); plan["operations"][0]["new_value"] = "wrong"; changes["plan"] = plan
                if label == "boolean_alias":
                    plan = copy.deepcopy(self.plan); plan["files_written"] = False; changes["plan"] = plan
                if label == "companion": (self.inp.parent / "new_line.tli").write_bytes(b"changed")
                if label == "fresh_path": self.candidate.parent.mkdir()
                with self.assertRaises((ValueError, ToolSafetyError)):
                    self.run_adapter(**changes)
                self.assertEqual(self.app.connects, 0)
                if label == "companion": (self.inp.parent / "new_line.tli").write_bytes(TLI)
                if label == "fresh_path": self.candidate.parent.rmdir()

    def test_zero_external_attributes_survive_source_archive_projection(self):
        with zipfile.ZipFile(self.inp) as incoming:
            entries = [(info, incoming.read(info)) for info in incoming.infolist()]
            comment = incoming.comment
        with zipfile.ZipFile(self.inp, "w") as outgoing:
            outgoing.comment = comment
            for info, raw in entries:
                outgoing.writestr(info, raw)
                info.external_attr = 0
        self.digest = sha(self.inp)
        result = self.run_adapter()
        self.assertEqual(result["status"], "verified_hybrid_binding")
        with zipfile.ZipFile(self.inp) as incoming, zipfile.ZipFile(self.candidate) as candidate:
            self.assertEqual([i.external_attr for i in incoming.infolist()], [0, 0, 0])
            self.assertEqual([i.external_attr for i in candidate.infolist()], [0, 0, 0])
            self.assertEqual(incoming.read("model.rtx"), candidate.read("model.rtx"))

    def test_unsafe_archive_names_and_member_bound_refused_before_sdk(self):
        original = self.inp.read_bytes()
        for names in (("model.dfx", "MODEL.DFX"), ("model.dfx", "../escape"),
                      ("model.dfx", *(f"part{i}" for i in range(64)))):
            with self.subTest(names=names[:2]):
                with zipfile.ZipFile(self.inp, "w") as archive:
                    for name in names:
                        archive.writestr(name, source() if name.lower().endswith(".dfx") else b"x")
                with self.assertRaises(ToolSafetyError):
                    self.run_adapter(source_sha256=sha(self.inp))
                self.assertEqual(self.app.connects, 0)
                self.inp.write_bytes(original)

    def failure(self, mode, recovery):
        with self.assertRaises((ToolSafetyError, RuntimeError)):
            self.run_adapter(mode)
        self.assertEqual(self.journal.value["status"], "operator_recovery_required" if recovery else "failed")
        self.assertEqual(self.app.disconnects, 1)
        self.assertFalse(self.journal.value.get("candidate_reopen_verified", False))

    def test_extra_inventory_refused_and_clean_owned_case_closed(self): self.failure("extra_parameter", False)
    def test_wrong_component_refused_and_clean_owned_case_closed(self): self.failure("wrong_component", False)
    def test_line_pair_alias_mismatch_refused(self): self.failure("bad_pair", False)
    def test_wrong_native_phase_count_refused_before_setters(self):
        self.failure("wrong_phases", False)
        self.assertEqual(self.app.sets, 0)
    def test_wrong_native_line_percentage_refused_before_setters(self):
        self.failure("wrong_percent", False)
        self.assertEqual(self.app.sets, 0)
    def test_wrong_native_endpoint_direction_refused_before_setters(self):
        self.failure("wrong_direction", False)
        self.assertEqual(self.app.sets, 0)
    def test_stable_source_import_drift_refused_before_setters(self):
        self.failure("baseline_stored_drift", False)
        self.assertEqual(self.app.sets, 0)
    def test_unexpected_default_import_refused_before_setters(self):
        self.failure("baseline_default_drift", False)
        self.assertEqual(self.app.sets, 0)
    def test_nonselected_after_drift_requires_recovery_for_dirty_case(self): self.failure("after_drift", True)
    def test_nonselected_reopen_drift_refused_with_clean_cleanup(self): self.failure("reopen_drift", False)
    def test_export_exact_selected_value_mismatch_refused(self): self.failure("export_mismatch", False)
    def test_source_hash_race_requires_recovery_for_dirty_case(self): self.failure("source_race", True)
    def test_candidate_hash_race_refused(self): self.failure("candidate_race", False)
    def test_wrong_case_identity_never_force_closes(self): self.failure("wrong_identity", True)
    def test_partial_set_failure_never_force_closes(self): self.failure("set_error", True)
    def test_uncertain_save_requires_recovery(self): self.failure("save_error", True)
    def test_uncertain_reopen_requires_recovery(self): self.failure("reopen_error", True)
    def test_uncertain_close_is_not_retried(self):
        self.failure("close_error", True)
        self.assertEqual(self.app.closes, 1)

    def test_disconnect_failure_cannot_report_success(self):
        with self.assertRaises(ToolSafetyError): self.run_adapter("disconnect_error")
        self.assertEqual(self.journal.value["status"], "operator_recovery_required")
        self.assertFalse(self.journal.value["cleanup_verified"])

    def test_absent_candidate_final_hash_recorded_after_cleanup(self):
        self.failure("final_hash_error", False)
        self.assertTrue(self.journal.value["final_hash_errors"])
        self.assertTrue(self.journal.value["cleanup_verified"])

    def test_rpc_allowlist_requires_matching_pending_operation_and_refuses_live_calls(self):
        value = self.journal.value
        value.update(owned_case=101, identity_verified=True, read_ids=[11, 12],
                     read_parameters={"11": ["Tnam1"]}, binding_operations=self.plan["operations"])
        def allowed(path, method, args):
            return allow_line_binding_rpc(path, method, args, self.journal, self.inp, self.export, self.candidate)
        for path, method, args in (("rscad", "getRacks", []), ("rscad.case:101", "compile", []),
                                   ("rscad.case:101", "run", []), ("rscad.case:101", "save", []),
                                   ("rscad.case:101", "close", [True]),
                                   ("rscad.case:101.draft.comp_id:99", "getParameter", ["Tnam1"])):
            value["permitted_rpc"] = [path, method, args]
            value["native_calls"] = [{"status": "started", "mutation": True, "operation": method,
                                       "arguments": {"path": path, "method": method, "args": args}}]
            self.assertFalse(allowed(path, method, args))
        path, method, args = "rscad.case:101", "close", [False]
        value["permitted_rpc"] = [path, method, args]
        value["native_calls"] = [{"status": "started", "mutation": True, "operation": "get_version",
                                   "arguments": {"path": path, "method": method, "args": args}}]
        self.assertFalse(allowed(path, method, args))
        value["native_calls"][-1]["operation"] = "close"
        self.assertTrue(allowed(path, method, args))
        self.assertFalse(allowed(path, method, [0]))
        value["status"] = "operator_recovery_required"
        self.assertFalse(allowed(path, method, args))
        self.assertTrue(allowed("rscad", "ping", []))


if __name__ == "__main__":
    unittest.main()

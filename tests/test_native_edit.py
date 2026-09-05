"""Synthetic failure injection; these tests never import or connect the SDK."""
import test_environment
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from rtds_agent.core.native_edit import NativeJournal, edit_case, paste_ids, values_equal
from rtds_agent.core.topology_parser import read_rtfx_dfx, parse_dfx_components, parse_dfx_entities
from rtds_agent.core.model_ir import semantic_diff, model_ir
from rtds_agent.model_editor import edit_rscad_model
from rtds_agent.safety import sha256_file
import test_engineering_editor as editor_fixture
from test_engineering_editor import block


class FakeComponent:
    def __init__(self, case, row):
        self.case, self.row = case, row
        self.unique_id, self.component_type = row["uuid"], row["component_type"]
    def get_parameter(self, name): return self.row["parameters"][name]
    def set_parameter(self, name, value):
        self.row["parameters"][name] = value
        self.case.state.modified = True
        if self.case.app.fail == "write_after_mutation": raise RuntimeError("Response lost after mutation")
    @property
    def location(self): return tuple(self.row["location"])
    @location.setter
    def location(self, value):
        self.row["location"] = list(value)
        self.case.state.modified = True


class FakeCase:
    def __init__(self, app, path):
        self.app, self.file, self.caseid = app, str(path), len(app.cases)+1
        self.state = SimpleNamespace(run_state="stopped", modified=False)
        self.rows = parse_dfx_components(read_rtfx_dfx(Path(path))[1])
        self.draft = SimpleNamespace(get_object=lambda i: next((FakeComponent(self,r) for r in self.rows if r["uuid"] == i),None))
        self.closed = False
    def save(self, path):
        old = Path(self.file)
        text = "DRAFT 1\nSUBSYSTEM-START:\n"+"".join(block(r["component_type"],r["uuid"],r["parameters"],r["location"]) for r in self.rows)+"SUBSYSTEM-END:\n"
        with zipfile.ZipFile(old) as source, zipfile.ZipFile(path,"w") as target:
            for item in source.infolist(): target.writestr(item, text if item.filename.endswith(".dfx") else source.read(item))
            target.comment = source.comment
        self.file, self.state.modified = path, False
    def close(self, force=False):
        if force: raise AssertionError("Force close forbidden")
        if self.app.fail == "close": return False
        self.closed = True
        return True


class FakeApp:
    def __init__(self, fail=None): self.cases, self.fail, self.disconnected = [], fail, False
    def connect(self): pass
    def disconnect(self, terminate=False):
        if terminate: raise AssertionError("Application termination forbidden")
        if self.fail == "disconnect": raise RuntimeError("Lost disconnect")
        self.disconnected = True
    def get_version(self): return "2.7"
    def get_case(self, *, file, open_file):
        if open_file: raise AssertionError("Implicit opening forbidden")
        return next((c for c in self.cases if c.file == file and not c.closed), None)
    def open_case(self, path):
        c = FakeCase(self, path)
        self.cases.append(c)
        if self.fail == "wrong_identity": c.file = "wrong-case.rtfx"
        if self.fail == "reopen_readback" and len(self.cases) == 2: c.rows[0]["parameters"]["Gain"] = "9"
        return c


class NativeEditTests(unittest.TestCase):
    setUp = editor_fixture.EngineeringEditorTests.setUp
    write = editor_fixture.EngineeringEditorTests.write
    request = editor_fixture.EngineeringEditorTests.request

    def op(self): return {**self.identity,"op":"set_parameter","parameter":"Gain","expected_old_value":"1","new_value":"2"}
    def adapter(self, fail=None):
        directory = self.data / "adapter"; directory.mkdir(parents=True,exist_ok=True)
        journal = NativeJournal(directory / "journal.json")
        app = FakeApp(fail)
        return directory, journal, app

    def test_save_close_exact_reopen_readbacks_and_original_protection(self):
        directory,journal,app = self.adapter()
        digest = sha256_file(self.project)
        result = edit_case(app,self.project,directory/"result.rtfx",[self.op()],journal)
        self.assertEqual(sha256_file(self.project),digest)
        self.assertTrue(result["cleanup_verified"])
        self.assertTrue(result["closed_before_reopen"] and result["reopened"])
        self.assertEqual(len(result["readbacks"]),3)
        self.assertTrue(all(c.closed for c in app.cases))
        self.assertFalse(result["integration_qualified"])

    def test_lost_response_records_mutation_and_retains_unsaved_case(self):
        directory,journal,app = self.adapter("write_after_mutation")
        with self.assertRaises(RuntimeError): edit_case(app,self.project,directory/"result.rtfx",[self.op()],journal)
        evidence = json.loads(journal.path.read_text())
        self.assertTrue(evidence["native_mutation_possible"])
        self.assertEqual(evidence["status"],"operator_recovery_required")
        self.assertFalse(app.cases[0].closed)
        self.assertEqual(sum(c["operation"]=="set_parameter" for c in evidence["native_calls"]),1)
        with self.assertRaisesRegex(ValueError,"recovery"): journal.call("retry",lambda: None)

    def test_wrong_case_never_closed(self):
        directory,journal,app = self.adapter("wrong_identity")
        with self.assertRaises(ValueError): edit_case(app,self.project,directory/"result.rtfx",[self.op()],journal)
        self.assertFalse(app.cases[0].closed)
        self.assertEqual(journal.value["status"],"operator_recovery_required")

    def test_reopen_mismatch_and_cleanup_failures_never_success(self):
        for failure in ("reopen_readback","close","disconnect"):
            with self.subTest(failure=failure):
                folder=self.data/failure;folder.mkdir()
                journal=NativeJournal(folder/"journal.json")
                with self.assertRaises((ValueError,RuntimeError)):
                    edit_case(FakeApp(failure),self.project,folder/"result.rtfx",[self.op()],journal)
                self.assertNotEqual(journal.value["status"],"verified_edit")

    def test_expected_old_mismatch_no_parameter_write(self):
        directory,journal,app = self.adapter()
        with self.assertRaises(ValueError): edit_case(app,self.project,directory/"result.rtfx",[{**self.op(),"expected_old_value":"3"}],journal)
        self.assertTrue(app.cases[0].closed)
        self.assertFalse(any(c["operation"]=="set_parameter" for c in journal.value["native_calls"]))

    def test_group_sentinel_is_not_resolved_or_treated_as_success(self):
        directory,journal,_=self.adapter()
        canvas=SimpleNamespace(identifier=10,_paste=lambda loc,i:[7,-1,9],get_object=lambda i:self.fail("Sentinel must not be dereferenced"))
        with self.assertRaisesRegex(ValueError,"owned"): paste_ids(canvas,[32,64],journal)
        journal.value.update(owned_case=17,identity_verified=True)
        result=paste_ids(canvas,[32,64],journal)
        self.assertEqual(result["component_ids"],[7,9])
        self.assertEqual(result["group_sentinels"],1)
        self.assertFalse(result["structure_verified"])
        self.assertTrue(journal.value["native_mutation_possible"])

    def test_native_preview_and_auto_do_not_launch(self):
        req={**self.request([self.op()]),"backend":"auto"}
        with patch("rtds_agent.native_editor.subprocess.run",side_effect=AssertionError("No process permitted")):
            preview=edit_rscad_model(req)
            self.assertEqual(preview["backend"],"static")
            with self.assertRaisesRegex(ValueError,"preview only"):
                edit_rscad_model({**req,"mode":"apply","preview_id":preview["preview_id"]})
            native=edit_rscad_model({**req,"backend":"native"})
            self.assertFalse(native["sdk"]["available"])
            with self.assertRaisesRegex(ValueError,"scope"):
                edit_rscad_model({**req,"backend":"native","mode":"apply","preview_id":native["preview_id"]})

    def test_native_publication_and_policy_preview_binding(self):
        sdk={"available":True,"sdk_version":"1.1","evidence_id":"synthetic"}
        def worker(command, **kwargs):
            job_path=Path(command[-1]);job=json.loads(job_path.read_text(encoding="utf-8"))
            journal=NativeJournal(job_path.parent/"native_journal.json")
            edit_case(FakeApp(),job["input_path"],job["output_path"],job["request"]["operations"],journal)
            return SimpleNamespace(returncode=0)
        req={**self.request([self.op()]),"backend":"native"}
        with patch("rtds_agent.native_editor.inspect_native_sdk",return_value=sdk),patch("rtds_agent.native_editor.subprocess.run",side_effect=worker):
            preview=edit_rscad_model(req)
            with self.assertRaisesRegex(ValueError,"preview"):
                edit_rscad_model({**req,"mode":"apply","preview_id":"0"*64})
            result=edit_rscad_model({**req,"mode":"apply","preview_id":preview["preview_id"]})
        self.assertEqual(result["status"],"completed")
        self.assertTrue(result["native_evidence"]["cleanup_verified"])
        self.assertEqual(sha256_file(self.project),req["source_sha256"])

    def test_worker_timeout_retains_journal_and_blocks_followup(self):
        import subprocess
        sdk={"available":True,"sdk_version":"1.1","evidence_id":"synthetic"}
        req={**self.request([self.op()]),"backend":"native"}
        with patch("rtds_agent.native_editor.inspect_native_sdk",return_value=sdk),patch("rtds_agent.native_editor.subprocess.run",side_effect=subprocess.TimeoutExpired("native",120)) as run:
            preview=edit_rscad_model(req)
            apply={**req,"mode":"apply","preview_id":preview["preview_id"]}
            with self.assertRaises(subprocess.TimeoutExpired): edit_rscad_model(apply)
            with self.assertRaisesRegex(ValueError,"recovery"): edit_rscad_model(apply)
            self.assertEqual(run.call_count,1)
        self.assertTrue((self.data/"native_recovery_required.json").exists())
        from rtds_agent.policy import execution_lock, configure_policy, read_policy
        from rtds_agent.execution import _execute
        from rtds_agent.core.state_machine import ApprovalAction
        configure_policy(self.settings,["compile","runtime_start_stop"],[1],"synthetic operator")
        with patch("rtds_agent.execution._load_workflow",side_effect=AssertionError("Recovery gate must precede workflow/backend")):
            for action in (ApprovalAction.COMPILE,ApprovalAction.RUNTIME):
                with self.assertRaisesRegex(PermissionError,"blocks live execution"):
                    _execute("unused",action)
        # CLI policy revocation uses the same lock and must remain possible.
        with execution_lock(self.settings): configure_policy(self.settings,[],[],"synthetic operator")
        self.assertEqual(read_policy(self.settings)["status"],"inactive")
        self.assertFalse((self.data/"execution.lock").exists())

    def test_unrequested_native_change_prevents_publication(self):
        sdk={"available":True,"sdk_version":"1.1","evidence_id":"synthetic"}
        def worker(command, **kwargs):
            job_path=Path(command[-1]);job=json.loads(job_path.read_text(encoding="utf-8"))
            journal=NativeJournal(job_path.parent/"native_journal.json")
            extra={**self.identity,"op":"set_string","parameter":"Name","expected_old_value":"gain","new_value":"unexpected"}
            edit_case(FakeApp(),job["input_path"],job["output_path"],[*job["request"]["operations"],extra],journal)
            return SimpleNamespace(returncode=0)
        req={**self.request([self.op()]),"backend":"native"}
        with patch("rtds_agent.native_editor.inspect_native_sdk",return_value=sdk),patch("rtds_agent.native_editor.subprocess.run",side_effect=worker):
            preview=edit_rscad_model(req)
            with self.assertRaisesRegex(ValueError,"semantics"):
                edit_rscad_model({**req,"mode":"apply","preview_id":preview["preview_id"]})
        self.assertFalse((self.data/"projects/model_edits").exists())
        self.assertFalse((self.data/"native_recovery_required.json").exists())
        self.assertEqual(sha256_file(self.project),req["source_sha256"])

    def test_group_inspection_is_additive_and_edit_still_refuses(self):
        self.dfx=self.dfx.replace('COMPONENT_TYPE=synthetic_gain','COMPONENT_TYPE=GROUP\n0 0 0 0 0\nCOMPONENT_TYPE=synthetic_gain').replace('COMPONENT_TYPE=WIRE','GROUP-END:\nCOMPONENT_TYPE=WIRE')
        self.write()
        from rtds_agent.project_tools import inspect_rscad_project, compare_project_versions
        ir=inspect_rscad_project(str(self.project),representation="ir")
        self.assertIn("groups",str(ir))
        comparison=compare_project_versions(str(self.project),str(self.project))
        self.assertEqual(comparison["group_changes"],[])
        with self.assertRaisesRegex(ValueError,"fully identified"):
            edit_rscad_model(self.request([self.op()]))
        from rtds_agent.core.structured_patch import patch_dfx
        with self.assertRaisesRegex(ValueError,"block count"):
            patch_dfx(self.dfx.encode(),[self.op()])

    def test_decimal_readback_never_accepts_nan_or_boolean_as_number(self):
        self.assertTrue(values_equal(1.0,"1",True))
        self.assertFalse(values_equal(True,"1",True))
        self.assertFalse(values_equal("NaN","NaN",True))

    def test_version_comparison_does_not_inherit_optional_ir_limits(self):
        import rtds_agent.project_tools as projects
        path,scope,doc=projects._document(str(self.project))
        rows=[]
        for i in range(5001):
            row=copy.deepcopy(doc["components"][0]);row["uuid"]=i
            rows.append(row)
        doc["components"]=rows
        with patch.object(projects,"_document",return_value=(path,scope,doc)):
            compared=projects.compare_project_versions(str(path),str(path))
        self.assertEqual(compared["status"],"completed")
        self.assertEqual(compared["component_change_count"],0)


class GroupParserTests(unittest.TestCase):
    def group(self, inner): return "COMPONENT_TYPE=GROUP\n100 200 0 0 0\n"+inner+"GROUP-END:\n"
    def document(self,text):
        rows,groups=parse_dfx_entities("SUBSYSTEM-START:\n"+text+"SUBSYSTEM-END:\n")
        return dict(components=rows,groups=groups,nets=[],ports=[],segments=[],source={},coverage={},warnings=[],limitations=[])

    def test_group_children_are_components_not_fake_uuid(self):
        doc=self.document(self.group(block("A",7,{},(96,192))+block("B",8,{},(128,224))))
        self.assertEqual([c["uuid"] for c in doc["components"]],[7,8])
        self.assertEqual(doc["groups"][0]["bounds"],[96,192,128,224])
        self.assertNotIn("uuid",doc["groups"][0])
        self.assertEqual(model_ir(doc)["groups"],doc["groups"])

    def test_nested_groups_membership_and_bounds(self):
        doc=self.document(self.group(block("A",1,{},(32,64))+self.group(block("B",2,{},(96,128)))))
        outer,inner=doc["groups"]
        self.assertEqual(inner["parent_group"],outer["group_id"])
        self.assertEqual(outer["members"][1],{"kind":"group","group_id":inner["group_id"]})
        self.assertEqual(outer["bounds"],[32,64,96,128])

    def test_group_diff_add_remove_move_members_and_structure(self):
        a=self.document(self.group(block("A",1,{})))
        b=copy.deepcopy(a);b["groups"][0]["location"]=[200,300]
        diff=semantic_diff(a,b)
        self.assertEqual(len(diff["group_moved"]),1)
        self.assertEqual(len(diff["group_structure_changed"]),1)
        b["groups"][0]["members"]=[]
        self.assertEqual(len(semantic_diff(a,b)["group_member_changed"]),1)
        b["groups"]=[]
        self.assertEqual(len(semantic_diff(a,b)["group_removed"]),1)
        self.assertEqual(len(semantic_diff(b,a)["group_added"]),1)

    def test_group_hierarchy_context_and_malformed_boundaries(self):
        text="HIERARCHY-START:\n"+block("HIERARCHY",9,{"Name":"inner"})+self.group(block("A",1,{}))+"HIERARCHY-END:\n"
        doc=self.document(text)
        self.assertEqual(doc["groups"][0]["context"],"subsystem:0/inner:9")
        for malformed in ("GROUP-END:\n",self.group("").replace("GROUP-END:\n",""),"COMPONENT_TYPE=GROUP\ninvalid\nGROUP-END:\n",self.group(self.group(""))*2001):
            with self.assertRaises(ValueError): self.document(malformed)

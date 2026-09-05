"""Synthetic two-gain patch transaction and regression cases."""
import test_environment  # isolate config and credentials before application imports
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_public_release as fixtures
from rtds_agent.core.state_machine import sha256_file
from rtds_agent import editing, knowledge

class BatchEditingTests(unittest.TestCase):
    prepare = fixtures.PublicReleaseTests.prepare
    def setUp(self):
        fixtures.PublicReleaseTests.setUp(self)
        (self.defs / "synthetic_gain").write_text('PARAMETERS:\n Kp "Proportional" "pu" REAL 1 0 10\n Ki "Integral" "pu" REAL 1 0 10\n Count "Count" "" INTEGER 1 0 10\n File "Input data file" "" FILE companion.txt\nNODES:\n', encoding="utf-8")
        self.companion = self.sources / "companion.txt"
        self.companion.write_text("synthetic samples", encoding="utf-8")
        with zipfile.ZipFile(self.project,"w") as archive:
            archive.writestr("synthetic.dfx", 'DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 4\nPARAMETERS-START:\nKp: 1\nKi: 1\nCount: 1\nFile: companion.txt\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n')
            archive.writestr("payload.txt","untouched payload")
            archive.comment = b"untouched comment"
        snapshot = knowledge.index_parameters(str(self.project))["parameter_catalog_snapshot_id"]
        self.original = sha256_file(self.project)
        self.request = {"schema_version":"1.0","source_project":str(self.project),"source_sha256":self.original,
                        "rscad_version":"2.7.3","project_label":"two-gains","parameter_catalog_snapshot_id":snapshot,
                        "operations":[self.operation("Kp","2"), self.operation("Ki","3")]}

    def operation(self,name,new):
        return {"op":"set_parameter","component_id":1,"context":"subsystem:0","component_type":"synthetic_gain",
                "parameter":name,"expected_old_value":"1","new_value":new}

    def test_two_parameters_preserve_source_companions_members_and_topology(self):
        result = editing.apply_parameter_patch_batch(self.request)
        self.assertEqual(sha256_file(self.project), self.original)
        working = Path(result["working_project"])
        self.assertTrue(working.is_file())
        self.assertEqual((working.parent / self.companion.name).read_bytes(),self.companion.read_bytes())
        with zipfile.ZipFile(working) as archive:
            self.assertEqual(archive.read("payload.txt"),b"untouched payload")
            self.assertEqual(archive.comment,b"untouched comment")
        from rtds_agent.project_tools import compare_project_versions
        diff=compare_project_versions(str(self.project),str(working))
        self.assertTrue(diff["same_static_topology"])
        self.assertEqual({v["parameter"] for v in diff["component_changes"][0]["parameter_changes"]},{"Kp","Ki"})
        self.assertEqual(result["parameter_catalog_snapshot_ids"],[self.request["parameter_catalog_snapshot_id"]])
        manifest=json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["working"]["path"],str(working))
        self.assertEqual(manifest["companions"][0]["working"]["sha256"],sha256_file(self.companion))

    def test_invalid_second_operation_publishes_nothing(self):
        self.request["operations"][1]["expected_old_value"]="wrong"
        with self.assertRaises(ValueError): editing.apply_parameter_patch_batch(self.request)
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))
        self.assertEqual(sha256_file(self.project),self.original)

    def test_stale_duplicate_context_type_old_value_and_limits(self):
        changes=[lambda r:r.update(source_sha256="0"*64),
                 lambda r:r["operations"].append(copy.deepcopy(r["operations"][0])),
                 lambda r:r["operations"][1].update(context="wrong"),
                 lambda r:r["operations"][1].update(component_type="wrong"),
                 lambda r:r["operations"][1].update(expected_old_value="9"),
                 lambda r:r["operations"][1].update(new_value="11"),
                 lambda r:r["operations"][1].update(component_id=True),
                 lambda r:r.update(operations=r["operations"]*11),
                 lambda r:r["operations"][1].update(unsafe=True),
                 lambda r:r.update(unsafe=True)]
        for change in changes:
            with self.subTest(change=change):
                request=copy.deepcopy(self.request);change(request)
                with self.assertRaises(ValueError):editing.apply_parameter_patch_batch(request)
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))

    def test_nonfinite_and_non_numeric_integer_rejected(self):
        for value in ("NaN","Inf","-Inf"):
            request=copy.deepcopy(self.request);request["operations"][1]["new_value"]=value
            with self.assertRaises(ValueError):editing.apply_parameter_patch_batch(request)
        for value in (True,"1.5","True"):
            request=copy.deepcopy(self.request);request["operations"][1]=self.operation("Count",value)
            with self.assertRaises(ValueError):editing.apply_parameter_patch_batch(request)

    def test_failure_after_staging_is_not_listed_and_is_cleaned(self):
        from rtds_agent.core import structured_patch
        def fail(*args,**kwargs):
            from rtds_agent.project_tools import list_rscad_projects
            self.assertEqual(list_rscad_projects()["projects"],[])
            raise RuntimeError("synthetic write failure")
        with patch.object(structured_patch,"write_patched_archive",side_effect=fail):
            with self.assertRaises(RuntimeError):editing.apply_parameter_patch_batch(self.request)
        self.assertEqual(list((self.data / ".patch-staging").iterdir()),[])
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))

    def test_single_api_compatibility(self):
        result=editing.apply_parameter_patch(str(self.project),self.original,1,"subsystem:0","synthetic_gain","Kp","1","2")
        self.assertEqual(len(result["changes"]),1)

    def test_source_companion_mutation_prevents_publication(self):
        from rtds_agent.core import structured_patch
        original=structured_patch.topology_summary
        def change(path,*args):
            result=original(path,*args)
            self.companion.write_text("changed",encoding="utf-8")
            return result
        with patch.object(structured_patch,"topology_summary",side_effect=change):
            with self.assertRaises(ValueError):editing.apply_parameter_patch_batch(self.request)
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))

    def test_exact_twenty_operation_limit_is_accepted(self):
        definition=self.defs/"synthetic_gain"
        text=definition.read_text(encoding="utf-8")
        text=text.replace("NODES:","".join(f' P{i} "Synthetic" "" REAL 1 0 10\n' for i in range(20))+"NODES:")
        definition.write_text(text,encoding="utf-8")
        with zipfile.ZipFile(self.project) as archive:
            dfx=archive.read("synthetic.dfx").decode()
        dfx=dfx.replace("PARAMETERS-END:","".join(f"P{i}: 1\n" for i in range(20))+"PARAMETERS-END:").replace("0 0 0 0 4","0 0 0 0 24")
        with zipfile.ZipFile(self.project,"w") as archive:
            archive.writestr("synthetic.dfx",dfx)
        self.request["source_sha256"]=sha256_file(self.project)
        self.request["parameter_catalog_snapshot_id"]=knowledge.index_parameters(str(self.project))["parameter_catalog_snapshot_id"]
        self.request["operations"]=[self.operation(f"P{i}","2") for i in range(20)]
        self.assertEqual(len(editing.apply_parameter_patch_batch(self.request)["changes"]),20)

    def test_transient_source_edit_cannot_inject_unrequested_changes(self):
        from rtds_agent.core import structured_patch
        original_bytes=self.project.read_bytes()
        original_archive=structured_patch.archive_snapshot
        original_patch=structured_patch.patch_dfx
        changed=[]
        def archive_snapshot(path):
            result=original_archive(path)
            if Path(path)==self.project and not changed:
                changed.append(True)
                with zipfile.ZipFile(self.project) as archive:
                    members=[(info,archive.read(info.filename)) for info in archive.infolist()]
                    comment=archive.comment
                with zipfile.ZipFile(self.project,"w") as archive:
                    archive.comment=comment
                    for info,data in members:
                        if info.filename.endswith(".dfx"):data=data.replace(b"Count: 1",b"Count: 2")
                        archive.writestr(info,data)
            return result
        def patch_then_restore(data,operations):
            result=original_patch(data,operations)
            self.project.write_bytes(original_bytes)
            return result
        with patch.object(structured_patch,"archive_snapshot",side_effect=archive_snapshot), \
             patch.object(structured_patch,"patch_dfx",side_effect=patch_then_restore):
            result=editing.apply_parameter_patch_batch(self.request)
        with zipfile.ZipFile(result["working_project"]) as archive:
            self.assertIn(b"Count: 1",archive.read("synthetic.dfx"))
        self.assertEqual({c["parameter"] for c in result["changes"]},{"Kp","Ki"})
        self.assertEqual(self.project.read_bytes(),original_bytes)

    def test_current_definition_root_detects_new_required_companion(self):
        from rtds_agent.settings import Settings
        with zipfile.ZipFile(self.project) as archive:
            dfx=archive.read("synthetic.dfx").decode()
        dfx=dfx.replace("PARAMETERS-END:","Flag: required_missing_input\nPARAMETERS-END:")
        with zipfile.ZipFile(self.project,"w") as archive:
            archive.writestr("synthetic.dfx",dfx)
        new_vendor=self.root / "second installed version"
        new_defs=new_vendor / "MLIB/COMPONENTS"
        new_defs.mkdir(parents=True)
        text=(self.defs / "synthetic_gain").read_text(encoding="utf-8")
        text=text.replace("NODES:",' Flag "Required input file" "" FILE required_missing_input\nNODES:')
        (new_defs / "synthetic_gain").write_text(text,encoding="utf-8")
        settings=Settings(self.data,new_vendor,(self.sources,),(self.docs,)).validated()
        self.config.write_text(json.dumps(settings.as_dict()),encoding="utf-8")
        self.request["source_sha256"]=sha256_file(self.project)
        self.request["parameter_catalog_snapshot_id"]=knowledge.index_parameters(str(self.project))["parameter_catalog_snapshot_id"]
        from rtds_agent.core.companion_dependencies import CompanionDiscoveryError
        with self.assertRaisesRegex(CompanionDiscoveryError,"companion|dependencies"):
            editing.apply_parameter_patch_batch(self.request)
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))

    def test_configuration_change_during_patch_prevents_publication(self):
        from rtds_agent.core import structured_patch
        original=structured_patch.topology_summary
        def change(path,*args):
            result=original(path,*args)
            settings=self.settings.as_dict()
            settings["document_roots"].append(str(self.root / "extra-documents"))
            self.config.write_text(json.dumps(settings),encoding="utf-8")
            return result
        with patch.object(structured_patch,"topology_summary",side_effect=change):
            with self.assertRaisesRegex(ValueError,"Configuration changed"):
                editing.apply_parameter_patch_batch(self.request)
        self.assertFalse(list(self.data.glob("projects/**/*.rtfx")))

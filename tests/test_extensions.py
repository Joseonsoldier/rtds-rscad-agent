"""Authored extension fixtures; no vendor imports, connections or format qualification."""
import test_environment
import builtins
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_public_release as fixture
from rtds_agent import extension_support, extension_trials, runtime_layout, project_tools
from rtds_agent.safety import sha256_file

DEFINITION = '''PARAMETERS:
 Mode "Mode" "Off;On" TOGGLE Off
 File "Input data file" "" FILE samples.txt
NODES:
 #IF Mode=0
 OUT 1 0 OUTPUT INTEGER
 #ELSE
 NEW 1 0 OUTPUT REAL
 #END
'''
DFX = '''DRAFT 1
SUBSYSTEM-START:
COMPONENT_TYPE=synthetic_selector
0 0 0 0 2
PARAMETERS-START:
Mode: Off
File: samples.txt
PARAMETERS-END:
UUID: 1
SUBSYSTEM-END:
'''
RTX = '''RSCAD 2.3p
VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "authored" VIEW-CANVAS-SIZE:3000,2000
COMPONENT: TAGGED_V2.2_FRAME
 NAME: frame
 UUID: 10
COMPONENT: TAGGED_V2.2_SWITCH
 NAME: control
 GROUP: (NONE)
 GROUP: Subsystem #1|CTLs|Inputs
 DESC: SW1
 UUID: 11
 MIN: 0
 MAX: 1
COMPONENT-END:
COMPONENT-END:
COMPONENT: TAGGED_V2.2_METER
 NAME: output
 GROUP: Subsystem #1|CTLs|Outputs
 DESC: OUT
 UUID: 12
COMPONENT-END:
VIEW-END:
'''


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        (self.defs / "synthetic_selector").write_text(DEFINITION, encoding="utf-8")
        self.companion = self.sources / "samples.txt"
        self.companion.write_text("authored data", encoding="utf-8")
        self.write_project()
        self.refresh()

    def write_project(self, dfx=DFX, rtx=RTX):
        with zipfile.ZipFile(self.project, "w") as z:
            z.writestr("synthetic.dfx", dfx)
            if rtx is not None:
                z.writestr("synthetic.rtx", rtx)
            z.writestr("unchanged.txt", "preserved")
            z.comment = b"authored archive"

    def refresh(self):
        snapshot = project_tools.inspect_rscad_project(str(self.project))["snapshot_id"]
        self.request = {"source_project": str(self.project), "source_sha256": sha256_file(self.project),
                        "snapshot_id": snapshot, "component_id": 1, "context": "subsystem:0",
                        "component_type": "synthetic_selector", "parameter": "Mode", "expected_old_value": "Off", "new_value": "On"}

    def test_preview_compares_type_and_active_port_without_any_file_write(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = extension_trials.preview_selector_change(self.request)
        self.assertEqual(result["status"], "analyzed")
        self.assertEqual(result["removed_or_changed_nodes"][0]["name"], "OUT")
        self.assertEqual(result["added_or_changed_nodes"][0]["name"], "NEW")
        self.assertTrue(result["node_structure_changed"])
        self.assertFalse(result["automatic_application_supported"])
        self.assertEqual(result["non_node_and_dependency_effects"], "not_evaluated")
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertEqual(result["preview_id"], extension_trials.preview_selector_change(self.request)["preview_id"])

    def test_stale_hash_snapshot_and_definition_rejected(self):
        for field in ("source_sha256", "snapshot_id"):
            request = copy.deepcopy(self.request); request[field] = "0" * 64
            with self.assertRaises(ValueError): extension_trials.preview_selector_change(request)
        (self.defs / "synthetic_selector").write_text(DEFINITION + "// changed", encoding="utf-8")
        with self.assertRaises(ValueError): extension_trials.preview_selector_change(self.request)

    def test_unknown_fields_bool_identity_and_bad_option_rejected(self):
        for delta in ({"unsafe": True}, {"component_id": True}, {"component_type": "other"}, {"context": "other"},
                      {"expected_old_value": "On"}, {"new_value": "on"}, {"new_value": "Off"}, {"new_value": "On\nrun"}):
            with self.subTest(delta=delta):
                request = {**self.request, **delta}
                with self.assertRaises(ValueError): extension_trials.preview_selector_change(request)

    def test_non_toggle_and_ambiguous_options_rejected(self):
        for text in (DEFINITION.replace('"Off;On" TOGGLE Off', '"" REAL 1 0 10'), DEFINITION.replace('Off;On', 'Off;Off')):
            (self.defs / "synthetic_selector").write_text(text, encoding="utf-8"); self.refresh()
            with self.assertRaises(ValueError): extension_trials.preview_selector_change(self.request)

    def test_unresolved_conditions_are_inconclusive_and_cannot_prepare(self):
        (self.defs / "synthetic_selector").write_text(DEFINITION.replace("#IF Mode=0", "#IF unknownFunction(Mode)"), encoding="utf-8")
        self.refresh()
        self.assertEqual(extension_trials.preview_selector_change(self.request)["status"], "inconclusive")
        with self.assertRaises(ValueError): extension_trials.prepare_extension_trial(self.request)
        self.assertFalse((self.data / "projects/.extension-trials").exists())

    def test_duplicate_component_identity_rejected(self):
        self.write_project(DFX.replace("SUBSYSTEM-END:", DFX.split("SUBSYSTEM-START:\n")[1]))
        self.refresh()
        with self.assertRaises(ValueError): extension_trials.preview_selector_change(self.request)

    def test_prepared_trial_preserves_all_originals_and_is_not_published_model(self):
        before, data = self.project.read_bytes(), self.companion.read_bytes()
        result = extension_trials.prepare_extension_trial(self.request)
        self.assertEqual(result["status"], "prepared_unexecuted")
        for key in ("source_snapshot", "working_project"):
            p = Path(result[key])
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual((p.parent / "samples.txt").read_bytes(), data)
        self.assertEqual(self.project.read_bytes(), before)
        self.assertFalse(Path(result["candidate_path_for_future_save_as"]).exists())
        self.assertEqual(project_tools.list_rscad_projects()["projects"], [])
        self.assertFalse(result["working_model_modified"])
        self.assertEqual(result["sdk_actions_executed"], [])
        self.assertEqual(sha256_file(Path(result["manifest_path"])), result["manifest_sha256"])

    def test_copy_failure_cleans_staging_without_publishing(self):
        original = extension_trials.shutil.copy2
        calls = []
        def fail(source, target):
            calls.append(target)
            if len(calls) == 2: raise OSError("authored copy failure")
            return original(source, target)
        with patch.object(extension_trials.shutil, "copy2", side_effect=fail):
            with self.assertRaises(OSError): extension_trials.prepare_extension_trial(self.request)
        self.assertEqual(list((self.data / ".extension-trial-staging").iterdir()), [])
        self.assertFalse(list(self.data.glob("projects/.extension-trials/*")))

    def test_missing_companion_prevents_trial(self):
        self.companion.unlink(); self.refresh()
        with self.assertRaises(RuntimeError): extension_trials.prepare_extension_trial(self.request)
        self.assertFalse((self.data / ".extension-trial-staging").exists())

    def test_companion_change_during_copy_prevents_publication(self):
        original = extension_trials.shutil.copy2
        def mutate(source, target):
            result = original(source, target)
            if Path(source) == self.companion: self.companion.write_text("changed", encoding="utf-8")
            return result
        with patch.object(extension_trials.shutil, "copy2", side_effect=mutate):
            with self.assertRaises(ValueError): extension_trials.prepare_extension_trial(self.request)
        self.assertFalse(list(self.data.glob("projects/.extension-trials/*")))

    def test_runtime_nested_headers_do_not_infer_units_values_or_gui(self):
        result = runtime_layout.inspect_runtime_layout(str(self.project))
        self.assertEqual(result["total_count"], 3)
        control = result["records"][1]
        self.assertEqual(control["parent_index"], 0)
        self.assertEqual(control["component_id"], 11)
        self.assertEqual(control["role"], "control")
        self.assertEqual(control["signal_references"][0]["stored_signal_path"], "Subsystem #1|CTLs|Inputs|SW1")
        self.assertIsNone(control["observed_units"]); self.assertIsNone(control["observed_value"])
        self.assertFalse(result["gui_observed"]); self.assertFalse(control["live_target_verified"])

    def test_runtime_pagination_requires_unchanged_snapshot(self):
        first = runtime_layout.inspect_runtime_layout(str(self.project), limit=1)
        second = runtime_layout.inspect_runtime_layout(str(self.project), first["snapshot_id"], offset=1, limit=1)
        self.assertEqual(second["records"][0]["component_id"], 11)
        with self.assertRaises(ValueError): runtime_layout.inspect_runtime_layout(str(self.project), offset=1)
        self.write_project(rtx=RTX.replace("SW1", "SW2"))
        with self.assertRaises(ValueError): runtime_layout.inspect_runtime_layout(str(self.project), first["snapshot_id"], offset=1)

    def test_runtime_duplicate_and_unknown_records_remain_partial(self):
        value = runtime_layout.parse_runtime_layout(RTX.replace("UUID: 12", "UUID: 11").replace("TAGGED_V2.2_FRAME", "UNSUPPORTED_FRAME"))
        self.assertEqual(value["status"], "partial")
        self.assertEqual(value["unsupported_count"], 1)
        self.assertEqual(value["records"][1]["identity_status"], "ambiguous")

    def test_plot_graph_uuid_is_not_component_uuid(self):
        text = RTX.replace('COMPONENT: TAGGED_V2.2_METER', 'COMPONENT: TAGGED_V2.2_PLOT').replace(' UUID: 12\nCOMPONENT-END:', ' UUID: 12\n PLOT-DATA-START\n UUID: 900\n NAME: graph\n PLOT-DATA-END\nCOMPONENT-END:')
        result = runtime_layout.parse_runtime_layout(text)
        self.assertEqual(result["records"][-1]["component_id"], 12)
        self.assertEqual(result["records"][-1]["name"], "output")

    def test_malformed_runtime_and_limits_rejected(self):
        for text in ("COMPONENT-END:", "COMPONENT: SWITCH", RTX.replace("COMPONENT-END:", "", 1), "x" * (16 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError): runtime_layout.parse_runtime_layout(text)

    def test_missing_rtx_explicitly_unsupported(self):
        self.write_project(rtx=None)
        self.assertEqual(runtime_layout.inspect_runtime_layout(str(self.project))["status"], "unsupported")

    def test_sdk_inspection_never_imports_or_connects_and_preserves_unknown_version(self):
        sdk = self.settings.sdk_root / "rtds"; sdk.mkdir(parents=True)
        (sdk / "__init__.py").write_text('__version__ = "1.1"\nraise RuntimeError("must not execute")', encoding="utf-8")
        (sdk / "component.py").write_text('class DraftComponent:\n @connected_method\n def set_parameter(self, param, val): raise RuntimeError("must not execute")\n', encoding="utf-8")
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "rtds" or name.startswith("rtds."): raise AssertionError("Vendor import")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded), patch("socket.socket", side_effect=AssertionError("Socket")), patch("subprocess.Popen", side_effect=AssertionError("Process")):
            result = extension_support.inspect_extension_support()
            extension_trials.preview_selector_change(self.request)
            runtime_layout.inspect_runtime_layout(str(self.project))
        self.assertEqual(result["evidence"]["sdk_version"], "1.1")
        self.assertEqual(result["features"]["selector_change"]["status"], "source_declared")
        self.assertEqual(result["features"]["create_wire"]["status"], "incomplete_source")
        self.assertFalse(result["integration_qualified"])
        self.assertEqual(result["rscad_running_version"], "unknown")
        self.assertEqual(result["draft_window_capture"]["status"], "unsupported")

    def test_sdk_missing_version_and_changed_source_identity(self):
        first = extension_support.inspect_extension_support()
        self.assertEqual(first["evidence"]["sdk_version"], "unknown")
        sdk = self.settings.sdk_root / "rtds"; sdk.mkdir(parents=True)
        (sdk / "__init__.py").write_text('__version__ = "2.0"', encoding="utf-8")
        second = extension_support.inspect_extension_support()
        self.assertNotEqual(first["evidence_id"], second["evidence_id"])
        self.assertFalse(second["features"]["selector_change"]["version_in_reviewed_scope"])

    def test_connected_port_change_is_flagged_for_connection_review(self):
        (self.defs / "synthetic_sink").write_text('PARAMETERS:\nNODES:\n IN 0 0 INPUT INTEGER\n',encoding="utf-8")
        second='COMPONENT_TYPE=synthetic_sink\n32 0 0 0 0\nPARAMETERS-START:\nPARAMETERS-END:\nUUID: 2\n'
        self.write_project(DFX.replace("SUBSYSTEM-END:",second+"SUBSYSTEM-END:"))
        self.refresh()
        value=extension_trials.preview_selector_change(self.request)
        self.assertTrue(any(n["connection_review_required"] for n in value["affected_existing_nets"]))
        self.assertFalse(value["automatic_application_supported"])

    def test_configuration_change_during_trial_rejects_publication(self):
        original=extension_trials.shutil.copy2
        def change(source,target):
            result=original(source,target)
            config=self.settings.as_dict()
            config["document_roots"].append(str(self.root / "new-docs"))
            self.config.write_text(json.dumps(config),encoding="utf-8")
            return result
        with patch.object(extension_trials.shutil,"copy2",side_effect=change):
            with self.assertRaises(ValueError):extension_trials.prepare_extension_trial(self.request)
        self.assertFalse(list(self.data.glob("projects/.extension-trials/*")))

    def test_definition_read_bytes_must_match_snapshot(self):
        original=Path.read_bytes
        definition=self.defs / "synthetic_selector"
        reads=[]
        def changed(path):
            raw=original(path)
            if path==definition:
                reads.append(path)
                return raw.replace(b"NEW 1",b"NEW 2")
            return raw
        with patch.object(Path,"read_bytes",changed):
            with self.assertRaisesRegex(ValueError,"definition bytes"):
                extension_trials.preview_selector_change(self.request)
        self.assertTrue(reads)

    def test_duplicate_header_uuid_is_ambiguous(self):
        value=runtime_layout.parse_runtime_layout(RTX.replace(" UUID: 11", " UUID: 11\n UUID: 77"))
        self.assertEqual(value["records"][1]["identity_status"],"ambiguous")
        self.assertEqual(value["records"][1]["field_ambiguities"],["UUID"])

    def test_runtime_read_has_no_filesystem_mutation(self):
        before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        runtime_layout.inspect_runtime_layout(str(self.project))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_new_schema_preserves_existing_workflow_registry(self):
        from rtds_agent.validation import validate_workflow
        workflow=fixture.PublicReleaseTests.prepare(self)
        validate_workflow(json.loads(Path(workflow).read_text(encoding="utf-8")))

    def test_unclosed_or_unknown_node_directives_remain_inconclusive(self):
        for text in (DEFINITION.replace(" #END\n", ""), DEFINITION.replace(" #IF Mode=0", " #UNSUPPORTED Mode\n #IF Mode=0")):
            (self.defs / "synthetic_selector").write_text(text,encoding="utf-8")
            self.refresh()
            value=extension_trials.preview_selector_change(self.request)
            self.assertEqual(value["status"],"inconclusive")
            with self.assertRaises(ValueError):extension_trials.prepare_extension_trial(self.request)

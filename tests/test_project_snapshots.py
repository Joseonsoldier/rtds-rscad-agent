"""Fresh static snapshots, identity, pagination and opt-in source discovery."""
import test_environment  # isolate config and credentials before application imports
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_public_release as fixtures
from rtds_agent.core.static_comparison import topology_signature


def component(uuid=1, value="1", kind="synthetic_gain", location="0 0"):
    return (f"COMPONENT_TYPE={kind}\n{location} 0 0 1\nPARAMETERS-START:\nGain: {value}\n"
            f"PARAMETERS-END:\nUUID: {uuid}\n")


class ProjectSnapshotTests(unittest.TestCase):
    setUp = fixtures.PublicReleaseTests.setUp

    def projects(self):
        from rtds_agent import project_tools
        return project_tools

    def write_model(self, body, path=None):
        path = path or self.project
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("synthetic.dfx", "DRAFT 1\n" + body)
        return path

    def model(self, *components):
        return self.write_model("SUBSYSTEM-START:\n" + "".join(components) + "SUBSYSTEM-END:\n")

    def test_queries_share_snapshot_component_identity_and_stored_origin(self):
        tools = self.projects()
        first = tools.inspect_rscad_project(str(self.project))
        snapshot = first["snapshot_id"]
        calls = [tools.get_project_hierarchy(str(self.project), snapshot_id=snapshot),
                 tools.list_components(str(self.project), snapshot_id=snapshot),
                 tools.get_component_parameters(str(self.project), 1, snapshot_id=snapshot),
                 tools.find_project_parameters(str(self.project), "Gain", snapshot_id=snapshot),
                 tools.get_component_graph(str(self.project), snapshot_id=snapshot),
                 tools.validate_project(str(self.project), snapshot_id=snapshot)]
        self.assertTrue(all(result["snapshot_id"] == snapshot for result in calls))
        listing = calls[1]["components"][0]
        parameters = calls[2]["component"]
        self.assertEqual(listing["component_key"], parameters["component_key"])
        self.assertEqual(parameters["parameter_origins"], {"Gain": "stored"})
        self.assertFalse(first["snapshot"]["runtime_observed"])
        self.assertEqual(first["snapshot"]["cache"], "disabled_fresh_hash_validation")

    def test_same_uuid_in_separate_contexts_is_ambiguous_without_context(self):
        tools = self.projects()
        self.write_model("SUBSYSTEM-START:\n" + component(1) + "SUBSYSTEM-END:\nSUBSYSTEM-START:\n" + component(1,"2") + "SUBSYSTEM-END:\n")
        result = tools.get_component_parameters(str(self.project),1)
        self.assertEqual(result["status"],"ambiguous")
        self.assertEqual(tools.compare_component_settings(str(self.project),str(self.project),1)["status"],"ambiguous")
        first = tools.get_component_parameters(str(self.project),1,"subsystem:0")
        second = tools.get_component_parameters(str(self.project),1,"subsystem:1")
        self.assertNotEqual(first["component"]["component_key"],second["component"]["component_key"])
        self.assertTrue(tools.compare_project_versions(str(self.project),str(self.project))["same_static_topology"])

    def test_duplicate_context_uuid_has_no_invented_comparison_identity(self):
        tools = self.projects()
        self.model(component(1),component(1,"2"))
        result=tools.compare_project_versions(str(self.project),str(self.project))
        self.assertEqual(result["status"],"ambiguous")
        self.assertIsNone(result["comparison"])

    def test_pagination_reads_remaining_components_with_same_snapshot(self):
        tools = self.projects()
        self.model(component(1),component(2),component(3))
        first=tools.list_components(str(self.project),limit=2)
        self.assertEqual([row["component_id"] for row in first["components"]],[1,2])
        self.assertEqual(first["next_offset"],2)
        second=tools.list_components(str(self.project),limit=2,offset=2,snapshot_id=first["snapshot_id"])
        self.assertEqual([row["component_id"] for row in second["components"]],[3])
        self.assertIsNone(second["next_offset"])
        with self.assertRaisesRegex(ValueError,"snapshot_id"):
            tools.list_components(str(self.project),limit=2,offset=2)
        for bad in (True,-1):
            with self.assertRaises(ValueError): tools.list_components(str(self.project),offset=bad,snapshot_id=first["snapshot_id"])

    def test_equal_size_mtime_project_change_invalidates_snapshot(self):
        tools=self.projects()
        first=tools.list_components(str(self.project))
        before=self.project.stat()
        self.model(component(1,"2"))
        self.assertEqual(self.project.stat().st_size,before.st_size)
        os.utime(self.project,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,"Snapshot changed"):
            tools.list_components(str(self.project),snapshot_id=first["snapshot_id"])

    def test_definition_only_change_invalidates_snapshot(self):
        tools=self.projects()
        first=tools.list_components(str(self.project))
        definition=self.defs/"synthetic_gain"
        before=definition.stat()
        definition.write_text(definition.read_text().replace('REAL 1 0 10','REAL 2 0 10'))
        os.utime(definition,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,"Snapshot changed"):
            tools.list_components(str(self.project),snapshot_id=first["snapshot_id"])
        second=tools.list_components(str(self.project))
        self.assertNotEqual(first["snapshot_id"],second["snapshot_id"])

    def test_companion_only_change_invalidates_snapshot(self):
        tools=self.projects()
        (self.defs/"synthetic_gain").write_text('PARAMETERS:\n Gain "Gain" "" REAL 1 0 10\n File "Input file" "" FILE input.txt\nNODES:\n')
        self.model(component(1).replace('Gain: 1\n','Gain: 1\nFile: input.txt\n'))
        companion=self.sources/"input.txt"
        companion.write_text("first")
        first=tools.list_components(str(self.project))
        companion.write_text("other")
        with self.assertRaisesRegex(ValueError,"Snapshot changed"):
            tools.list_components(str(self.project),snapshot_id=first["snapshot_id"])

    def test_dependency_change_during_parser_call_is_rejected(self):
        tools=self.projects()
        original=tools.parse_rtfx_topology
        def changing(*args,**kwargs):
            result=original(*args,**kwargs)
            definition=self.defs/"synthetic_gain"
            definition.write_text(definition.read_text()+"\n# changed during parse\n")
            return result
        with patch.object(tools,"parse_rtfx_topology",side_effect=changing):
            with self.assertRaisesRegex(ValueError,"changed during snapshot"):
                tools.list_components(str(self.project))

    def test_unresolved_definition_remains_explicit(self):
        tools=self.projects()
        self.model(component(1,kind="missing_definition"))
        result=tools.inspect_rscad_project(str(self.project))
        self.assertEqual(result["coverage"]["definition_coverage"],0)
        self.assertEqual(result["snapshot"]["evidence"]["definitions"]["missing_definition"]["status"],"unresolved")
        self.assertTrue(result["snapshot"]["warnings"])

    def test_source_listing_opt_in_and_unpublished_copy_excluded(self):
        tools=self.projects()
        partial=self.settings.projects_root/"partial"/"working"/"partial.rtfx"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(self.project.read_bytes())
        self.assertEqual(tools.list_rscad_projects()["count"],0)
        source=tools.list_rscad_projects(source_root=str(self.sources))
        self.assertEqual(source["projects"][0]["access_scope"],"source_read_only")
        (partial.parent.parent/"workflow.json").write_text('{}')
        self.assertEqual(tools.list_rscad_projects()["count"],0)
        fixtures.PublicReleaseTests.prepare(self)
        working=tools.list_rscad_projects()
        self.assertEqual(working["count"],1)
        self.assertEqual(working["projects"][0]["access_scope"],"agent_working_copy")
        with self.assertRaisesRegex(ValueError,"configured source"):
            tools.list_rscad_projects(source_root=str(self.root))

    def test_listing_pagination_rejects_changed_inventory(self):
        tools=self.projects()
        other=self.sources/"second.rtfx"
        other.write_bytes(self.project.read_bytes())
        first=tools.list_rscad_projects(limit=1,source_root=str(self.sources))
        self.assertEqual(first["next_offset"],1)
        second=tools.list_rscad_projects(limit=1,offset=1,source_root=str(self.sources),snapshot_id=first["snapshot_id"])
        self.assertEqual(second["count"],1)
        self.model(component(1,"2"))
        with self.assertRaisesRegex(ValueError,"snapshot changed"):
            tools.list_rscad_projects(limit=1,offset=1,source_root=str(self.sources),snapshot_id=first["snapshot_id"])

    def test_listing_skips_resolved_path_escape(self):
        tools=self.projects()
        original=Path.resolve
        outside=self.root/"outside.rtfx"
        outside.write_bytes(self.project.read_bytes())
        def resolve(path,*args,**kwargs):
            if path == self.project: return outside
            return original(path,*args,**kwargs)
        with patch.object(Path,"resolve",resolve):
            result=tools.list_rscad_projects(source_root=str(self.sources))
        self.assertEqual(result["count"],0)

    def test_topology_signature_ignores_net_ids_and_order_detects_endpoint_change(self):
        net={"net_id":"net-1","domain":"wire1","members":[{"atom":"port:a","context":"subsystem:0","component_id":1,"port":"out","domain":"wire1","phase":None},
                                                                 {"atom":"port:b","context":"subsystem:0","component_id":2,"port":"in","domain":"wire1","phase":None}]}
        first={"nets":[net]}
        second=copy.deepcopy(first)
        second["nets"][0]["net_id"]="different-number"
        second["nets"][0]["members"].reverse()
        self.assertEqual(topology_signature(first),topology_signature(second))
        second["nets"][0]["members"][0]["component_id"]=3
        self.assertNotEqual(topology_signature(first),topology_signature(second))

    def test_net_members_and_trace_endpoints_can_be_paged(self):
        tools=self.projects()
        (self.defs/"synthetic_gain").write_text('PARAMETERS:\n Gain "Gain" "" REAL 1 0 10\nNODES:\n Out 0 0 OUTPUT REAL\n')
        self.model(component(1),component(2),component(3))
        first=tools.get_component_graph(str(self.project),limit=1,member_limit=2)
        self.assertEqual(first["nets"][0]["member_pagination"]["next_offset"],2)
        second=tools.get_component_graph(str(self.project),limit=1,member_limit=2,member_offset=2,snapshot_id=first["snapshot_id"])
        self.assertEqual(len(second["nets"][0]["members"]),1)
        self.assertIn("component_key",second["nets"][0]["members"][0])
        trace=tools.trace_signal(str(self.project),1,"Out",limit=2)
        self.assertEqual(trace["next_offset"],2)
        tail=tools.trace_signal(str(self.project),1,"Out",limit=2,offset=2,snapshot_id=trace["snapshot_id"])
        self.assertEqual(tail["trace"]["returned_endpoint_count"],1)
        self.assertEqual(tail["direction_evidence"]["trace_scope"],"same_net_endpoints_only")

    def test_electrical_phase_ports_are_not_directed_control_sources(self):
        tools=self.projects()
        (self.defs/"synthetic_gain").write_text('PARAMETERS:\n Gain "Gain" "" REAL 1 0 10\nNODES:\n A 0 0 OUTPUT REAL PHASE=A_PHASE\n')
        result=tools.trace_signal(str(self.project),1,"A")
        self.assertEqual(result["trace"]["sources"],[])
        self.assertEqual(len(result["trace"]["undirected"]),1)
        self.assertFalse(result["direction_evidence"]["power_flow_inferred"])

    def test_detailed_comparison_reports_changed_connectivity(self):
        tools=self.projects()
        (self.defs/"synthetic_gain").write_text('PARAMETERS:\n Gain "Gain" "" REAL 1 0 10\nNODES:\n Out 0 0 OUTPUT REAL\n')
        self.model(component(1),component(2))
        second=self.sources/"different.rtfx"
        self.write_model("SUBSYSTEM-START:\n"+component(1)+component(2,location="32 0")+"SUBSYSTEM-END:\n",second)
        result=tools.compare_project_versions(str(self.project),str(second))
        self.assertFalse(result["same_static_topology"])
        self.assertGreater(result["topology_change_count"],0)
        self.assertEqual(result["component_changes"],[])

    def test_query_mutation_is_forbidden_with_snapshots_enabled(self):
        tools=self.projects()
        before={p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(Path,"write_text",side_effect=AssertionError("Unexpected mutation")), \
             patch.object(Path,"write_bytes",side_effect=AssertionError("Unexpected mutation")), \
             patch.object(Path,"mkdir",side_effect=AssertionError("Unexpected mutation")), \
             patch("socket.create_connection",side_effect=AssertionError("Unexpected connection")):
            result=tools.inspect_rscad_project(str(self.project))
            tools.list_components(str(self.project),snapshot_id=result["snapshot_id"])
            tools.list_rscad_projects(source_root=str(self.sources))
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_nested_completed_patch_is_listed_but_source_snapshot_is_not(self):
        from rtds_agent import editing, knowledge
        from rtds_agent.core.state_machine import sha256_file
        tools=self.projects()
        knowledge.index_parameters(str(self.project))
        result=editing.apply_parameter_patch(str(self.project),sha256_file(self.project),1,"subsystem:0","synthetic_gain","Gain","1","2")
        listed=tools.list_rscad_projects()
        self.assertEqual(listed["count"],1)
        self.assertEqual(listed["projects"][0]["path"],result["working_project"])
        self.assertEqual(listed["projects"][0]["publication"]["kind"],"parameter_patch")
        self.assertNotIn("source_snapshot",listed["projects"][0]["path"])
        marker=Path(result["manifest_path"])
        payload=json.loads(marker.read_text(encoding="utf-8"))
        payload["status"]="in_progress"
        marker.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(tools.list_rscad_projects()["count"],0)
        payload["status"]="completed"
        payload["working"]["sha256"]="0"*64
        marker.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(tools.list_rscad_projects()["count"],0)

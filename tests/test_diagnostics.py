"""Diagnostic readers use synthetic stored evidence; no simulator is involved."""
import test_environment  # Isolate user configuration and credentials before imports.
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_public_release as fixture
from rtds_agent.core.state_machine import sha256_file
from rtds_agent.diagnostics import get_execution_diagnostics


class DiagnosticTests(unittest.TestCase):
    setUp = fixture.PublicReleaseTests.setUp

    def prepare(self):
        return Path(fixture.PublicReleaseTests.prepare(self))

    def evidence(self, entries=None, *, complete=True, stage="compile", operational=False):
        workflow_path = self.prepare()
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        project = workflow["project"]
        inputs = {"source_sha256": project["source_sha256"], "working_sha256": project["working_sha256"]}
        action = "runtime_start_stop" if stage == "runtime" else stage
        result_path = workflow_path.parent / ("synthetic-" + stage + ".json")
        result = {"schema_version": "1.0", "backend": "ProductionRscadBackend", "action": action,
                  "evidence_kind": "synthetic_software_test", "created_at": "synthetic-time",
                  "workflow_id": workflow["workflow_id"], "attempt_id": "synthetic-attempt-1",
                  "hashes": {"source_before": inputs["source_sha256"], "working_before": inputs["working_sha256"],
                             "before": {"source": inputs["source_sha256"], "working": inputs["working_sha256"]}},
                  "hashes_before": {"source": inputs["source_sha256"], "working": inputs["working_sha256"]}}
        if operational:
            result["driver"] = {"errors": entries or [], "cleanup_errors": []}
        else:
            result["diagnostic_log"] = {"schema_version": "1.0", "complete": complete, "entries": entries or []}
        result_path.write_text(json.dumps(result), encoding="utf-8")
        ref = {"path": str(result_path), "sha256": sha256_file(result_path)}
        workflow[stage] = {"succeeded": True, "artifact_sha256": "a" * 64, "selected_rack": 2, "result_ref": ref}
        workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
        attempt = {"schema_version": 1, "workflow_id": workflow["workflow_id"], "attempt_id": "synthetic-attempt-1",
                   "action": action, "status": "finished", "execution": "succeeded", "phase": "persist",
                   "input_hashes": inputs, "result_ref": ref, "at": "synthetic-time"}
        marker = workflow_path.parent / (action + ".attempt.json")
        marker.write_text(json.dumps(attempt), encoding="utf-8")
        return workflow_path, result_path, marker

    def replace_result(self, workflow_path, result_path, marker, change):
        result = json.loads(result_path.read_text(encoding="utf-8"))
        change(result)
        result_path.write_text(json.dumps(result), encoding="utf-8")
        digest = sha256_file(result_path)
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
        stage = "runtime" if result["action"] == "runtime_start_stop" else result["action"]
        workflow[stage]["result_ref"]["sha256"] = digest
        workflow_path.write_text(json.dumps(workflow), encoding="utf-8")
        attempt = json.loads(marker.read_text(encoding="utf-8"))
        attempt["result_ref"]["sha256"] = digest
        marker.write_text(json.dumps(attempt), encoding="utf-8")

    def test_not_run_is_distinct_from_completed_empty_log(self):
        pending = get_execution_diagnostics(str(self.prepare()))
        self.assertEqual(pending["status"], "not_run")
        self.assertIsNone(pending["diagnostic_count"])
        self.assertFalse(pending["no_diagnostics_found"])
        workflow, _, _ = self.evidence()
        completed = get_execution_diagnostics(str(workflow))
        self.assertEqual(completed["status"], "available", completed)
        self.assertEqual(completed["diagnostic_count"], 0)
        self.assertTrue(completed["no_diagnostics_found"])
        self.assertEqual(completed["engineering_verdict"], "not_evaluated")
        self.assertEqual(completed["evidence_kind"], "synthetic_software_test")

    def test_empty_operational_errors_do_not_claim_complete_native_log(self):
        workflow, _, _ = self.evidence(operational=True)
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["diagnostic_count"], 0)
        self.assertEqual(result["log_completeness"], "partial")
        self.assertFalse(result["no_diagnostics_found"])

    def test_partial_log_and_in_progress_attempt_cannot_claim_no_diagnostics(self):
        workflow, _, marker = self.evidence(complete=False)
        result = get_execution_diagnostics(str(workflow))
        self.assertFalse(result["no_diagnostics_found"])
        attempt = json.loads(marker.read_text(encoding="utf-8"))
        attempt["status"] = "in_progress"
        marker.write_text(json.dumps(attempt), encoding="utf-8")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["log_completeness"], "partial")

    def test_old_attempt_log_is_stale_even_with_matching_hash_reference(self):
        workflow, artifact, marker = self.evidence([{"message": "old success"}])
        self.replace_result(workflow, artifact, marker, lambda result: result.update(attempt_id="earlier-attempt"))
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["diagnostics"], [])
        self.assertIn("earlier", result["reason"])

    def test_artifact_tamper_is_stale(self):
        workflow, artifact, _ = self.evidence([{"message": "failure"}])
        artifact.write_bytes(artifact.read_bytes() + b" ")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "stale")
        self.assertIn("hash mismatch", result["reason"])

    def test_changed_project_or_definition_is_stale(self):
        workflow, _, _ = self.evidence()
        definition = self.defs / "synthetic_gain"
        definition.write_text(definition.read_text(encoding="utf-8") + "\n// changed\n", encoding="utf-8")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["states"]["structure"], "stale")

    def test_unknown_severity_and_unproven_component_stay_unknown(self):
        workflow, _, _ = self.evidence([{"message": "synthetic warning", "severity": "unexpected-severity",
                                        "component_name": "looks_like_gain", "component_id": 1},
                                       {"message": "bad context", "context": "nonexistent", "component_id": 1}])
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["diagnostics"][0]["severity"], "unknown")
        self.assertTrue(all(row["component_key"] == "unknown" for row in result["diagnostics"]))

    def test_exact_context_uuid_maps_to_snapshot_key_with_location(self):
        workflow, _, _ = self.evidence([{"message": "synthetic warning", "severity": "warning", "context": "subsystem:0", "component_id": 1}])
        result = get_execution_diagnostics(str(workflow))
        row = result["diagnostics"][0]
        self.assertEqual(row["component_mapping"], "exact_context_uuid")
        self.assertNotEqual(row["component_key"], "unknown")
        self.assertEqual(row["mapping_snapshot_id"], result["current_snapshot_id"])
        self.assertEqual(result["input_snapshot_id"], "unknown")
        self.assertEqual(row["location"]["json_pointer"], "/diagnostic_log/entries/0")

    def test_snapshot_mismatch_is_stale(self):
        workflow, artifact, marker = self.evidence()
        self.replace_result(workflow, artifact, marker, lambda result: result.update(input_snapshot_id="old-snapshot"))
        self.assertEqual(get_execution_diagnostics(str(workflow))["status"], "stale")

    def test_legacy_unhashed_reference_is_unsupported(self):
        workflow, _, _ = self.evidence()
        manifest = json.loads(workflow.read_text(encoding="utf-8"))
        del manifest["compile"]["result_ref"]["sha256"]
        workflow.write_text(json.dumps(manifest), encoding="utf-8")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "unsupported")
        self.assertFalse(result["no_diagnostics_found"])

    def test_no_attempt_marker_is_not_repaired_from_legacy_success(self):
        workflow, _, marker = self.evidence()
        marker.unlink()
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "unsupported")
        self.assertIn("no attempt", result["reason"])

    def test_native_text_log_stays_unsupported_with_original_reference(self):
        workflow, artifact, marker = self.evidence()
        text = artifact.with_suffix(".log")
        text.write_text("Unknown vendor diagnostic format", encoding="utf-8")
        ref = {"path": str(text), "sha256": sha256_file(text)}
        manifest = json.loads(workflow.read_text(encoding="utf-8"))
        manifest["compile"]["result_ref"] = ref
        workflow.write_text(json.dumps(manifest), encoding="utf-8")
        attempt = json.loads(marker.read_text(encoding="utf-8"))
        attempt["result_ref"] = ref
        marker.write_text(json.dumps(attempt), encoding="utf-8")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(result["source_artifact"], str(text))
        self.assertEqual(result["source_hash"], ref["sha256"])

    def test_backend_initialization_failure_is_journal_diagnostic_not_run_success(self):
        workflow = self.prepare()
        manifest = json.loads(workflow.read_text(encoding="utf-8"))
        attempt = {"schema_version": 1, "attempt_id": "init-failure", "workflow_id": manifest["workflow_id"],
                   "action": "compile", "status": "failed", "execution": "not_started", "phase": "backend_init",
                   "error_type": "RuntimeError", "input_hashes": {"source_sha256": manifest["project"]["source_sha256"],
                                                                 "working_sha256": manifest["project"]["working_sha256"]}}
        (workflow.parent / "compile.attempt.json").write_text(json.dumps(attempt), encoding="utf-8")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "available", result)
        self.assertEqual(result["states"]["execution"], "not_started")
        self.assertIn("backend_init", result["diagnostics"][0]["message"])
        self.assertFalse(result["no_diagnostics_found"])

    def test_bounded_paging_keeps_deterministic_diagnostic_identity(self):
        workflow, _, _ = self.evidence([{"message": str(index)} for index in range(3)])
        first = get_execution_diagnostics(str(workflow), limit=1)
        second = get_execution_diagnostics(str(workflow), offset=first["next_offset"], limit=1)
        repeat = get_execution_diagnostics(str(workflow), offset=1, limit=1)
        self.assertEqual(first["diagnostic_count"], 3)
        self.assertEqual(second["diagnostics"][0]["message"], "1")
        self.assertEqual(second["diagnostics"], repeat["diagnostics"])
        self.assertNotEqual(first["diagnostics"][0]["diagnostic_id"], second["diagnostics"][0]["diagnostic_id"])

    def test_nested_artifact_tamper_invalidates_diagnostics(self):
        workflow, artifact, marker = self.evidence()
        log = workflow.parent / "stderr.txt"
        log.write_text("original", encoding="utf-8")
        self.replace_result(workflow, artifact, marker, lambda result: result.update(outputs={"stderr": {"path": str(log), "sha256": sha256_file(log)}}))
        log.write_text("changed", encoding="utf-8")
        self.assertEqual(get_execution_diagnostics(str(workflow))["status"], "stale")

    def test_read_only_states_do_not_run_or_assess_requirements(self):
        workflow, _, _ = self.evidence([{"message": "recorded error"}], operational=True)
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch("rtds_agent.execution._backend", side_effect=AssertionError("Backend")), \
             patch("socket.create_connection", side_effect=AssertionError("Network")):
            result = get_execution_diagnostics(str(workflow))
        after = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(result["states"]["grounding"], "hashes_verified")
        self.assertEqual(result["states"]["structure"], "static_hashes_verified")
        self.assertEqual(result["states"]["data_quality"], "not_evaluated")
        self.assertEqual(result["states"]["requirements"], "not_evaluated")
        self.assertFalse(result["rerun"])

    def test_runtime_and_offline_logs_bind_the_compile_artifact(self):
        for stage in ("runtime", "offline_test"):
            with self.subTest(stage=stage):
                workflow_path, artifact, marker = self.evidence(stage=stage)
                unsupported = get_execution_diagnostics(str(workflow_path), stage=stage)
                self.assertEqual(unsupported["status"], "unsupported")
                workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
                result = json.loads(artifact.read_text(encoding="utf-8"))
                compile_path = workflow_path.parent / "bound-compile.json"
                compile_result = {"schema_version": "1.0", "backend": "ProductionRscadBackend", "action": "compile",
                                  "hashes": {"source_before": workflow["project"]["source_sha256"], "working_before": workflow["project"]["working_sha256"]}}
                compile_path.write_text(json.dumps(compile_result), encoding="utf-8")
                workflow["compile"] = {"succeeded": True, "artifact_sha256": "a" * 64, "selected_rack": 2,
                                       "result_ref": {"path": str(compile_path), "sha256": sha256_file(compile_path)}}
                workflow_path.write_text(json.dumps(workflow), encoding="utf-8")

                def add_binary(value):
                    if stage == "runtime":
                        value["compiled_artifact"] = {"sha256": "a" * 64}
                    else:
                        value["hashes_before"]["rack_binary"] = "a" * 64

                self.replace_result(workflow_path, artifact, marker, add_binary)
                available = get_execution_diagnostics(str(workflow_path), stage=stage)
                self.assertEqual(available["status"], "available", available)
                self.assertEqual(available["compile_result_ref"]["path"], str(compile_path))
                compile_path.write_bytes(compile_path.read_bytes() + b" ")
                self.assertEqual(get_execution_diagnostics(str(workflow_path), stage=stage)["status"], "stale")

    def test_malformed_source_archive_is_stale(self):
        workflow, _, _ = self.evidence()
        self.project.write_bytes(b"changed invalid zip")
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result["status"], "stale")
        self.assertIsNone(result["diagnostic_count"])

    def test_invalid_stage_and_pagination_are_input_errors(self):
        workflow = self.prepare()
        for kwargs in ({"stage": "save"}, {"offset": True}, {"offset": -1}, {"limit": 0}, {"limit": 501}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                get_execution_diagnostics(str(workflow), **kwargs)

    def native_evidence(self, text=None, collection='partial', execution='failed'):
        from rtds_agent.core.compile_diagnostics import COMPILE_INCOMPLETE_MESSAGE, API_EXCEPTION_FORMAT_ID
        workflow, artifact, marker = self.evidence()
        log = workflow.parent/'saved-compile-exception.txt'
        log.write_bytes((COMPILE_INCOMPLETE_MESSAGE if text is None else text).encode())
        attempt = json.loads(marker.read_text(encoding='utf-8'))
        attempt['execution'] = execution
        marker.write_text(json.dumps(attempt), encoding='utf-8')
        envelope = {'schema_version':'1.0','workflow_id':attempt['workflow_id'], 'attempt_id':attempt['attempt_id'],
                    'action':'compile', **attempt['input_hashes'], 'logs':[{'path':str(log), 'sha256':sha256_file(log),
                    'bytes':log.stat().st_size, 'encoding':'utf-8', 'format_id':API_EXCEPTION_FORMAT_ID,
                    'collection_status':collection}]}
        self.replace_result(workflow, artifact, marker, lambda result: result.update(native_compile_logs=envelope))
        return workflow, artifact, marker, log

    def test_explicit_empty_log_never_hides_operational_or_cleanup_errors(self):
        workflow, artifact, marker = self.evidence()
        self.replace_result(workflow, artifact, marker, lambda result: result.update(driver={
            'errors':[{'type':'RSCADError','message':'Compile failure'}], 'cleanup_errors':[{'message':'Close failed'}]}))
        result = get_execution_diagnostics(str(workflow))
        self.assertEqual(result['diagnostic_count'],2)
        self.assertFalse(result['no_diagnostics_found'])
        self.assertEqual(result['log_completeness'],'partial')
        self.assertEqual(result['diagnostics'][0]['classification']['category'],'rscad_api')

    def test_failed_attempt_or_cleanup_with_empty_complete_log_stays_partial(self):
        for key in ('execution','cleanup'):
            workflow, _, marker = self.evidence()
            attempt=json.loads(marker.read_text(encoding='utf-8'));attempt[key]='failed'
            marker.write_text(json.dumps(attempt),encoding='utf-8')
            result=get_execution_diagnostics(str(workflow))
            self.assertFalse(result['no_diagnostics_found'])
            self.assertEqual(result['log_completeness'],'partial')

    def test_attempt_bound_native_exception_is_read_only_category_only(self):
        workflow, _, _, _ = self.native_evidence()
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('socket.create_connection',side_effect=AssertionError('network')), patch('subprocess.Popen',side_effect=AssertionError('native')):
            result=get_execution_diagnostics(str(workflow))
        self.assertEqual(result['status'],'available',result)
        native=result['native_compile_analysis'];row=native['diagnostics'][0]
        self.assertEqual(row['category'],'rscad_api')
        self.assertEqual(row['component_mapping'],'unknown')
        self.assertFalse(native['integration_qualified'])
        self.assertFalse(native['automatic_retry'])
        self.assertEqual(native['native_outcome'],'not_evaluated')
        self.assertFalse(result['no_diagnostics_found'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_native_empty_or_unknown_log_never_establishes_success(self):
        for text in ('','Unknown failure UUID 1; error parameter'):
            workflow, _, _, _=self.native_evidence(text,collection='complete',execution='succeeded')
            result=get_execution_diagnostics(str(workflow))
            self.assertFalse(result['no_diagnostics_found'])
            self.assertFalse(result['native_compile_analysis']['empty_log_proves_success'])
            if text:self.assertEqual(result['native_compile_analysis']['diagnostics'][0]['category'],'unknown')

    def test_native_receipt_requires_explicit_attempt_action_and_input_identity(self):
        for field in ('workflow_id','attempt_id','action','source_sha256','working_sha256'):
            workflow,artifact,marker,_=self.native_evidence()
            def change(result):result['native_compile_logs'][field]='0'*64
            self.replace_result(workflow,artifact,marker,change)
            result=get_execution_diagnostics(str(workflow))
            self.assertEqual(result['status'],'stale',field)
            self.assertNotIn('native_compile_analysis',result)

    def test_native_log_changed_during_grounding_invalidates_all_native_analysis(self):
        workflow,artifact,marker,log=self.native_evidence()
        self.replace_result(workflow,artifact,marker,lambda result:result['diagnostic_log'].update(entries=[{'message':'operational'}]))
        def change(*args):log.write_text('changed during grounding',encoding='utf-8');return {}
        with patch('rtds_agent.core.diagnostic_grounding.ground_diagnostic',side_effect=change):
            result=get_execution_diagnostics(str(workflow),include_grounding=True)
        self.assertEqual(result['status'],'stale')
        self.assertNotIn('native_compile_analysis',result)

    def test_native_receipt_bounds_links_duplicates_and_tamper(self):
        for mode in ('size','duplicate','bad-hash','unknown-field'):
            workflow,artifact,marker,log=self.native_evidence()
            def change(result):
                env=result['native_compile_logs'];ref=env['logs'][0]
                if mode=='size':ref['bytes']=1048577
                elif mode=='duplicate':env['logs'].append(dict(ref))
                elif mode=='bad-hash':ref['sha256']='0'*64
                else:env['execute']=True
            self.replace_result(workflow,artifact,marker,change)
            self.assertEqual(get_execution_diagnostics(str(workflow))['status'],'stale',mode)
        workflow, _, _, _=self.native_evidence()
        with patch.object(Path,'is_junction',return_value=True):
            self.assertEqual(get_execution_diagnostics(str(workflow))['status'],'stale')

    def test_native_pagination_retains_stable_record_identity(self):
        workflow, _, _, _=self.native_evidence('Unknown first\nUnknown second\n')
        first=get_execution_diagnostics(str(workflow),limit=1)['native_compile_analysis']
        second=get_execution_diagnostics(str(workflow),offset=first['next_offset'],limit=1)['native_compile_analysis']
        again=get_execution_diagnostics(str(workflow),offset=1,limit=1)['native_compile_analysis']
        self.assertEqual(first['diagnostic_count'],2)
        self.assertNotEqual(first['diagnostics'][0]['record_id'],second['diagnostics'][0]['record_id'])
        self.assertEqual(second,again)


if __name__ == "__main__":
    unittest.main()

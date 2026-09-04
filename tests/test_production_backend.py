from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from rtds_agent.core.companion_dependencies import discover_companion_dependencies
from rtds_agent.core.orchestrator import ApprovalGatedOrchestrator
from rtds_agent.core.production_backend import BackendSafetyViolation, ProductionBackendConfig, ProductionRscadBackend, resolve_bus_nodes, validate_existing_run
from rtds_agent.core.state_machine import ApprovalAction, Workflow, WorkflowState, sha256_file, sha256_json
import rtds_agent
_TEST_TEMP = tempfile.TemporaryDirectory(prefix='rtds-core-tests-')
ROOT = Path(_TEST_TEMP.name)
AGENT = ROOT / 'agent-data'
AGENT_ROOT = AGENT
(AGENT / 'projects').mkdir(parents=True)
HERE = Path(rtds_agent.__file__).parent / 'schemas'

class FakeCompileDriver:

    def __init__(self) -> None:
        self.query_calls = 0
        self.compile_calls = 0
        self.compile_succeeds = True
        self.cleanup_succeeds = True

    def query_racks(self) -> dict[str, Any]:
        self.query_calls += 1
        return {'source': 'live_query_immediately_before_action', 'refreshed_at': f'fake-{self.query_calls}', 'rscad_fx_version': '2.7.3', 'status': 'selected', 'selected_rack': 1, 'available_racks': [1], 'configured_racks': [1], 'reason': 'fake available rack'}

    def compile_case(self, *, working_copy: str, rack: int) -> dict[str, Any]:
        self.compile_calls += 1
        working = Path(working_copy)
        build = working.parent / f'build_{working.stem}'
        build.mkdir(parents=True, exist_ok=True)
        dtp = build / f'{working.stem}.dtp'
        rack_binary = build / f'{working.stem}_r{rack}'
        dtp.write_text('NODE= 1 DATA NODENAME= "N1"\nNODE= 2 DATA NODENAME= "N2"\nNODE= 3 DATA NODENAME= "N3"\n', encoding='utf-8')
        rack_binary.write_bytes(b'fake-rack-binary')
        return {'succeeded': self.compile_succeeds and self.cleanup_succeeds, 'connected': True, 'version': '2.7.3', 'available_racks': [1], 'opened_file': str(working), 'starting_rack_before': 1, 'starting_rack_for_compile': rack, 'starting_rack_changed_in_memory': False, 'case_save_called': False, 'compile_called': True, 'compile_return_value': repr(self.compile_succeeds), 'case_closed': self.cleanup_succeeds, 'disconnected': self.cleanup_succeeds, 'artifacts': {'dtp': str(dtp), 'rack_binary': str(rack_binary)}, 'errors': [], 'cleanup_errors': [] if self.cleanup_succeeds else [{'operation': 'synthetic cleanup', 'message': 'injected failure'}]}

class FakeFsatRunner:

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mode = 'success'

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({'command': list(command), **kwargs})
        if self.mode == 'timeout':
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        output_base = (Path(kwargs['cwd']) / command[3]).resolve()
        output = Path(str(output_base) + '.fscn')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text('Frequency(Hz) Zqq_mag Zqq_phase\n0.000001 1.0 90.0\n1.0 1.1 89.0\n', encoding='utf-8')
        if self.mode == 'error_stdout':
            return subprocess.CompletedProcess(command, 0, stdout='Error: injected FSAT failure\n', stderr='')
        return subprocess.CompletedProcess(command, 0, stdout='Frequency Scan completed successfully!\n', stderr='')

class ProductionBackendTests(unittest.TestCase):

    def test_generated_bus_node_templates_resolve_by_bus_number(self) -> None:
        result = resolve_bus_nodes({'NA': 'N#A', 'NB': 'N#B', 'NC': 'N#C', 'Num': '1'}, {'N1A': 1, 'N1B': 2, 'N1C': 3})
        self.assertEqual(result['resolved_node_names'], ['N1A', 'N1B', 'N1C'])
        self.assertEqual(result['selected_node_numbers'], [1, 2, 3])
        self.assertEqual(result['strategy'], 'buslabel_num_substitution')

    def setUp(self) -> None:
        projects = AGENT_ROOT / 'projects'
        self.temporary = tempfile.TemporaryDirectory(prefix='production_backend_test_', dir=projects)
        self.addCleanup(self.temporary.cleanup)
        self.run_dir = Path(self.temporary.name) / 'run'
        self.working_dir = self.run_dir / 'working'
        self.working_dir.mkdir(parents=True)
        self.working = self.working_dir / 'case.rtfx'
        with zipfile.ZipFile(self.working, 'w') as archive:
            archive.writestr('case.dfx', 'DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=file_component\n0 0 0 0 1\nPARAMETERS-START:\nData: line.tli\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n')
        self.companion = self.working_dir / 'line.tli'
        self.companion.write_text('immutable line model\n', encoding='utf-8')
        self.topology = {'components': [{'uuid': 6, 'component_type': 'rtds_sharc_sld_BUSLABEL', 'parameters': {'BName': 'BUS1#', 'NA': 'N1', 'NB': 'N2', 'NC': 'N3'}}]}
        (self.run_dir / 'topology.json').write_text(json.dumps(self.topology), encoding='utf-8')
        self.fake_rscad_root = self.run_dir / 'fake_rscad'
        (self.fake_rscad_root / 'Examples').mkdir(parents=True)
        self.source = self.fake_rscad_root / 'Examples' / 'source.rtfx'
        self.source.write_text('immutable source case\n', encoding='utf-8')
        definitions = self.fake_rscad_root / 'MLIB' / 'COMPONENTS'
        definitions.mkdir(parents=True)
        (definitions / 'file_component').write_text('Component Builder 0.1.0\nPARAMETERS:\n  SECTION: "CONFIGURATION"\n    Data "Input file" "*.tli" 0 FILE line.tli\nNODES:\n', encoding='utf-8')
        (self.fake_rscad_root / 'BIN' / 'GCC' / 'bin').mkdir(parents=True)
        (self.fake_rscad_root / 'BIN' / 'fs.exe').write_bytes(b'fake-fs')
        self.driver = FakeCompileDriver()
        self.fsat = FakeFsatRunner()
        self.config = ProductionBackendConfig(rscad_root=self.fake_rscad_root, agent_root=AGENT_ROOT)
        self.backend = ProductionRscadBackend(self.config, compile_driver=self.driver, process_runner=self.fsat)
        self.workflow = self._new_workflow()

    def _new_workflow(self) -> Workflow:
        input_files = [{'path': str(self.companion), 'sha256': sha256_file(self.companion)}]
        discovery = discover_companion_dependencies(self.working, self.config.component_definitions_root)
        self.assertTrue(discovery['passed'])
        workflow = Workflow.create(workflow_id='production-backend-test', project={'source_path': str(self.source), 'source_sha256': sha256_file(self.source), 'working_copy': str(self.working), 'working_sha256': sha256_file(self.working), 'working_root': str(AGENT_ROOT / 'projects'), 'vendor_source_root': str(self.fake_rscad_root / 'Examples'), 'input_files': input_files, 'input_bundle_sha256': sha256_json(input_files), 'companion_discovery_sha256': discovery['discovery_sha256']}, test_spec={'test_id': 'fake-offline-fsat', 'execution_mode': 'offline_analytical_frequency_scan', 'runtime_required': False, 'execution_notes': {'case_run_forbidden': True}, 'scan': {'system_frequency_hz': 60.0, 'start_frequency_hz': 0.0, 'end_frequency_hz': 1.0, 'frequency_increment_hz': 1.0, 'domain': 'DQ0', 'selected_bus': 'BUS1', 'output_basename': 'fake_scan', 'expected_extension': '.fscn'}})
        workflow.record_stage('inspection', passed=True, evidence=[])
        workflow.record_stage('grounding', passed=True, evidence=[])
        workflow.record_stage('static_validation', passed=True, evidence=[])
        workflow.add_standing_authorization([ApprovalAction.COMPILE, ApprovalAction.OFFLINE_TEST], actor='user', source='recommended limited scope')
        return workflow

    def _compile(self) -> ApprovalGatedOrchestrator:
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='production adapter test')
        orchestrator = ApprovalGatedOrchestrator(self.workflow, self.backend)
        result = orchestrator.execute_compile()
        self.assertTrue(result['succeeded'])
        self.assertIs(self.workflow.state, WorkflowState.COMPILED)
        return orchestrator

    def test_compile_and_offline_path_is_hash_bound_and_rackless_offline(self) -> None:
        orchestrator = self._compile()
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='offline adapter test')
        result = orchestrator.execute_offline_test()
        self.assertTrue(result['succeeded'])
        self.assertTrue(result['raw_data_collected'])
        self.assertIs(self.workflow.state, WorkflowState.OFFLINE_TEST_COMPLETED)
        self.assertEqual(self.driver.query_calls, 1)
        self.assertEqual(self.driver.compile_calls, 1)
        self.assertEqual(len(self.fsat.calls), 1)
        self.assertFalse(self.fsat.calls[0]['shell'])
        self.assertEqual([item['call'] for item in self.backend.call_log], ['refresh_racks', 'compile', 'run_offline_test'])
        compile_manifest = json.loads((self.run_dir / 'production_compile_execution.json').read_text(encoding='utf-8'))
        offline_manifest = json.loads((self.run_dir / 'production_offline_execution.json').read_text(encoding='utf-8'))
        expected_discovery = self.workflow.manifest['project']['companion_discovery_sha256']
        self.assertEqual(compile_manifest['companion_discovery']['sha256'], expected_discovery)
        self.assertTrue(compile_manifest['companion_discovery']['required'])
        self.assertEqual(offline_manifest['companion_discovery']['sha256'], expected_discovery)
        result_ref = result['result_ref']
        self.assertEqual(sha256_file(result_ref['path']), result_ref['sha256'])
        self.assertEqual(Path(result_ref['command_manifest']).resolve(), Path(result_ref['command_manifest_ref']['path']).resolve())
        self.assertEqual(sha256_file(result_ref['command_manifest']), result_ref['command_manifest_ref']['sha256'])

    def test_fault_working_copy_tamper_is_blocked(self) -> None:
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='stale hash test')
        self.working.write_text('tampered\n', encoding='utf-8')
        with self.assertRaises(BackendSafetyViolation):
            ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.driver.compile_calls, 0)
        self.assertEqual(self.workflow.manifest['compile']['result_ref']['backend_operation'], 'compile')

    def test_fault_companion_input_tamper_before_compile_is_blocked(self) -> None:
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='companion input tamper')
        self.companion.write_text('tampered line model\n', encoding='utf-8')
        with self.assertRaises(BackendSafetyViolation):
            ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.driver.compile_calls, 0)

    def test_fault_companion_input_tamper_before_fsat_is_blocked(self) -> None:
        orchestrator = self._compile()
        self.companion.write_text('tampered after compile\n', encoding='utf-8')
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='companion input tamper')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_offline_test()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.fsat.calls, [])

    def test_fault_existing_compile_artifact_is_never_overwritten(self) -> None:
        build = self.working_dir / f'build_{self.working.stem}'
        build.mkdir()
        dtp = build / f'{self.working.stem}.dtp'
        dtp.write_bytes(b'preserve compile evidence')
        before = dtp.read_bytes()
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='compile overwrite refusal')
        with self.assertRaises(BackendSafetyViolation):
            ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(dtp.read_bytes(), before)
        self.assertEqual(self.driver.compile_calls, 0)

    def test_fault_existing_offline_output_is_never_overwritten(self) -> None:
        orchestrator = self._compile()
        output = self.run_dir / 'outputs' / 'fake_scan.fscn'
        output.parent.mkdir(parents=True)
        output.write_text('preserve me\n', encoding='utf-8')
        before = output.read_bytes()
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='overwrite refusal')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_offline_test()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(self.fsat.calls, [])
        self.assertEqual(self.driver.query_calls, 1)

    def test_fault_source_tamper_is_blocked(self) -> None:
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='source tamper')
        self.source.write_text('tampered source\n', encoding='utf-8')
        with self.assertRaises(BackendSafetyViolation):
            ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.driver.compile_calls, 0)

    def test_fault_compile_false_result_records_failed_workflow(self) -> None:
        self.driver.compile_succeeds = False
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='compile false result')
        result = ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertFalse(result['succeeded'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.driver.compile_calls, 1)

    def test_fault_compile_cleanup_failure_records_failed_workflow(self) -> None:
        self.driver.cleanup_succeeds = False
        self.workflow.request_approval(ApprovalAction.COMPILE, reason='cleanup failure')
        result = ApprovalGatedOrchestrator(self.workflow, self.backend).execute_compile()
        self.assertFalse(result['succeeded'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        manifest = json.loads((self.run_dir / 'production_compile_execution.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['driver']['cleanup_errors'])

    def test_fault_corrupted_dtp_is_blocked_before_fsat(self) -> None:
        orchestrator = self._compile()
        manifest = json.loads((self.run_dir / 'production_compile_execution.json').read_text(encoding='utf-8'))
        dtp = Path(manifest['artifacts']['dtp']['path'])
        dtp.write_bytes(dtp.read_bytes() + b'injected corruption')
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='corrupted DTP')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_offline_test()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.fsat.calls, [])

    def test_fault_corrupted_rack_binary_is_blocked_before_fsat(self) -> None:
        orchestrator = self._compile()
        manifest = json.loads((self.run_dir / 'production_compile_execution.json').read_text(encoding='utf-8'))
        binary = Path(manifest['artifacts']['rack_binary']['path'])
        binary.write_bytes(binary.read_bytes() + b'injected corruption')
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='corrupted rack binary')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_offline_test()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.fsat.calls, [])

    def test_fault_fsat_timeout_records_failed_workflow(self) -> None:
        orchestrator = self._compile()
        self.fsat.mode = 'timeout'
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='FSAT timeout')
        result = orchestrator.execute_offline_test()
        self.assertFalse(result['succeeded'])
        self.assertFalse(result['raw_data_collected'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        manifest = json.loads((self.run_dir / 'production_offline_execution.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['execution']['timed_out'])

    def test_fault_fsat_error_stdout_records_failed_workflow(self) -> None:
        orchestrator = self._compile()
        self.fsat.mode = 'error_stdout'
        self.workflow.request_approval(ApprovalAction.OFFLINE_TEST, reason='FSAT error stdout')
        result = orchestrator.execute_offline_test()
        self.assertFalse(result['succeeded'])
        self.assertTrue(result['raw_data_collected'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        manifest = json.loads((self.run_dir / 'production_offline_execution.json').read_text(encoding='utf-8'))
        self.assertFalse(manifest['execution']['error_text_absent'])

    def test_runtime_backend_is_fail_closed(self) -> None:
        orchestrator = self._compile()
        self.workflow.request_approval(ApprovalAction.RUNTIME, reason='explicit test approval')
        self.workflow.grant_approval(ApprovalAction.RUNTIME, actor='tester', source='unit test only')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_runtime()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self.fsat.calls, [])
        self.assertEqual(self.driver.compile_calls, 1)
if __name__ == '__main__':
    unittest.main(verbosity=2)

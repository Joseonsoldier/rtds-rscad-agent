from __future__ import annotations
import test_environment  # isolate config and credentials before application imports
import copy
import json
import math
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from rtds_agent.core.orchestrator import ApprovalGatedOrchestrator
from rtds_agent.core.production_backend import BackendSafetyViolation, ProductionBackendConfig, ProductionRscadBackend
from rtds_agent.core.runtime_backend import _latest_numeric, _read_single_curve_plot_csv, RscadFxRuntimeDriver, RuntimeContractError, runtime_input_objects, runtime_meter_ids, runtime_single_curve_plot_ids, validate_runtime_test_spec
from rtds_agent.core.state_machine import ApprovalAction, ApprovalScopeMismatch, SafetyViolation, Workflow, WorkflowState, sha256_file
import rtds_agent
_TEST_TEMP = tempfile.TemporaryDirectory(prefix='rtds-core-tests-')
ROOT = Path(_TEST_TEMP.name).resolve()
AGENT = ROOT / 'agent-data'
AGENT_ROOT = AGENT
(AGENT / 'projects').mkdir(parents=True)
HERE = Path(rtds_agent.__file__).parent / 'schemas'

def runtime_spec() -> dict[str, Any]:
    return {'test_id': 'fake_runtime_read_only_capture', 'execution_mode': 'runtime_read_only_signal_capture', 'runtime_required': True, 'event': {'type': 'none', 'description': 'steady-state capture'}, 'runtime_controls': {'read_only_signal_capture': True, 'runtime_parameter_writes': [], 'hardware_io_changes': [], 'rack_configuration_changes': [], 'deployment_actions': []}, 'runtime_capture': {'warmup_seconds': 0.0, 'minimum_samples_per_channel': 3}, 'measurement_channels': [{'channel_id': 'VA', 'signal_path': 'Subsystem #1|Node Voltages|S1) VA', 'units': 'kV'}, {'channel_id': 'VB', 'signal_path': 'Subsystem #1|Node Voltages|S1) VB', 'units': 'kV'}], 'output_requirements': {'raw_numeric_data_required': True, 'screenshot_only_pass_fail_forbidden': True}}

def runtime_control_spec() -> dict[str, Any]:
    spec = runtime_spec()
    spec['execution_mode'] = 'runtime_control_and_signal_capture'
    spec['runtime_controls']['runtime_parameter_writes'] = [{'action_id': 'lockfree_bus39', 'purpose': 'lockfree_change', 'object_uuid': 603, 'object_type': 'switch', 'object_name': 'LockFree', 'object_group': 'Subsystem #1|Machines|BUS39x1', 'object_desc': 'LockFree', 'attribute': 'position', 'expected_initial_value': 1, 'value': 0, 'apply_after_seconds': 0.0, 'restore_after_capture': True}]
    spec['runtime_controls']['runtime_parameter_writes'][0]['object_subpage'] = 'Controls'
    return spec

def runtime_lock_release_spec() -> dict[str, Any]:
    spec = runtime_control_spec()
    lock = spec['runtime_controls']['runtime_parameter_writes'][0]
    lock['action_id'] = 'lock_bus39_before_run'
    lock['phase'] = 'before_run'
    release = copy.deepcopy(lock)
    release.update({'action_id': 'release_bus39_after_settle', 'phase': 'after_run', 'expected_initial_value': 0, 'value': 1, 'apply_after_seconds': 0.5})
    spec['runtime_controls']['runtime_parameter_writes'] = [lock, release]
    spec['runtime_capture']['warmup_seconds'] = 1.0
    return spec

class FakeRackDriver:

    def __init__(self, selected_rack: int=1) -> None:
        self.selected_rack = selected_rack
        self.query_calls = 0

    def query_racks(self) -> dict[str, Any]:
        self.query_calls += 1
        return {'source': 'live_query_immediately_before_action', 'refreshed_at': f'fake-live-{self.query_calls}', 'rscad_fx_version': '2.7.3', 'status': 'selected', 'selected_rack': self.selected_rack, 'available_racks': [self.selected_rack], 'configured_racks': [1, 2], 'reason': 'fake available rack'}

class FakeRuntimeDriver:

    def __init__(self) -> None:
        self.calls = 0
        self.mode = 'success'
        self.mutate_path: Path | None = None

    def capture_case(self, *, working_copy: str, rack: int, channels: list[dict[str, str]], warmup_seconds: float, loadflow_initialization: dict[str, Any] | None=None, runtime_parameter_writes: list[dict[str, Any]] | None=None, capture_directory: str | None=None) -> dict[str, Any]:
        self.calls += 1
        if self.mode == 'raise':
            raise RuntimeError('injected driver exception before live start')
        if self.mutate_path is not None:
            self.mutate_path.write_bytes(self.mutate_path.read_bytes() + b'injected mutation')
        samples = {item['channel_id']: {'times': [0.0, 0.1, 0.2], 'values': [1.0, 2.0, 3.0]} for item in channels}
        loadflow_enabled = bool((loadflow_initialization or {}).get('enabled', False))
        writes = list(runtime_parameter_writes or [])
        restore_targets = len({(int(item['object_uuid']), str(item['attribute'])) for item in writes})
        safety = {'compile_called': False, 'load_flow_called': loadflow_enabled, 'runtime_parameter_write_called': bool(writes), 'case_settings_write_called': False, 'rack_power_change_called': False, 'rack_security_change_called': False, 'rack_configuration_changed': False, 'deployment_called': False, 'hardware_io_called': False, 'case_save_called': False, 'source_write_called': False}
        execution = {'loadflow_call_attempted': loadflow_enabled, 'loadflow_succeeded': loadflow_enabled, 'loadflow_return_value': 'True' if loadflow_enabled else None, 'run_call_attempted': True, 'run_started': True, 'run_return_value': 'True', 'run_state_after_start': 'running', 'warmup_seconds': warmup_seconds, 'update_plots_called': True, 'raw_data_collected': True, 'stop_call_attempted': True, 'stop_succeeded': True, 'run_state_after_stop': 'stopped'}
        cleanup = {'case_close_attempted': True, 'case_closed': True, 'disconnect_terminate': False, 'disconnected': True}
        errors: list[dict[str, str]] = []
        cleanup_errors: list[dict[str, str]] = []
        opened_file = working_copy
        run_state_before = 'stopped'
        if self.mode == 'stop_failure':
            execution['stop_succeeded'] = False
            execution['run_state_after_stop'] = 'running'
            cleanup_errors.append({'operation': 'case.stop()', 'message': 'injected stop failure'})
        elif self.mode == 'disconnect_failure':
            cleanup['disconnected'] = False
            cleanup_errors.append({'operation': 'disconnect', 'message': 'injected disconnect failure'})
        elif self.mode == 'runtime_write':
            safety['runtime_parameter_write_called'] = True
        elif self.mode == 'hardware_io':
            safety['hardware_io_called'] = True
        elif self.mode == 'nan':
            samples[channels[0]['channel_id']]['values'][1] = math.nan
        elif self.mode == 'too_few_samples':
            samples[channels[0]['channel_id']] = {'times': [0.0], 'values': [1.0]}
        elif self.mode == 'wrong_file':
            opened_file = str(Path(working_copy).with_name('other.rtfx'))
        elif self.mode == 'already_running':
            run_state_before = 'running'
        elif self.mode == 'run_failure':
            execution['run_started'] = False
            execution['run_state_after_start'] = 'stopped'
            errors.append({'type': 'RuntimeError', 'message': 'run rejected'})
        elif self.mode == 'loadflow_failure':
            execution['loadflow_succeeded'] = False
            execution['run_call_attempted'] = False
            execution['run_started'] = False
            execution['run_state_after_start'] = 'stopped'
            errors.append({'type': 'RuntimeError', 'message': 'loadflow rejected'})
        return {'connected': True, 'version': '2.7.3', 'available_racks': [rack], 'opened_file': opened_file, 'starting_rack': rack, 'run_state_before': run_state_before, 'execution': execution, 'cleanup': cleanup, 'safety': safety, 'runtime_controls': {'planned': len(writes), 'restore_targets_planned': restore_targets, 'applied': len(writes), 'restored': restore_targets, 'all_readbacks_verified': True, 'all_restored': True, 'actions': [{**item, 'applied': True, 'restored': True} for item in writes]}, 'signals': {item['channel_id']: {'signal_path': item['signal_path'], 'units': item['units'], 'lookup_succeeded': True} for item in channels}, 'samples': samples, 'errors': errors, 'cleanup_errors': cleanup_errors}

class FakeSignal:

    def __init__(self, fail: bool=False) -> None:
        self.fail = fail

    def get_time_data(self) -> list[float]:
        return [0.0, 0.1, 0.2]

    def get_data(self) -> list[float]:
        if self.fail:
            raise RuntimeError('injected signal read failure')
        return [1.0, 2.0, 3.0]

class FakeRuntimeInput:

    def __init__(self, *, position: int=0, value: float=0.0) -> None:
        self.position = position
        self.value = value
        self.unique_id=603;self.subpage='Controls';self.subtab='Runtime'

class FakeLiveRuntime:

    def __init__(self, objects: dict[int, FakeRuntimeInput] | None=None) -> None:
        self.objects = dict(objects or {})

    def get_object(self, object_uuid: int) -> FakeRuntimeInput | None:
        return self.objects.get(object_uuid)

    def get_objects(self, object_type: str, name: str):
        return list(self.objects.values()) if object_type=='switch' and name=='LockFree' else []

class FakeLiveCase:

    def __init__(self, file: str, *, initial_state: str='stopped', stop_fails: bool=False, signal_fails: bool=False, loadflow_fails: bool=False, runtime_objects: dict[int, FakeRuntimeInput] | None=None) -> None:
        self.file = file
        self.settings = type('Settings', (), {'starting_rack': 1})()
        self.state = type('State', (), {'run_state': initial_state})()
        self.stop_fails = stop_fails
        self.signal_fails = signal_fails
        self.loadflow_fails = loadflow_fails
        self.runtime = FakeLiveRuntime(runtime_objects)
        self.events: list[str] = []
        self.loadflow_calls: list[tuple[int, float, bool, str]] = []
        self.run_calls = 0
        self.stop_calls = 0
        self.close_calls = 0
        self.update_calls = 0

    def get_signal(self, path: str) -> FakeSignal:
        return FakeSignal(self.signal_fails)

    def run(self) -> None:
        self.events.append('run')
        self.run_calls += 1
        self.state.run_state = 'running'
        return None

    def run_loadflow(self, timeout_seconds: int, zero_impedance_threshold_pu: float, flat_start: bool, method: str) -> bool:
        self.events.append('loadflow')
        self.loadflow_calls.append((timeout_seconds, zero_impedance_threshold_pu, flat_start, method))
        if self.loadflow_fails:
            raise RuntimeError('injected loadflow failure')
        return True

    def update_plots(self) -> None:
        self.update_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1
        if self.stop_fails:
            raise RuntimeError('injected stop exception')
        self.state.run_state = 'stopped'
        return None

    def close(self, *, force: bool) -> None:
        self.close_calls += 1

class FakeRack:

    def __init__(self, number: int) -> None:
        self.num = number

class FakeLiveApp:

    def __init__(self, case: FakeLiveCase) -> None:
        self.case = case
        self.connect_calls = 0
        self.disconnect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    def get_version(self) -> str:
        return '2.7.3'

    def get_available_racks(self) -> list[FakeRack]:
        return [FakeRack(1)]

    def get_case(self, *, file: str, open_file: bool) -> None:
        return None

    def open_case(self, file: str) -> FakeLiveCase:
        return self.case

    def disconnect(self, *, terminate: bool) -> None:
        self.disconnect_calls += 1

class InjectedRuntimeDriver(RscadFxRuntimeDriver):

    def __init__(self, config: ProductionBackendConfig, app: FakeLiveApp) -> None:
        self.sleep_calls: list[float] = []
        super().__init__(config, sleeper=self.sleep_calls.append)
        self.app = app
        self.app.sleep_calls = self.sleep_calls

    def _new_connection(self) -> FakeLiveApp:
        return self.app

class RuntimeContractTests(unittest.TestCase):

    def test_runtime_single_curve_plot_ids_maps_exact_signal(self) -> None:
        rtx = 'COMPONENT: TAGGED_V2.2_PLOT\n  GROUP: Subsystem #1|LNRT|Box|Node Voltages\n  DESC: S1) A1\n  UUID: 1850\n  PLOT-DATA-START\n    CURVE-START\n      GROUP: Subsystem #1|LNRT|Box|Node Voltages\n      DESC: S1) A1\n    CURVE-END\n  PLOT-DATA-END\nCOMPONENT-END:\n'
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'plot.rtfx'
            with zipfile.ZipFile(fixture, 'w') as archive:
                archive.writestr('fixture.rtx', rtx)
            plots = runtime_single_curve_plot_ids(fixture)
        self.assertEqual(plots['Subsystem #1|LNRT|Box|Node Voltages|S1) A1'], 1850)

    def test_single_curve_plot_csv_parser_skips_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            export = Path(temporary) / 'plot.csv'
            export.write_text('Time,Signal\n0.0,1.0\n0.1,1.1\n0.2,1.2\n', encoding='utf-8')
            times, values = _read_single_curve_plot_csv(export)
        self.assertEqual(times, [0.0, 0.1, 0.2])
        self.assertEqual(values, [1.0, 1.1, 1.2])

    @staticmethod
    def _write_meter_fixture(path: Path, lnrt_names: list[str]) -> None:
        rtx = 'COMPONENT: TAGGED_V2.2_METER\n  GROUP: Subsystem #1|Node Voltages\n  DESC: S1) A1\n  UUID: 793\nCOMPONENT-END:\n'
        dfx = '\n'.join((f'HIERARCHY-START:\nCOMPONENT_TYPE=HIERARCHY\nPARAMETERS-START:\nName    :{name}\nType    :LNRT\nPARAMETERS-END:\nHIERARCHY-END:' for name in lnrt_names))
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('fixture.rtx', rtx)
            archive.writestr('fixture.dfx', dfx)

    def test_runtime_meter_ids_does_not_alias_multiple_lnrt_boxes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / 'fixture.rtfx'
            self._write_meter_fixture(fixture, ['LNRT_A', 'LNRT_B'])
            meters = runtime_meter_ids(fixture)
        self.assertEqual(meters, {'Subsystem #1|Node Voltages|S1) A1': 793})

    def test_latest_numeric_flattens_vector_meter_current_values(self) -> None:
        self.assertEqual(_latest_numeric([[0.0, 1.25], [0.1, 1.5]]), 1.5)
        with self.assertRaises(RuntimeContractError):
            _latest_numeric([[float('nan')], ['not numeric']])

    def test_runtime_schemas_are_valid(self) -> None:
        for name in ('runtime_test_spec.schema.json', 'runtime_execution_manifest.schema.json'):
            schema = json.loads((HERE / name).read_text(encoding='utf-8'))
            self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
            self.assertEqual(schema['type'], 'object')
            self.assertTrue(schema['required'])

    def test_valid_read_only_plan_is_canonicalized(self) -> None:
        plan = validate_runtime_test_spec(runtime_spec())
        self.assertEqual(plan['test_id'], 'fake_runtime_read_only_capture')
        self.assertEqual(len(plan['measurement_channels']), 2)
        self.assertEqual(plan['runtime_controls']['runtime_parameter_writes'], [])
        self.assertFalse(plan['loadflow_initialization']['enabled'])

    def test_control_plan_is_canonicalized(self) -> None:
        plan = validate_runtime_test_spec(runtime_control_spec())
        action = plan['runtime_controls']['runtime_parameter_writes'][0]
        self.assertEqual(plan['execution_mode'], 'runtime_control_and_signal_capture')
        self.assertEqual(action['object_uuid'], 603)
        self.assertEqual(action['purpose'], 'lockfree_change')
        self.assertTrue(action['restore_after_capture'])
        self.assertEqual(action['phase'], 'after_run')

    def test_lock_release_sequence_is_canonicalized(self) -> None:
        plan = validate_runtime_test_spec(runtime_lock_release_spec())
        actions = plan['runtime_controls']['runtime_parameter_writes']
        self.assertEqual([item['phase'] for item in actions], ['before_run', 'after_run'])
        self.assertEqual(actions[0]['value'], actions[1]['expected_initial_value'])

    def test_repeated_target_sequence_requires_value_chain(self) -> None:
        spec = runtime_lock_release_spec()
        spec['runtime_controls']['runtime_parameter_writes'][1]['expected_initial_value'] = 1
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_lockfree_requires_exact_machine_or_breaker_switch(self) -> None:
        spec = runtime_control_spec()
        spec['runtime_controls']['runtime_parameter_writes'][0]['object_group'] = 'Subsystem #1|Controls'
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_runtime_control_bounds_and_restore_are_enforced(self) -> None:
        spec = runtime_control_spec()
        spec['runtime_controls']['runtime_parameter_writes'][0]['value'] = 2
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)
        spec = runtime_control_spec()
        spec['runtime_controls']['runtime_parameter_writes'][0]['restore_after_capture'] = False
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_loadflow_plan_is_canonicalized(self) -> None:
        spec = runtime_spec()
        spec['loadflow_initialization'] = {'enabled': True, 'timeout_seconds': 60, 'zero_impedance_threshold_pu': 1e-06, 'flat_start': True, 'method': 'FAST_DECOUPLED'}
        plan = validate_runtime_test_spec(spec)
        self.assertEqual(plan['loadflow_initialization'], spec['loadflow_initialization'])

    def test_unsafe_loadflow_plan_is_rejected(self) -> None:
        for field, value in (('timeout_seconds', 121), ('zero_impedance_threshold_pu', 1.0), ('flat_start', 'yes'), ('method', 'UNREVIEWED')):
            spec = runtime_spec()
            spec['loadflow_initialization'] = {'enabled': True, 'timeout_seconds': 60, 'zero_impedance_threshold_pu': 1e-06, 'flat_start': True, 'method': 'FAST_DECOUPLED'}
            spec['loadflow_initialization'][field] = value
            with self.subTest(field=field):
                with self.assertRaises(RuntimeContractError):
                    validate_runtime_test_spec(spec)

    def test_runtime_event_is_rejected(self) -> None:
        spec = runtime_spec()
        spec['event'] = {'type': 'fault'}
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_runtime_parameter_write_plan_is_rejected(self) -> None:
        spec = runtime_spec()
        spec['runtime_controls']['runtime_parameter_writes'] = [{'component': 'switch', 'value': 1}]
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_hardware_and_deployment_plans_are_rejected(self) -> None:
        for field in ('hardware_io_changes', 'rack_configuration_changes', 'deployment_actions'):
            spec = runtime_spec()
            spec['runtime_controls'][field] = [{'operation': 'injected'}]
            with self.subTest(field=field):
                with self.assertRaises(RuntimeContractError):
                    validate_runtime_test_spec(spec)

    def test_duplicate_signal_path_is_rejected(self) -> None:
        spec = runtime_spec()
        spec['measurement_channels'][1]['signal_path'] = spec['measurement_channels'][0]['signal_path']
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

    def test_runtime_bounds_are_enforced(self) -> None:
        spec = runtime_spec()
        spec['runtime_capture']['warmup_seconds'] = 31.0
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)
        spec = runtime_spec()
        spec['runtime_capture']['minimum_samples_per_channel'] = 0
        with self.assertRaises(RuntimeContractError):
            validate_runtime_test_spec(spec)

class RscadFxRuntimeDriverTests(unittest.TestCase):

    def setUp(self) -> None:
        self.path = str(AGENT / 'projects' / 'fake' / 'working' / 'case.rtfx')
        self.config = ProductionBackendConfig(rscad_root=ROOT, agent_root=AGENT)

    def _capture(self, case: FakeLiveCase, *, loadflow_enabled: bool=False, writes: list[dict[str, Any]] | None=None, warmup_seconds: float=0.0) -> tuple[dict[str, Any], FakeLiveApp]:
        app = FakeLiveApp(case)
        driver = InjectedRuntimeDriver(self.config, app)
        result = driver.capture_case(working_copy=self.path, rack=1, channels=runtime_spec()['measurement_channels'], warmup_seconds=warmup_seconds, runtime_parameter_writes=writes or [], loadflow_initialization={'enabled': True, 'timeout_seconds': 60, 'zero_impedance_threshold_pu': 1e-06, 'flat_start': True, 'method': 'FAST_DECOUPLED'} if loadflow_enabled else {'enabled': False})
        return (result, app)

    def test_live_driver_success_stops_closes_and_disconnects(self) -> None:
        case = FakeLiveCase(self.path)
        result, app = self._capture(case)
        self.assertTrue(result['execution']['run_started'])
        self.assertTrue(result['execution']['stop_succeeded'])
        self.assertEqual(result['execution']['run_return_value'], 'None')
        self.assertEqual(result['execution']['stop_return_value'], 'None')
        self.assertEqual(result['execution']['plot_update_wait_seconds'], 5.0)
        self.assertEqual(app.sleep_calls, [0.0, 5.0])
        self.assertTrue(result['cleanup']['case_closed'])
        self.assertTrue(result['cleanup']['disconnected'])
        self.assertEqual(case.run_calls, 1)
        self.assertEqual(case.stop_calls, 1)
        self.assertEqual(case.close_calls, 1)
        self.assertEqual(app.disconnect_calls, 1)

    def test_live_driver_applies_reads_back_and_restores_lockfree(self) -> None:
        with tempfile.TemporaryDirectory(dir=AGENT / 'projects') as temporary:
            path = Path(temporary) / 'controls.rtfx'
            rtx = 'COMPONENT: TAGGED_V2.2_SWITCH\nNAME: LockFree\nGROUP: Subsystem #1|Machines|BUS39x1\nDESC: LockFree\nUUID: 603\nCOMPONENT-END:\n'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('controls.rtx', rtx)
            self.path = str(path)
            control = FakeRuntimeInput(position=1)
            case = FakeLiveCase(self.path, runtime_objects={603: control})
            writes = validate_runtime_test_spec(runtime_control_spec())['runtime_controls']['runtime_parameter_writes']
            result, _ = self._capture(case, writes=writes)
        self.assertEqual(result['runtime_controls']['applied'], 1)
        self.assertEqual(result['runtime_controls']['restored'], 1)
        self.assertTrue(result['runtime_controls']['all_restored'])
        self.assertEqual(control.position, 1)
        self.assertTrue(result['safety']['runtime_parameter_write_called'])

    def test_live_driver_locks_before_run_releases_after_settle_and_restores(self) -> None:
        with tempfile.TemporaryDirectory(dir=AGENT / 'projects') as temporary:
            path = Path(temporary) / 'controls.rtfx'
            rtx = 'COMPONENT: TAGGED_V2.2_SWITCH\nNAME: LockFree\nGROUP: Subsystem #1|Machines|BUS39x1\nDESC: LockFree\nUUID: 603\nCOMPONENT-END:\n'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('controls.rtx', rtx)
            self.path = str(path)
            control = FakeRuntimeInput(position=1)
            case = FakeLiveCase(self.path, runtime_objects={603: control})
            plan = validate_runtime_test_spec(runtime_lock_release_spec())
            writes = plan['runtime_controls']['runtime_parameter_writes']
            result, app = self._capture(case, writes=writes, warmup_seconds=1.0)
        self.assertEqual(result['runtime_controls']['applied'], 2)
        self.assertEqual(result['runtime_controls']['restore_targets_planned'], 1)
        self.assertEqual(result['runtime_controls']['restored'], 1)
        self.assertTrue(result['runtime_controls']['all_restored'])
        self.assertEqual(control.position, 1)
        self.assertEqual(app.sleep_calls, [0.5, 0.5, 5.0])

    def test_loadflow_runs_before_runtime_start(self) -> None:
        case = FakeLiveCase(self.path)
        result, app = self._capture(case, loadflow_enabled=True)
        self.assertEqual(case.events[:2], ['loadflow', 'run'])
        self.assertEqual(case.loadflow_calls, [(60, 1e-06, True, 'FAST_DECOUPLED')])
        self.assertTrue(result['execution']['loadflow_succeeded'])
        self.assertTrue(result['safety']['load_flow_called'])
        self.assertTrue(result['execution']['stop_succeeded'])
        self.assertTrue(result['cleanup']['case_closed'])
        self.assertEqual(app.disconnect_calls, 1)

    def test_loadflow_failure_prevents_run_and_cleans_up(self) -> None:
        case = FakeLiveCase(self.path, loadflow_fails=True)
        result, app = self._capture(case, loadflow_enabled=True)
        self.assertTrue(result['execution']['loadflow_call_attempted'])
        self.assertFalse(result['execution']['loadflow_succeeded'])
        self.assertEqual(case.run_calls, 0)
        self.assertEqual(case.stop_calls, 0)
        self.assertTrue(result['cleanup']['case_closed'])
        self.assertTrue(result['cleanup']['disconnected'])
        self.assertEqual(app.disconnect_calls, 1)

    def test_signal_read_failure_still_stops_and_cleans_up(self) -> None:
        case = FakeLiveCase(self.path, signal_fails=True)
        result, app = self._capture(case)
        self.assertTrue(result['errors'])
        self.assertTrue(result['execution']['stop_succeeded'])
        self.assertEqual(result['execution']['run_return_value'], 'None')
        self.assertEqual(result['execution']['stop_return_value'], 'None')
        self.assertTrue(result['cleanup']['case_closed'])
        self.assertTrue(result['cleanup']['disconnected'])
        self.assertEqual(case.stop_calls, 1)
        self.assertEqual(app.disconnect_calls, 1)

    def test_stop_exception_is_preserved_as_cleanup_error(self) -> None:
        case = FakeLiveCase(self.path, stop_fails=True)
        result, app = self._capture(case)
        self.assertFalse(result['execution']['stop_succeeded'])
        self.assertTrue(result['cleanup_errors'])
        self.assertTrue(result['cleanup']['case_closed'])
        self.assertTrue(result['cleanup']['disconnected'])
        self.assertEqual(app.disconnect_calls, 1)

    def test_non_stopped_case_is_never_started(self) -> None:
        case = FakeLiveCase(self.path, initial_state='running')
        result, app = self._capture(case)
        self.assertTrue(result['errors'])
        self.assertEqual(case.run_calls, 0)
        self.assertEqual(case.stop_calls, 0)
        self.assertEqual(case.close_calls, 1)
        self.assertEqual(app.disconnect_calls, 1)

class ProductionRuntimeBackendTests(unittest.TestCase):

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix='runtime_backend_test_', dir=AGENT / 'projects')
        self.addCleanup(self.temporary.cleanup)
        self.run_dir = Path(self.temporary.name) / 'run'
        self.working_dir = self.run_dir / 'working'
        self.working_dir.mkdir(parents=True)
        self.working = self.working_dir / 'case.rtfx'
        self.working.write_bytes(b'immutable working case')
        self.source_root = self.run_dir / 'fake_rscad' / 'Examples'
        self.source_root.mkdir(parents=True)
        self.source = self.source_root / 'source.rtfx'
        self.source.write_bytes(b'immutable vendor source')
        self.build = self.working_dir / 'build_case'
        self.build.mkdir()
        self.artifact = self.build / 'case_r1'
        self.artifact.write_bytes(b'immutable compiled artifact')
        self.rack_driver = FakeRackDriver()
        self.runtime_driver = FakeRuntimeDriver()
        self.config = ProductionBackendConfig(rscad_root=self.run_dir / 'fake_rscad', agent_root=AGENT)
        self.workflow = self._workflow()
        self.backend = self._backend()

    def _workflow(self, *, loadflow_enabled: bool=False, controls: bool=False) -> Workflow:
        spec = runtime_control_spec() if controls else runtime_spec()
        if loadflow_enabled:
            spec['loadflow_initialization'] = {'enabled': True, 'timeout_seconds': 60, 'zero_impedance_threshold_pu': 1e-06, 'flat_start': True, 'method': 'FAST_DECOUPLED'}
        workflow = Workflow.create(workflow_id='production-runtime-test', project={'source_path': str(self.source), 'source_sha256': sha256_file(self.source), 'working_copy': str(self.working), 'working_sha256': sha256_file(self.working), 'working_root': str(AGENT / 'projects'), 'vendor_source_root': str(self.source_root)}, test_spec=spec)
        workflow.record_stage('inspection', passed=True, evidence=[])
        workflow.record_stage('grounding', passed=True, evidence=[])
        workflow.record_stage('static_validation', passed=True, evidence=[])
        workflow.request_approval(ApprovalAction.COMPILE, reason='test compile')
        workflow.grant_approval(ApprovalAction.COMPILE, actor='tester', source='unit test')
        workflow.consume_approval(ApprovalAction.COMPILE, rack_snapshot={'source': 'live_query_immediately_before_action', 'available_racks': [1], 'selected_rack': 1})
        workflow.record_compile_result(succeeded=True, artifact_sha256=sha256_file(self.artifact), result_ref={'backend': 'fixture'})
        return workflow

    def _backend(self, *, runtime_enabled: bool=True, runtime_driver: Any=...) -> ProductionRscadBackend:
        selected_driver = self.runtime_driver if runtime_driver is ... else runtime_driver
        return ProductionRscadBackend(self.config, compile_driver=self.rack_driver, runtime_driver=selected_driver, runtime_enabled=runtime_enabled)

    def _approve(self) -> ApprovalGatedOrchestrator:
        self.workflow.request_approval(ApprovalAction.RUNTIME, reason='explicit unit-test Runtime approval')
        self.workflow.grant_approval(ApprovalAction.RUNTIME, actor='tester', source='explicit unit test only')
        return ApprovalGatedOrchestrator(self.workflow, self.backend)

    def _execute(self) -> dict[str, Any]:
        return self._approve().execute_runtime()

    def _latest_manifest(self) -> dict[str, Any]:
        paths = sorted(self.run_dir.glob('runtime_runs/*/runtime_execution.json'))
        self.assertEqual(len(paths), 1)
        return json.loads(paths[0].read_text(encoding='utf-8'))

    def test_runtime_is_disabled_by_default_even_with_driver(self) -> None:
        self.backend = self._backend(runtime_enabled=False)
        with self.assertRaises(BackendSafetyViolation):
            self._execute()
        self.assertEqual(self.runtime_driver.calls, 0)
        self.assertIs(self.workflow.state, WorkflowState.FAILED)

    def test_runtime_requires_an_explicit_driver(self) -> None:
        self.backend = self._backend(runtime_driver=None)
        with self.assertRaises(BackendSafetyViolation):
            self._execute()
        self.assertIs(self.workflow.state, WorkflowState.FAILED)

    def test_happy_path_writes_hash_bound_raw_evidence(self) -> None:
        result = self._execute()
        self.assertTrue(result['succeeded'])
        self.assertTrue(result['safe_completion'])
        self.assertIs(self.workflow.state, WorkflowState.RUNTIME_COMPLETED)
        manifest = self._latest_manifest()
        self.assertEqual(manifest['status'], 'runtime_completed')
        self.assertTrue(manifest['safe_completion'])
        self.assertEqual(manifest['authorization']['status'], 'consumed')
        self.assertEqual(manifest['authorization']['risk_level'], 'L4')
        raw = manifest['raw_data']
        self.assertEqual(raw['rows'], 6)
        self.assertEqual(sha256_file(raw['path']), raw['sha256'])
        self.assertEqual(manifest['signals']['VA']['sample_count'], 3)
        self.assertNotIn('samples', manifest['driver'])
        self.assertTrue(all(manifest['hashes']['integrity'].values()))

    def test_loadflow_happy_path_is_hash_bound_and_required(self) -> None:
        self.workflow = self._workflow(loadflow_enabled=True)
        result = self._execute()
        self.assertTrue(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertTrue(manifest['runtime_plan']['loadflow_initialization']['enabled'])
        self.assertTrue(manifest['execution']['loadflow_call_attempted'])
        self.assertTrue(manifest['execution']['loadflow_succeeded'])
        self.assertTrue(manifest['safety']['load_flow_called'])

    def test_loadflow_compiled_artifact_mutation_is_authorized(self) -> None:
        self.workflow = self._workflow(loadflow_enabled=True)
        self.runtime_driver.mutate_path = self.artifact
        result = self._execute()
        self.assertTrue(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertFalse(manifest['hashes']['integrity']['compiled_artifact_unchanged'])
        self.assertTrue(manifest['hashes']['compiled_artifact_change_authorized_by_loadflow'])

    def test_loadflow_failure_fails_closed(self) -> None:
        self.workflow = self._workflow(loadflow_enabled=True)
        self.runtime_driver.mode = 'loadflow_failure'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertFalse(manifest['execution']['loadflow_succeeded'])
        self.assertTrue(any((item['type'] == 'SafetyTelemetryError' for item in manifest['errors'])))

    def test_working_copy_tamper_is_blocked_before_driver(self) -> None:
        orchestrator = self._approve()
        self.working.write_bytes(b'tampered working case')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_runtime()
        self.assertEqual(self.runtime_driver.calls, 0)
        self.assertIs(self.workflow.state, WorkflowState.FAILED)

    def test_source_tamper_is_blocked_before_driver(self) -> None:
        orchestrator = self._approve()
        self.source.write_bytes(b'tampered vendor source')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_runtime()
        self.assertEqual(self.runtime_driver.calls, 0)

    def test_compiled_artifact_tamper_is_blocked_before_driver(self) -> None:
        orchestrator = self._approve()
        self.artifact.write_bytes(b'tampered compiled artifact')
        with self.assertRaises(BackendSafetyViolation):
            orchestrator.execute_runtime()
        self.assertEqual(self.runtime_driver.calls, 0)

    def test_runtime_rack_must_match_compile_rack(self) -> None:
        self.rack_driver.selected_rack = 2
        with self.assertRaises(SafetyViolation):
            self._execute()
        self.assertEqual(self.runtime_driver.calls, 0)
        self.assertIs(self.workflow.state, WorkflowState.RUNTIME_APPROVED)

    def test_tampered_approval_receipt_is_rejected(self) -> None:
        self.workflow.request_approval(ApprovalAction.RUNTIME, reason='receipt tamper test')
        self.workflow.grant_approval(ApprovalAction.RUNTIME, actor='tester', source='unit test')
        snapshot = self.backend.refresh_racks(ApprovalAction.RUNTIME.value)
        receipt = self.workflow.consume_approval(ApprovalAction.RUNTIME, rack_snapshot=snapshot)
        receipt = copy.deepcopy(receipt)
        receipt['scope']['test_spec_sha256'] = '0' * 64
        project = self.workflow.manifest['project']
        with self.assertRaises(BackendSafetyViolation):
            self.backend.run_runtime(working_copy=project['working_copy'], rack=1, test_spec=self.workflow.manifest['test_spec'], expected_working_sha256=project['working_sha256'], compiled_artifact_sha256=self.workflow.manifest['compile']['artifact_sha256'], source_path=project['source_path'], expected_source_sha256=project['source_sha256'], authorization=receipt)
        self.assertEqual(self.runtime_driver.calls, 0)

    def test_authorized_runtime_controls_are_accepted_and_audited(self) -> None:
        self.workflow = self._workflow(controls=True)
        result = self._execute()
        self.assertTrue(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertTrue(manifest['safety']['runtime_parameter_write_called'])
        controls = manifest['driver']['runtime_controls']
        self.assertEqual(controls['planned'], 1)
        self.assertEqual(controls['applied'], 1)
        self.assertEqual(controls['restored'], 1)
        self.assertTrue(controls['all_restored'])

    def test_stop_failure_records_cleanup_failure(self) -> None:
        self.runtime_driver.mode = 'stop_failure'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        self.assertFalse(result['stopped'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        manifest = self._latest_manifest()
        self.assertEqual(manifest['status'], 'runtime_cleanup_failed')
        self.assertTrue(manifest['cleanup_errors'])

    def test_disconnect_failure_is_not_safe_completion(self) -> None:
        self.runtime_driver.mode = 'disconnect_failure'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        self.assertTrue(result['stopped'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)
        self.assertEqual(self._latest_manifest()['status'], 'runtime_cleanup_failed')

    def test_parameter_write_telemetry_fails_closed(self) -> None:
        self.runtime_driver.mode = 'runtime_write'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertTrue(manifest['safety']['runtime_parameter_write_called'])
        self.assertTrue(any((item['type'] == 'SafetyTelemetryError' for item in manifest['errors'])))

    def test_hardware_io_telemetry_fails_closed(self) -> None:
        self.runtime_driver.mode = 'hardware_io'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        self.assertTrue(self._latest_manifest()['safety']['hardware_io_called'])

    def test_non_finite_raw_data_fails_closed(self) -> None:
        self.runtime_driver.mode = 'nan'
        result = self._execute()
        self.assertFalse(result['raw_data_collected'])
        self.assertFalse(result['safe_completion'])
        self.assertIsNone(self._latest_manifest()['raw_data'])

    def test_minimum_sample_count_is_enforced(self) -> None:
        self.runtime_driver.mode = 'too_few_samples'
        result = self._execute()
        self.assertFalse(result['raw_data_collected'])
        self.assertFalse(result['safe_completion'])

    def test_wrong_opened_case_fails_closed(self) -> None:
        self.runtime_driver.mode = 'wrong_file'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        self.assertIs(self.workflow.state, WorkflowState.FAILED)

    def test_case_must_be_stopped_before_start(self) -> None:
        self.runtime_driver.mode = 'already_running'
        result = self._execute()
        self.assertFalse(result['safe_completion'])

    def test_input_mutation_during_runtime_fails_integrity(self) -> None:
        self.runtime_driver.mutate_path = self.working
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        manifest = self._latest_manifest()
        self.assertFalse(manifest['hashes']['integrity']['working_unchanged'])
        self.assertTrue(any((item['type'] == 'IntegrityError' for item in manifest['errors'])))

    def test_driver_exception_preserves_failure_evidence(self) -> None:
        self.runtime_driver.mode = 'raise'
        result = self._execute()
        self.assertFalse(result['safe_completion'])
        self.assertFalse(result['run_started'])
        manifest = self._latest_manifest()
        self.assertEqual(manifest['status'], 'runtime_failed')
        self.assertEqual(manifest['errors'][0]['type'], 'RuntimeError')
if __name__ == '__main__':
    unittest.main(verbosity=2)

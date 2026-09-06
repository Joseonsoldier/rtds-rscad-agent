"""Public timing plans/assessment and pre-dispatch refusal; authored data only."""
import test_environment
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_experiment_suites as suites
import test_public_release as public
import test_runtime_backend as runtime
from rtds_agent import execution
from rtds_agent.core.experiment_spec import compile_spec
from rtds_agent.core.runtime_backend import validate_runtime_test_spec, RuntimeContractError
from rtds_agent.core.state_machine import sha256_file
from rtds_agent.experiments import run_experiment_suite


def timed_spec(digest):
    spec=suites.spec()
    spec['channels']=[{'channel_id':'state','signal_path':'Authored|State','units':'position','sign_convention':'0=open 1=closed'},
                      {'channel_id':'clock','signal_path':'Authored|Clock','units':'s','sign_convention':'elapsed since declared reset'}]
    spec['event_timing']={'mode':'model_native','clock_channel_id':'clock',
        'source_evidence':{'source_sha256':digest,'locator':'Authored elapsed clock declaration; not a qualified simulator clock'},
        'observations':[{'action_id':name,'channel_id':'state','window_start_seconds':start,'window_end_seconds':end,
                         'value_tolerance':0,'max_timing_error_seconds':.11,'max_sample_gap_seconds':.101}
                        for name,start,end in [('event.fault_on',.8,1.2),('clear.fault_on',1.3,1.7)]]}
    return spec


class PublicTimingTests(unittest.TestCase):
    setUp=public.PublicReleaseTests.setUp

    def request(self):
        request=suites.ExperimentSuiteTests.request(self)
        request['specification']=timed_spec(sha256_file(self.guide))
        return request

    def prepare(self):
        request=self.request();plan=run_experiment_suite(request)
        request={**request,'mode':'prepare','suite_id':plan['suite_id']}
        return request,run_experiment_suite(request)

    def test_native_schedule_is_retained_without_host_writes_or_grants(self):
        before=self.project.read_bytes();request=self.request()
        plan=run_experiment_suite(request)['plan']['runs'][0]
        spec=plan['test_spec'];canonical=validate_runtime_test_spec(spec)
        self.assertEqual(canonical['event_timing'],spec['event_timing'])
        self.assertEqual(canonical['runtime_controls']['runtime_parameter_writes'],[])
        roundtrip=copy.deepcopy(spec);roundtrip['event_timing']=canonical['event_timing']
        self.assertEqual(canonical,validate_runtime_test_spec(roundtrip))
        self.assertFalse(plan['timing_qualification']['execution_supported'])
        req,prepared=self.prepare()
        row=next(iter(prepared['runs'].values()));workflow=json.loads(Path(row['workflow_path']).read_text(encoding='utf-8'))
        self.assertEqual(workflow['approvals'],[])
        self.assertEqual(self.project.read_bytes(),before)
        self.assertFalse(list(self.data.rglob('runtime-request-*.json')))

    def test_unbound_clock_evidence_is_refused_before_preparation(self):
        request=self.request();request['specification']['event_timing']['source_evidence']['source_sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'bound model'):run_experiment_suite(request)
        self.assertFalse(self.settings.projects_root.exists())

    def test_original_model_timing_evidence_refuses_draft_sweep_before_patch(self):
        request=self.request();request['specification']['event_timing']['source_evidence']['source_sha256']=request['source_sha256']
        request['sweep']={'mode':'cartesian','axes':[{'name':'gain','target':{'kind':'draft_parameter','component_id':1,
            'context':'subsystem:0','component_type':'synthetic_gain','parameter':'Gain','expected_old_value':'1'},'values':['2']}]}
        with patch('rtds_agent.core.structured_patch.normalize_request',side_effect=AssertionError('patch')) as patcher:
            with self.assertRaisesRegex(ValueError,'unchanged grounding'):run_experiment_suite(request)
            patcher.assert_not_called()
        self.assertFalse(self.settings.projects_root.exists())

    def test_native_public_actions_never_inspect_installation_or_make_grants(self):
        request,prepared=self.prepare();row=next(iter(prepared['runs'].values()));path=row['workflow_path']
        public.PublicReleaseTests.enable(self,controls=True)
        before={p:p.read_bytes() for p in Path(path).parent.rglob('*') if p.is_file()}
        with patch.object(execution,'_backend',side_effect=AssertionError('backend')) as backend, \
             patch.object(execution,'inspect_installation',side_effect=AssertionError('installation')) as inspection:
            for call in (lambda:execution.compile_project(path),lambda:execution.prepare_simulation_run(path),
                         lambda:execution.run_simulation(path,str(self.data/'no-grant.json'),'0'*64)):
                with self.assertRaisesRegex(ValueError,'[Ss]cheduler'):call()
            backend.assert_not_called();inspection.assert_not_called()
        self.assertEqual(before,{p:p.read_bytes() for p in Path(path).parent.rglob('*') if p.is_file()})

    def test_suite_guard_cannot_dispatch_even_compile(self):
        request,prepared=self.prepare();public.PublicReleaseTests.enable(self,controls=True)
        run_id,row=next(iter(prepared['runs'].items()))
        item={'run_id':run_id,'action':'compile','workflow_sha256':sha256_file(Path(row['workflow_path']))}
        with patch.object(execution,'compile_project') as backend:
            with self.assertRaisesRegex(ValueError,'[Ss]cheduler'):
                run_experiment_suite({**request,'mode':'execute','executions':[item]})
            backend.assert_not_called()

    def test_explicit_debug_retains_legacy_writes_and_rejects_native_mixture(self):
        spec=suites.spec();legacy=compile_spec(spec)
        spec['event_timing']={'mode':'wall_clock_debug'};debug=compile_spec(spec)
        self.assertEqual(legacy['runtime_controls'],debug['runtime_controls'])
        native=compile_spec(timed_spec('a'*64));native['runtime_controls']=legacy['runtime_controls']
        native['execution_mode']='runtime_control_and_signal_capture'
        with self.assertRaisesRegex(RuntimeContractError,'host-timed'):validate_runtime_test_spec(native)

    def test_native_initial_conditions_are_refused_instead_of_lost(self):
        spec=timed_spec('a'*64)
        spec['controls'].append({**spec['controls'][0],'target_id':'other','object_uuid':21})
        spec['initial_conditions']=[{'target_id':'other','value':1,'units':'position'}]
        with self.assertRaisesRegex(ValueError,'initial_conditions'):compile_spec(spec)

    def test_supplied_clock_values_drive_onset_clear_evidence_without_qualification(self):
        request,prepared=self.prepare();run_id,row=next(iter(prepared['runs'].items()))
        workflow=json.loads(Path(row['workflow_path']).read_text(encoding='utf-8'))
        clock=[i/10 for i in range(31)];plot=[100+t for t in clock]
        declarations=request['specification']['channels']
        data={'schema_version':'1.0','input_project_sha256':row['input_project_sha256'],'run_id':workflow['workflow_id'],
              'attempt_id':'authored-timing','time_unit':'s','time_basis':'simulator_time',
              'channels':[{**declarations[0],'times':plot,'values':[1 if 1<=t<1.5 else 0 for t in clock]},
                          {**declarations[1],'times':plot,'values':clock}]}
        path=self.data/'timing-samples.json';path.write_text(json.dumps(data),encoding='utf-8')
        ref={'data_path':str(path),'data_sha256':sha256_file(path),'input_project':row['input_project'],
             'input_project_sha256':row['input_project_sha256'],'run_id':workflow['workflow_id'],'attempt_id':'authored-timing'}
        result=run_experiment_suite({**request,'mode':'assess','captures':[{'run_id':run_id,'source':ref}]})
        timing=result['assessments'][0]['event_timing']
        self.assertEqual([e['observed_simulator_time'] for e in timing['events']],[1,1.5])
        self.assertEqual(timing['source'],ref)
        self.assertFalse(result['deterministic_verified']);self.assertFalse(timing['integration_qualified'])
        self.assertEqual(result['timing_status_counts'],{'passed':1})
        for field,value in (('sign_convention','changed declaration'),('signal_path','Other|State')):
            original=data['channels'][0][field];data['channels'][0][field]=value
            path.write_text(json.dumps(data),encoding='utf-8');ref['data_sha256']=sha256_file(path)
            with self.assertRaisesRegex(ValueError,'metadata differs'):
                run_experiment_suite({**request,'mode':'assess','captures':[{'run_id':run_id,'source':ref}]})
            data['channels'][0][field]=original


class DriverTimingTests(unittest.TestCase):
    def test_orchestrator_and_production_runtime_refuse_before_rack_or_driver(self):
        helper=runtime.ProductionRuntimeBackendTests();helper.setUp();self.addCleanup(helper.doCleanups)
        spec=compile_spec(timed_spec('a'*64))
        helper.workflow.manifest['test_spec']=spec
        orchestrator=helper._approve()
        with patch.object(helper.backend,'refresh_racks',side_effect=AssertionError('rack')) as racks:
            with self.assertRaisesRegex(ValueError,'[Ss]cheduler'):orchestrator.execute_runtime()
            racks.assert_not_called()
        with patch.object(helper.backend,'_project_context',side_effect=AssertionError('project')) as context:
            with self.assertRaisesRegex(ValueError,'[Ss]cheduler'):
                helper.backend.run_runtime(working_copy=str(helper.working),rack=1,test_spec=spec,
                    expected_working_sha256=sha256_file(helper.working),compiled_artifact_sha256=sha256_file(helper.artifact),
                    source_path=str(helper.source),expected_source_sha256=sha256_file(helper.source))
            context.assert_not_called()

    def test_direct_driver_refuses_native_before_connection(self):
        helper=runtime.RscadFxRuntimeDriverTests()
        # Reuse configuration initialization only; no external SDK object is used.
        runtime.RscadFxRuntimeDriverTests.setUp(helper)
        self.addCleanup(helper.doCleanups)
        case=runtime.FakeLiveCase('authored.rtfx');app=runtime.FakeLiveApp(case)
        driver=runtime.InjectedRuntimeDriver(helper.config,app)
        result=driver.capture_case(working_copy='authored.rtfx',rack=1,channels=[],warmup_seconds=0,
                                   event_timing={'mode':'model_native'})
        self.assertTrue(result['errors']);self.assertEqual(app.connect_calls,0)

    def test_default_control_receipts_never_invent_measured_simulator_time(self):
        import test_native_acquisition as native
        import test_runtime_binding as binding
        helper=native.AcquisitionTests();helper.setUp();self.addCleanup(helper.doCleanups)
        native.write_project(helper.path,native.RTX+binding.RTX)
        helper.context['input_project_sha256']=sha256_file(Path(helper.path))
        helper.case=native.Case(helper.path,runtime_objects={603:runtime.FakeRuntimeInput(position=1)})
        writes=validate_runtime_test_spec(runtime.runtime_control_spec())['runtime_controls']['runtime_parameter_writes']
        result,_=helper.capture(writes)
        self.assertEqual(result['errors'],[])
        for action in result['runtime_controls']['actions']:
            receipt=action['timing_evidence']
            self.assertFalse(receipt['deterministic_verified'])
            self.assertIsNone(receipt['observed_simulator_time']);self.assertIsNone(receipt['measured_timing_error_seconds'])
            self.assertEqual(receipt['qualification_state'],'debug_nonauthoritative')
        self.assertNotIn('event_timing',validate_runtime_test_spec(runtime.runtime_spec()))


if __name__=='__main__':unittest.main()

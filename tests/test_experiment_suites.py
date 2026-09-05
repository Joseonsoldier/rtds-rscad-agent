"""DSL, traceability, sequential dispatch and resume under synthetic policy only."""
import test_environment
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_public_release as fixture
from rtds_agent.core.experiment_spec import compile_spec,expand
from rtds_agent.experiments import run_experiment_suite
from rtds_agent.project_tools import inspect_rscad_project
from rtds_agent.core.state_machine import sha256_file,sha256_json


def spec():
    return {'schema_version':'1.0','test_id':'synthetic-lvrt','controls':[{
        'target_id':'fault','purpose':'switch_operation','object_uuid':20,'object_type':'switch','object_name':'fault',
        'object_group':'Subsystem #1|Controls','object_desc':'fault','attribute':'position','expected_initial_value':0,'units':'position'}],
        'initial_conditions':[], 'events':[{'event_id':'fault_on','kind':'fault','target_id':'fault','value':1,'units':'position','at_seconds':1,'duration_seconds':.5,'clear_value':0}],
        'channels':[{'channel_id':'voltage','signal_path':'Subsystem #1|BUS|V','units':'pu','sign_convention':'positive','pu_base':100}],
        'capture_after_seconds':3,'minimum_samples_per_channel':2,'criteria':{'schema_version':'1.0','requirements':[]},'traceability':[]}


class ExperimentSuiteTests(unittest.TestCase):
    setUp=fixture.PublicReleaseTests.setUp

    def request(self, sweep=None):
        return {'mode':'plan','source_project':str(self.project),'source_sha256':sha256_file(self.project),
                'snapshot_id':inspect_rscad_project(str(self.project))['snapshot_id'],'grounding_paths':[str(self.guide)],
                'specification':spec(),'sweep':sweep or {'mode':'cartesian','axes':[]}}

    def prepared(self, request=None):
        request=request or self.request()
        plan=run_experiment_suite(request)
        req={**request,'mode':'prepare','suite_id':plan['suite_id']}
        return req,run_experiment_suite(req)

    def test_event_duration_initial_chain_and_restoration(self):
        s=spec()
        s['initial_conditions']=[{'target_id':'fault','value':1,'units':'position'}]
        s['events'][0]['value']=0
        s['events'][0]['clear_value']=1
        writes=compile_spec(s)['runtime_controls']['runtime_parameter_writes']
        self.assertEqual([w['expected_initial_value'] for w in writes],[0,1,0])
        self.assertEqual([w['value'] for w in writes],[1,0,1])
        self.assertTrue(all(w['restore_after_capture'] for w in writes))
        self.assertEqual([w['apply_after_seconds'] for w in writes],[0,1,1.5])

    def test_duplicate_target_time_units_duration_and_bounds_rejected(self):
        for mutate in (lambda s:s['events'].append({**s['events'][0],'event_id':'second'}),
                       lambda s:s['events'][0].update(units='V'),
                       lambda s:s['events'][0].update(duration_seconds=30),
                       lambda s:s['controls'].append({**s['controls'][0],'target_id':'alias'})):
            s=spec(); mutate(s)
            with self.assertRaises(ValueError): compile_spec(s)

    def test_lockfree_requires_an_exact_hierarchy_segment(self):
        from test_runtime_backend import runtime_control_spec
        from rtds_agent.core.runtime_backend import validate_runtime_test_spec, RuntimeContractError
        for group in ('Subsystem #1|NotMachines|BUS','Subsystem #1|BreakersBackup|BUS'):
            candidate=runtime_control_spec()
            candidate['runtime_controls']['runtime_parameter_writes'][0]['object_group']=group
            with self.assertRaisesRegex(RuntimeContractError,'exact machine/breaker'):
                validate_runtime_test_spec(candidate)

    def test_plan_is_deterministic_and_prepare_resumes_without_duplicate_workflows(self):
        req=self.request()
        a=run_experiment_suite(req); b=run_experiment_suite(req)
        self.assertEqual(a,b)
        req,result=self.prepared(req)
        before=sorted((self.data/'projects').iterdir())
        self.assertEqual(run_experiment_suite(req),result)
        self.assertEqual(sorted((self.data/'projects').iterdir()),before)
        self.assertFalse((self.data/'execution_policy.json').exists())

    def test_cartesian_and_paired_matrices_and_limit(self):
        s=spec(); s['initial_conditions']=[{'target_id':'fault','value':0,'units':'position'}]
        axes=[{'name':'event','target':{'kind':'event_value','id':'fault_on'},'values':[0,1]},
              {'name':'initial','target':{'kind':'initial_value','id':'fault'},'values':[0,1]}]
        self.assertEqual(len(expand(s,{'mode':'cartesian','axes':axes})),4)
        self.assertEqual(len(expand(s,{'mode':'paired','axes':axes})),2)
        axes[1]['values']=[0]
        with self.assertRaisesRegex(ValueError,'equal'): expand(s,{'mode':'paired','axes':axes})
        axes[0]['values']=list(range(65))
        with self.assertRaisesRegex(ValueError,'64'): expand(s,{'mode':'cartesian','axes':axes})

    def test_draft_parameter_sweep_reuses_atomic_numeric_patch(self):
        from rtds_agent.knowledge import index_parameters
        index_parameters(str(self.project))
        sweep={'mode':'cartesian','axes':[{'name':'Gain','target':{'kind':'draft_parameter','component_id':1,
                  'context':'subsystem:0','component_type':'synthetic_gain','parameter':'Gain','expected_old_value':'1'},'values':['2','3']}]}
        req,result=self.prepared(self.request(sweep))
        from rtds_agent.project_tools import _document
        gains={_document(row['input_project'])[2]['components'][0]['parameters']['Gain'] for row in result['runs'].values()}
        self.assertEqual(gains,{'2','3'})
        self.assertEqual(_document(str(self.project))[2]['components'][0]['parameters']['Gain'],'1')

    def test_inactive_execution_rejected_before_planning_and_backend(self):
        req=self.request(); req.update(mode='execute',suite_id='0'*64,executions=[{'run_id':'0'*64,'action':'compile','workflow_sha256':'0'*64}])
        with patch('rtds_agent.experiments.plan_suite') as planner,patch('rtds_agent.execution._backend') as backend:
            with self.assertRaises(PermissionError): run_experiment_suite(req)
            planner.assert_not_called(); backend.assert_not_called()

    def test_sequential_compile_runtime_and_skip_completed_use_existing_grants(self):
        from rtds_agent import execution
        from rtds_agent.core.mock_backend import MockBackend
        req,prepared=self.prepared()
        fixture.PublicReleaseTests.enable(self,controls=True)
        run_id,row=next(iter(prepared['runs'].items()))
        path=Path(row['workflow_path'])
        class ArtifactMock(MockBackend):
            def bind(self,result,working,stage):
                artifact=Path(working).parent.parent/(stage+'.authored.json')
                artifact.write_text(json.dumps({'evidence_kind':'synthetic','result':result}))
                result['result_ref']={'path':str(artifact),'sha256':sha256_file(artifact)}
                return result
            def compile(self,**kwargs):
                return self.bind(super().compile(**kwargs),kwargs['working_copy'],'compile')
            def run_runtime(self,**kwargs):
                return self.bind(super().run_runtime(**kwargs),kwargs['working_copy'],'runtime')
        backend=ArtifactMock(available_racks=[2],selected_rack=2)
        compile_request={**req,'mode':'execute','executions':[{'run_id':run_id,'action':'compile','workflow_sha256':sha256_file(path)}]}
        with patch.object(execution,'verify_release',return_value={'synthetic':True}),patch.object(execution,'inspect_installation',return_value={'synthetic':True}),patch.object(execution,'_backend',return_value=backend):
            result=run_experiment_suite(compile_request)
            self.assertEqual(result['actions'][0]['status'],'completed')
            self.assertEqual(run_experiment_suite(compile_request)['actions'][0]['status'],'skipped_completed')
            grant=execution.prepare_simulation_run(str(path))
            runtime_request={**req,'mode':'execute','executions':[{'run_id':run_id,'action':'runtime','workflow_sha256':sha256_file(path),**grant}]}
            runtime_request['executions'][0].pop('live_calls_made')
            self.assertEqual(run_experiment_suite(runtime_request)['actions'][0]['status'],'completed')
            self.assertEqual(run_experiment_suite(runtime_request)['actions'][0]['status'],'skipped_completed')
        self.assertEqual([a['call'] for a in backend.call_log],['refresh_racks','compile','refresh_racks','run_runtime'])
        self.assertEqual([a['status'] for a in json.loads(path.read_text())['approvals']],['consumed','consumed'])

    def test_interrupted_preparation_and_action_are_not_repeated(self):
        req,prepared=self.prepared()
        path=Path(prepared['suite_path'])
        saved=json.loads(path.read_text())
        key=next(iter(saved['runs']))
        saved['runs'][key]={'status':'preparing'}
        path.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError,'Interrupted'): run_experiment_suite(req)

    def test_compile_failures_are_isolated_but_runtime_failure_stops_dispatch(self):
        sweep={'mode':'cartesian','axes':[{'name':'event','target':{'kind':'event_value','id':'fault_on'},'values':[0,1]}]}
        req,prepared=self.prepared(self.request(sweep))
        fixture.PublicReleaseTests.enable(self,controls=True)
        items=[{'run_id':key,'action':'compile','workflow_sha256':sha256_file(Path(row['workflow_path']))} for key,row in prepared['runs'].items()]
        with patch('rtds_agent.execution.compile_project',side_effect=RuntimeError('authored compile failure')) as compile_mock:
            result=run_experiment_suite({**req,'mode':'execute','executions':items})
            self.assertEqual(compile_mock.call_count,2)
            self.assertEqual(result['status'],'failed')
        items=[{**item,'action':'runtime','request_path':str(self.data/'authored-request.json'),'request_sha256':'0'*64} for item in items]
        with patch('rtds_agent.execution.run_simulation',side_effect=RuntimeError('authored cleanup failure')) as runtime_mock:
            result=run_experiment_suite({**req,'mode':'execute','executions':items})
            self.assertEqual(runtime_mock.call_count,1)
            self.assertEqual(result['remaining_not_dispatched'],1)
            with self.assertRaisesRegex(ValueError,'Failed/interrupted'):
                run_experiment_suite({**req,'mode':'execute','executions':items})
            self.assertEqual(runtime_mock.call_count,1)

    def test_supplied_capture_assessment_retains_run_and_axis_mapping(self):
        req=self.request()
        req['specification']['criteria']['requirements']=[{'requirement_id':'R','kind':'min_max','channel_id':'voltage','units':'pu','pu_base':100,
            'sign_convention':'positive','time_unit':'s','time_basis':'simulator_time','start_time':0,'end_time':3,
            'provenance':{'kind':'user_defined','reference':'authored metrics only'}}]
        req,prepared=self.prepared(req)
        run_id,row=next(iter(prepared['runs'].items()))
        workflow=json.loads(Path(row['workflow_path']).read_text())
        artifact=self.data/'samples.json'
        data={'schema_version':'1.0','input_project_sha256':row['input_project_sha256'],'run_id':workflow['workflow_id'],'attempt_id':'supplied-a',
              'time_unit':'s','time_basis':'simulator_time','channels':[{'channel_id':'voltage','units':'pu','pu_base':100,'sign_convention':'positive','times':[0,1,2,3],'values':[1,.5,.9,1]}]}
        artifact.write_text(json.dumps(data))
        source={'data_path':str(artifact),'data_sha256':sha256_file(artifact),'input_project':row['input_project'],
                'input_project_sha256':row['input_project_sha256'],'run_id':workflow['workflow_id'],'attempt_id':'supplied-a'}
        result=run_experiment_suite({**req,'mode':'assess','captures':[{'run_id':run_id,'source':source}]})
        self.assertEqual(result['assessment_status_counts'],{'not_evaluated':1})
        self.assertEqual(result['assessments'][0]['requirement_results'][0]['metrics']['minimum'],.5)
        self.assertEqual(result['not_supplied_run_ids'],[])
        self.assertFalse(result['integration_qualified'])

    def test_compile_hash_binding_checked_inside_existing_execution_lock(self):
        from rtds_agent import execution
        req,prepared=self.prepared()
        fixture.PublicReleaseTests.enable(self)
        row=next(iter(prepared['runs'].values()))
        with patch.object(execution,'_backend') as backend:
            with self.assertRaisesRegex(ValueError,'changed before execution lock'):
                execution.compile_project(row['workflow_path'],expected_workflow_sha256='0'*64)
            backend.assert_not_called()

    def test_document_trace_binds_page_and_catches_stale_document(self):
        req=self.request()
        criterion={'requirement_id':'R1','kind':'range','channel_id':'voltage','units':'pu','pu_base':100,'sign_convention':'positive',
                   'time_unit':'s','time_basis':'simulator_time','start_time':0,'end_time':3,'lower':.5,'upper':1.1,
                   'provenance':{'kind':'cited_document','reference':'authored guide'}}
        req['specification']['criteria']['requirements']=[criterion]
        req['specification']['traceability']=[{'requirement_id':'R1','source_path':str(self.guide),'source_sha256':sha256_file(self.guide),'page':1,
                  'statement':'Synthetic bound, not a real grid code','event_ids':['fault_on'],'channel_ids':['voltage']}]
        result=run_experiment_suite(req)
        self.assertTrue(result['plan']['runs'][0]['traceability'][0]['document_hash_and_page_verified'])
        self.assertFalse(result['plan']['runs'][0]['traceability'][0]['statement_interpretation_verified'])
        self.guide.write_text('changed')
        with self.assertRaisesRegex(ValueError,'document hash'): run_experiment_suite(req)

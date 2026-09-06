"""Authored native capture fixtures with injected SDK objects; no RSCAD calls."""
import test_environment
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import test_runtime_backend as runtime_fixture
import test_public_release as public_fixture
import test_diagnostics as diagnostic_fixture
from rtds_agent.core.native_acquisition import NativeAcquisition, discover_saved_signals, native_channels, validate_grounding
from rtds_agent.core.runtime_backend import validate_runtime_test_spec, RuntimeContractError, write_raw_signal_csv
from rtds_agent.core.state_machine import sha256_file,sha256_json
from rtds_agent.result_capture import capture_rtds_results

RTX='''VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "saved-view"
COMPONENT: PLOT
NAME: Container
UUID: 100
PLOT-DATA-START
GRAPH-START: GRAPH 1: 1 CURVE
GRAPH-DATA-START
NAME: Voltage
UUID: 101
GRAPH-DATA-END
CURVE-START
GROUP: Subsystem #1|Outputs
DESC: V
COMP_ID: 1
CURVE-END
GRAPH-END
PLOT-DATA-END
COMPONENT-END:
'''
DFX='DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 1\nPARAMETERS-START:\nGain: 1\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n'


def write_project(path,text=RTX):
    with zipfile.ZipFile(path,'w') as z:z.writestr('authored.dfx',DFX);z.writestr('authored.rtx',text)


def channel(digest):
    return {'channel_id':'voltage','signal_path':'Subsystem #1|Outputs|V','units':'V','sign_convention':'positive at measured terminal',
        'time_basis':'simulator_time','metadata_evidence':{'source_sha256':digest,'locator':'Authored measurement definition and time-axis declaration'},
        'runtime_identity':{'object_uuid':101,'object_name':'Voltage','object_subpage':'Plots'}}


def specification(digest,controls=False):
    spec=runtime_fixture.runtime_control_spec() if controls else runtime_fixture.runtime_spec()
    spec['measurement_channels']=[channel(digest)]
    spec['runtime_capture'].update(acquisition_mode='native_signal_arrays',minimum_samples_per_channel=2)
    return spec


class Signal:
    def __init__(self,parent,path):
        self.parent=parent;self.unique_id=path;self.times=[0.,.1,.2];self.values=[1.,2.,1.];self.calls=[]
    def get_time_data(self):self.calls.append('time');return list(self.times)
    def get_data(self):self.calls.append('values');return list(self.values)


class Case(runtime_fixture.FakeLiveCase):
    def __init__(self,path,**kwargs):
        super().__init__(path,**kwargs)
        self.plot=type('Plot',(),{'unique_id':101,'subtab':'Runtime','subpage':'Plots'})()
        original_many=self.runtime.get_objects;original_one=self.runtime.get_object
        self.runtime.get_objects=lambda kind,name:[self.plot] if kind=='plot' and name=='Voltage' else original_many(kind,name)
        self.runtime.get_object=lambda uid:self.plot if uid==101 else original_one(uid)
        self.signal=Signal(self.runtime,'Subsystem #1|Outputs|V')
    def get_signal(self,path):return self.signal


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        runtime_fixture.RscadFxRuntimeDriverTests.setUp(self)
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=str(Path(temp.name)/'isolated.rtfx');write_project(self.path)
        self.digest=sha256_file(Path(self.path));self.case=Case(self.path)
        self.channels=[channel(self.digest)]
        self.context={'run_id':'synthetic-run','attempt_id':'synthetic-attempt','input_project_sha256':self.digest}

    def session(self):return NativeAcquisition(self.case,self.path,self.channels,self.context)

    def capture(self,writes=None):
        app=runtime_fixture.FakeLiveApp(self.case);driver=runtime_fixture.InjectedRuntimeDriver(self.config,app)
        result=driver.capture_case(working_copy=self.path,rack=1,channels=self.channels,warmup_seconds=0,
            runtime_parameter_writes=writes,native_capture={'context':self.context,'minimum_samples':2,'maximum_samples':100000})
        return result,app

    def test_saved_graph_discovery_separates_container_and_draft_id(self):
        row=discover_saved_signals(self.path,self.channels)[0]
        self.assertEqual((row['graph_id'],row['plot_container_id'],row['stored_draft_comp_id']),(101,100,1))
        self.assertFalse(row['live_target_verified'])

    def test_complete_arrays_metadata_and_recovery(self):
        before=Path(self.path).read_bytes();result,app=self.capture()
        self.assertEqual(result['errors'],[]);self.assertEqual(result['cleanup_errors'],[])
        evidence=result['acquisition'];receipt=evidence['channels']['voltage']
        self.assertTrue(evidence['capture_success']);self.assertTrue(evidence['dispatch_stopped']);self.assertTrue(evidence['resources_closed'])
        self.assertFalse(evidence['atomic_snapshot_verified']);self.assertFalse(evidence['integration_qualified'])
        self.assertEqual(evidence['recovery_order'],['stop_acquisition_dispatch','restore_controls','stop_runtime','close_owned_acquisition_handles'])
        self.assertEqual(receipt['sample_rate_hz'],10.);self.assertEqual(receipt['sample_interval_s'],.1)
        self.assertEqual(receipt['input_project_sha256'],self.digest);self.assertEqual(receipt['attempt_id'],'synthetic-attempt')
        self.assertEqual(self.case.signal.calls,['time','values','time'])
        self.assertEqual(self.case.stop_calls,1);self.assertEqual(app.disconnect_calls,1)
        self.assertEqual(Path(self.path).read_bytes(),before)

    def test_missing_metadata_wrong_base_or_time_is_unresolved(self):
        for delta in ({'sign_convention':None},{'runtime_identity':{}},{'metadata_evidence':{}},{'time_basis':'wall_clock'},{'units':'pu'},{'pu_base':True}):
            with self.subTest(delta=delta),self.assertRaises(ValueError):native_channels([{**self.channels[0],**delta}])
        with self.assertRaises(ValueError):validate_grounding(native_channels(self.channels),{'a'*64})

    def test_legacy_default_remains_and_native_metadata_survives_canonicalization(self):
        legacy=validate_runtime_test_spec(runtime_fixture.runtime_spec())
        self.assertNotIn('acquisition_mode',legacy['runtime_capture'])
        spec=specification(self.digest);plan=validate_runtime_test_spec(spec)
        self.assertEqual(plan['measurement_channels'][0]['sign_convention'],self.channels[0]['sign_convention'])
        spec['runtime_capture']['minimum_samples_per_channel']=1
        with self.assertRaises(RuntimeContractError):validate_runtime_test_spec(spec)

    def test_duplicate_saved_signal_or_graph_refused_before_connection(self):
        for text in (RTX+RTX,RTX.replace('UUID: 101','UUID: 100'),RTX.replace('COMP_ID: 1','')):
            with self.subTest(text=text[-30:]):
                write_project(self.path,text);self.context['input_project_sha256']=sha256_file(Path(self.path))
                result,app=self.capture()
                self.assertEqual(app.connect_calls,0);self.assertTrue(result['errors'])

    def test_duplicate_live_graph_candidate_never_runs(self):
        with patch.object(self.case.runtime,'get_objects',return_value=[self.case.plot,self.case.plot]):result,_=self.capture()
        self.assertFalse(result['execution']['run_started']);self.assertEqual(self.case.run_calls,0)
        self.assertTrue(result['acquisition']['resources_closed'])

    def test_wrong_live_subpage_and_signal_owner_refused(self):
        for obj,field,value in ((self.case.plot,'subpage','Wrong'),(self.case.signal,'parent',object()),(self.case.signal,'unique_id','Other')):
            with self.subTest(field=field),patch.object(obj,field,value):
                result,_=self.capture();self.assertFalse(result['execution']['run_started']);self.assertTrue(result['errors'])

    def test_changed_time_axis_is_failure_without_retry(self):
        with patch.object(self.case.signal,'get_time_data',side_effect=[[0.,.1,.2],[1.,1.1,1.2]]) as read:
            result,_=self.capture()
        self.assertEqual(read.call_count,2);self.assertFalse(result['acquisition']['capture_success'])
        self.assertEqual(result['samples'],{});self.assertTrue(result['execution']['stop_succeeded'])

    def test_empty_single_mismatched_nonfinite_bool_and_nonmonotonic_fail(self):
        for times,values in (([],[]),([0.],[1.]),([0.,.1],[1.]),([0.,.1],[1.,float('nan')]),([0.,.1],[1.,True]),([0.,0.],[1.,2.])):
            with self.subTest(times=times,values=values):
                self.case=Case(self.path);self.case.signal.times=times;self.case.signal.values=values
                result,_=self.capture();self.assertFalse(result['acquisition']['capture_success']);self.assertTrue(result['errors'])
                self.assertFalse(result['execution']['plot_csv_export_called'])

    def test_sample_limit_is_enforced(self):
        session=self.session();session.maximum=2;session.bind();session.start()
        with self.assertRaises(ValueError):session.read()

    def test_nonuniform_time_has_no_invented_sample_rate(self):
        self.case.signal.times=[0.,.1,.4]
        result,_=self.capture();row=result['acquisition']['channels']['voltage']
        self.assertIsNone(row['sample_rate_hz']);self.assertIsNone(row['sample_interval_s'])

    def test_mutated_input_is_refused_before_connection(self):
        Path(self.path).write_bytes(Path(self.path).read_bytes()+b'changed')
        result,app=self.capture();self.assertEqual(app.connect_calls,0);self.assertTrue(result['errors'])

    def test_session_cannot_restart_or_read_after_stop(self):
        session=self.session();session.bind();session.start();session.stop();session.close()
        for method in (session.start,session.read,session.bind):
            with self.assertRaises(ValueError):method()

    def test_read_failure_restores_controls_then_stops_runtime(self):
        import test_runtime_binding
        write_project(self.path,RTX+test_runtime_binding.RTX)
        self.digest=sha256_file(Path(self.path));self.context['input_project_sha256']=self.digest
        control=runtime_fixture.FakeRuntimeInput(position=1);self.case=Case(self.path,runtime_objects={603:control})
        writes=validate_runtime_test_spec(runtime_fixture.runtime_control_spec())['runtime_controls']['runtime_parameter_writes']
        with patch.object(self.case.signal,'get_data',side_effect=RuntimeError('authored read error')):result,app=self.capture(writes)
        self.assertEqual(control.position,1);self.assertTrue(result['runtime_controls']['all_restored'])
        self.assertTrue(result['acquisition']['dispatch_stopped']);self.assertTrue(result['execution']['stop_succeeded'])
        self.assertEqual(app.disconnect_calls,1)

    def test_local_stop_failure_is_distinct_and_remaining_cleanup_runs(self):
        with patch.object(NativeAcquisition,'stop',side_effect=RuntimeError('authored local stop error')):result,app=self.capture()
        self.assertTrue(result['acquisition']['capture_success']);self.assertFalse(result['acquisition']['dispatch_stopped'])
        self.assertFalse(result['acquisition']['resources_closed'])
        self.assertEqual([e['operation'] for e in result['cleanup_errors']],['stop_acquisition_dispatch','close_owned_acquisition_handles'])
        self.assertTrue(result['execution']['stop_succeeded']);self.assertEqual(app.disconnect_calls,1)

    def test_runtime_stop_failure_does_not_erase_captured_arrays(self):
        self.case.stop_fails=True;result,app=self.capture()
        self.assertTrue(result['acquisition']['capture_success']);self.assertFalse(result['execution']['stop_succeeded'])
        self.assertTrue(result['acquisition']['resources_closed']);self.assertTrue(result['cleanup_errors'])
        self.assertEqual(app.disconnect_calls,1)


class NativePreparationTests(unittest.TestCase):
    def setUp(self):
        public_fixture.PublicReleaseTests.setUp(self);write_project(self.project)
        self.spec=specification(sha256_file(self.guide))

    def prepare(self):
        from rtds_agent.execution import prepare_workflow
        return Path(prepare_workflow(str(self.project),self.spec,[str(self.guide)])['workflow_path'])

    def test_prepare_is_source_bound_read_only_and_creates_no_grant(self):
        path=self.prepare();before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('rtds_agent.execution._backend',side_effect=AssertionError('backend')):
            result=capture_rtds_results({'mode':'prepare_native','workflow_path':str(path)})
        self.assertEqual(result['status'],'prepared_native_capture_unexecuted')
        self.assertFalse(result['grant_created']);self.assertFalse(result['live_calls_made'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_ungrounded_metadata_or_ambiguous_graph_never_publishes_workflow(self):
        self.spec['measurement_channels'][0]['metadata_evidence']['source_sha256']='a'*64
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.settings.projects_root.exists())
        self.spec=specification(sha256_file(self.guide));write_project(self.project,RTX+RTX)
        with self.assertRaises(ValueError):self.prepare()
        self.assertFalse(self.settings.projects_root.exists())

    def test_stale_grounding_and_manual_override_are_refused(self):
        path=self.prepare();self.guide.write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):capture_rtds_results({'mode':'prepare_native','workflow_path':str(path)})
        with self.assertRaises(ValueError):capture_rtds_results({'mode':'workflow_native','workflow_path':str(path),'channels':[]})

    def test_saved_native_receipt_to_canonical_and_tampered_metadata(self):
        helper=diagnostic_fixture.DiagnosticTests
        workflow,artifact,marker=helper.evidence(self,stage='runtime')
        manifest=json.loads(workflow.read_text(encoding='utf-8'));project=manifest['project']
        compiled=workflow.parent/'compile.json'
        compiled.write_text(json.dumps({'schema_version':'1.0','backend':'ProductionRscadBackend','action':'compile','hashes':{
            'source_before':project['source_sha256'],'working_before':project['working_sha256']}}),encoding='utf-8')
        manifest['compile']={'succeeded':True,'artifact_sha256':'a'*64,'selected_rack':2,'result_ref':{'path':str(compiled),'sha256':sha256_file(compiled)}}
        workflow.write_text(json.dumps(manifest),encoding='utf-8')
        context={'run_id':manifest['workflow_id'],'attempt_id':'synthetic-attempt-1','input_project_sha256':project['working_sha256']}
        session=NativeAcquisition(Case(project['working_copy']),project['working_copy'],self.spec['measurement_channels'],context)
        session.bind();session.start();samples=session.read();session.stop();session.close()
        raw=workflow.parent/'raw.csv';write_raw_signal_csv(raw,samples,self.spec['measurement_channels'])
        helper.replace_result(self,workflow,artifact,marker,lambda value:value.update(compiled_artifact={'sha256':'a'*64},
            raw_data={'path':str(raw),'sha256':sha256_file(raw)},safe_completion=False,native_acquisition=session.evidence))
        request={'mode':'workflow_native','workflow_path':str(workflow)}
        result=capture_rtds_results(request);data=json.loads(Path(result['source']['data_path']).read_text(encoding='utf-8'))
        self.assertFalse(data['acquisition_evidence']['safe_completion'])
        self.assertEqual(data['channels'][0]['runtime_identity']['object_uuid'],101)
        self.assertEqual(data['channels'][0]['attempt_id'],data['attempt_id'])
        self.assertEqual(data['channels'][0]['sample_interval_s'],.1)
        with self.assertRaises(ValueError):
            capture_rtds_results({'mode':'workflow','workflow_path':str(workflow),'channels':[{k:v for k,v in self.spec['measurement_channels'][0].items() if k in {'channel_id','signal_path','units','sign_convention'}}],'time_basis':'simulator_time'})
        for field,value in (('units','pu'),('sample_interval_s',99),('sample_rate_hz',99),('binding',{}),('samples_sha256','0'*64)):
            with self.subTest(field=field):
                import copy
                receipt=copy.deepcopy(session.evidence);receipt['channels']['voltage'][field]=value
                helper.replace_result(self,workflow,artifact,marker,lambda result:result.update(native_acquisition=receipt))
                with self.assertRaises(ValueError):capture_rtds_results(request)

    def test_public_runtime_binds_actual_attempt_and_consumes_grant_once(self):
        from rtds_agent import execution
        from rtds_agent.core.mock_backend import MockBackend
        class RecordingBackend(MockBackend):
            def run_runtime(self,*,acquisition_context,**kwargs):
                self.context=acquisition_context
                return super().run_runtime(**kwargs)
        path=str(self.prepare());public_fixture.PublicReleaseTests.enable(self)
        backend=RecordingBackend(available_racks=[2],selected_rack=2)
        with patch.object(execution,'verify_release',return_value={'synthetic':True}), patch.object(execution,'inspect_installation',return_value={'synthetic':True}), patch.object(execution,'_backend',return_value=backend):
            execution.compile_project(path)
            request=execution.prepare_simulation_run(path)
            result=execution.run_simulation(path,request['request_path'],request['request_sha256'])
            self.assertEqual(result['state'],'runtime_completed')
            manifest=json.loads(Path(path).read_text(encoding='utf-8'))
            self.assertEqual(backend.context,{'run_id':manifest['workflow_id'],'attempt_id':result['attempt']['attempt_id']})
            with self.assertRaises(ValueError):execution.run_simulation(path,request['request_path'],request['request_sha256'])
        self.assertTrue(all(row['status']=='consumed' for row in manifest['approvals']))

    def test_native_public_execution_remains_inactive_by_default(self):
        from rtds_agent import execution
        path=str(self.prepare())
        with patch.object(execution,'_backend') as backend:
            with self.assertRaises(ValueError):execution.run_simulation(path,str(self.root/'absent-grant.json'),'0'*64)
            backend.assert_not_called()

    def test_native_dsl_preserves_mode_and_channel_evidence(self):
        from rtds_agent.core.experiment_spec import compile_spec
        spec={'test_id':'capture','controls':[],'events':[],'initial_conditions':[],
            'capture_after_seconds':0,'minimum_samples_per_channel':2}
        spec.update(acquisition_mode='native_signal_arrays',channels=self.spec['measurement_channels'])
        result=compile_spec(spec)
        self.assertEqual(result['runtime_capture']['acquisition_mode'],'native_signal_arrays')
        self.assertEqual(result['measurement_channels'],self.spec['measurement_channels'])


class NativeProductionTests(unittest.TestCase):
    def make_backend(self):
        helper=runtime_fixture.ProductionRuntimeBackendTests('test_happy_path_writes_hash_bound_raw_evidence')
        helper.setUp();self.addCleanup(helper.doCleanups)
        write_project(helper.working);helper.source.write_bytes(helper.working.read_bytes())
        spec=specification(sha256_file(helper.source))
        with patch.object(runtime_fixture,'runtime_spec',return_value=spec):helper.workflow=helper._workflow()
        helper.workflow.manifest['workflow_id']=helper.run_dir.name
        helper.case=Case(str(helper.working));helper.app=runtime_fixture.FakeLiveApp(helper.case)
        helper.runtime_driver=runtime_fixture.InjectedRuntimeDriver(helper.config,helper.app)
        helper.backend=helper._backend()
        helper.context={'run_id':helper.run_dir.name,'attempt_id':'f'*32}
        return helper

    def test_full_native_backend_binds_raw_receipts_and_separate_safe_completion(self):
        h=self.make_backend();result=h._approve().execute_runtime(acquisition_context=h.context)
        self.assertTrue(result['safe_completion'])
        manifest=h._latest_manifest();receipt=manifest['native_acquisition']
        self.assertEqual(receipt['context']['attempt_id'],h.context['attempt_id'])
        self.assertTrue(receipt['capture_success']);self.assertEqual(receipt['state'],'closed')
        self.assertEqual(receipt['recovery']['stop_runtime'],'succeeded')
        self.assertTrue(Path(manifest['raw_data']['path']).is_file())
        self.assertTrue(all(manifest['hashes']['integrity'].values()))

    def test_context_and_grounding_refused_before_rack_discovery(self):
        h=self.make_backend();orchestrator=h._approve()
        with self.assertRaises(ValueError):orchestrator.execute_runtime()
        self.assertEqual(h.backend.call_log,[])
        h.workflow.manifest['test_spec']['measurement_channels'][0]['metadata_evidence']['source_sha256']='0'*64
        with self.assertRaises(ValueError):orchestrator.execute_runtime(acquisition_context=h.context)
        self.assertEqual(h.backend.call_log,[])

    def test_sample_metadata_and_binding_tampering_fail_closed(self):
        for field,value in (('units','A'),('sample_count',99),('samples_sha256','0'*64),('sample_rate_hz',99),('binding',{})):
            with self.subTest(field=field):
                h=self.make_backend();original=h.runtime_driver.capture_case
                def tamper(**kwargs):
                    result=original(**kwargs);result['acquisition']['channels']['voltage'][field]=value;return result
                with patch.object(h.runtime_driver,'capture_case',side_effect=tamper):result=h._approve().execute_runtime(acquisition_context=h.context)
                self.assertFalse(result['safe_completion']);self.assertTrue(h._latest_manifest()['errors'])

    def test_capture_success_does_not_override_runtime_stop_failure(self):
        h=self.make_backend();h.case.stop_fails=True
        result=h._approve().execute_runtime(acquisition_context=h.context)
        manifest=h._latest_manifest()
        self.assertTrue(manifest['native_acquisition']['capture_success'])
        self.assertFalse(result['safe_completion']);self.assertTrue(manifest['cleanup_errors'])
        self.assertEqual(manifest['native_acquisition']['recovery']['stop_runtime'],'unconfirmed')

    def test_acquisition_stop_or_resource_failure_cannot_pass_backend(self):
        for method in ('stop','close'):
            with self.subTest(method=method):
                h=self.make_backend()
                with patch.object(NativeAcquisition,method,side_effect=RuntimeError('authored cleanup failure')):
                    result=h._approve().execute_runtime(acquisition_context=h.context)
                self.assertFalse(result['safe_completion']);self.assertEqual(h.app.disconnect_calls,1)


if __name__=='__main__':unittest.main()

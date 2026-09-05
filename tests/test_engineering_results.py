"""Analytical waveforms and native-format authored CSV; no simulator calls."""
import test_environment
import copy
import json
import math
import unittest
from pathlib import Path
import test_public_release as fixture
from rtds_agent.core.runtime_backend import write_raw_signal_csv
from rtds_agent.result_capture import capture_rtds_results
from rtds_agent.assessment import evaluate_results
from rtds_agent.core.state_machine import sha256_file,sha256_json
from rtds_agent.core.power_metrics import compute_metric


class EngineeringResultTests(unittest.TestCase):
    setUp=fixture.PublicReleaseTests.setUp

    def capture(self,times=None,values=None):
        path=self.data/'raw.csv'
        channel={'channel_id':'voltage','signal_path':'Subsystem #1|BUS|V','units':'pu'}
        write_raw_signal_csv(path,{'voltage':{'times':times or [0,1,2,3], 'values':values or [1,.5,.9,1]}},[channel])
        self.request={'mode':'supplied_csv','source':{'data_path':str(path),'data_sha256':sha256_file(path),
           'input_project':str(self.project),'input_project_sha256':sha256_file(self.project),'run_id':'authored','attempt_id':'a'},
           'time_basis':'simulator_time','channels':[{**channel,'sign_convention':'positive','pu_base':100}]}
        return capture_rtds_results(self.request)

    def metric(self,name,times,values,options=None,units='pu'):
        req={'metric':name,'metric_options':options or {},'start_time':times[0],'end_time':times[-1], 'units':units}
        return compute_metric(req,times,values)

    def test_csv_to_canonical_then_evaluate_and_idempotent(self):
        result=self.capture()
        self.assertEqual(capture_rtds_results(self.request),result)
        data=json.loads(Path(result['source']['data_path']).read_text())
        self.assertEqual(data['channels'][0]['sample_rate_hz'],1)
        req={'requirement_id':'nadir','kind':'power_metric','metric':'voltage_nadir','metric_options':{},
             'metric_acceptance':{'lower':.4,'upper':1,'units':'pu'},'channel_id':'voltage','units':'pu','pu_base':100,
             'sign_convention':'positive','time_unit':'s','time_basis':'simulator_time','start_time':0,'end_time':3,
             'provenance':{'kind':'user_defined','reference':'authored threshold'}}
        spec={'schema_version':'1.0','requirements':[req]}
        evaluation=evaluate_results({'source':result['source'],'specification':spec,'specification_sha256':sha256_json(spec)})
        self.assertEqual(evaluation['status'],'passed')
        self.assertEqual(evaluation['results'][0]['metrics']['value'],.5)
        self.assertEqual(evaluation['engineering_verdict'],'not_evaluated')

    def test_csv_rejects_stale_duplicate_metadata_units_and_nonfinite(self):
        self.capture()
        for delta in ({'source':{**self.request['source'],'data_sha256':'0'*64}},
                      {'channels':self.request['channels']*2},
                      {'channels':[{**self.request['channels'][0],'units':'V'}]}):
            with self.assertRaises(ValueError): capture_rtds_results({**self.request,**delta})
        path=Path(self.request['source']['data_path'])
        path.write_text(path.read_text().replace('0.5','nan'))
        self.request['source']['data_sha256']=sha256_file(path)
        with self.assertRaisesRegex(ValueError,'non_finite'): capture_rtds_results(self.request)

    def test_saved_workflow_missing_evidence_does_not_call_live_backend(self):
        from unittest.mock import patch
        self.capture()
        with patch('rtds_agent.execution._backend') as backend:
            with self.assertRaises(ValueError): capture_rtds_results({'mode':'workflow','workflow_path':str(self.data/'missing.json'),'channels':self.request['channels'],'time_basis':'simulator_time'})
            backend.assert_not_called()

    def test_saved_native_workflow_acquisition_and_tamper(self):
        import test_diagnostics
        helper=test_diagnostics.DiagnosticTests
        self.prepare=lambda: Path(fixture.PublicReleaseTests.prepare(self))
        workflow,artifact,marker=helper.evidence(self,stage='runtime')
        manifest=json.loads(workflow.read_text())
        compiled=workflow.parent/'authored-compile.json'
        compiled.write_text(json.dumps({'schema_version':'1.0','backend':'ProductionRscadBackend','action':'compile','hashes':{
            'source_before':manifest['project']['source_sha256'],'working_before':manifest['project']['working_sha256']}}))
        manifest['compile']={'succeeded':True,'artifact_sha256':'a'*64,'selected_rack':2,'result_ref':{'path':str(compiled),'sha256':sha256_file(compiled)}}
        workflow.write_text(json.dumps(manifest))
        csv_path=workflow.parent/'raw.csv'
        channel={'channel_id':'v','signal_path':'authored|v','units':'V'}
        write_raw_signal_csv(csv_path,{'v':{'times':[0,1,2],'values':[1,2,1]}},[channel])
        helper.replace_result(self,workflow,artifact,marker,lambda value:value.update(compiled_artifact={'sha256':'a'*64},
            raw_data={'path':str(csv_path),'sha256':sha256_file(csv_path)},safe_completion=True))
        request={'mode':'workflow','workflow_path':str(workflow),'channels':[{**channel,'sign_convention':'positive'}],'time_basis':'simulator_time'}
        result=capture_rtds_results(request)
        self.assertEqual(result['source']['run_id'],manifest['workflow_id'])
        self.assertEqual(result['source']['attempt_id'],'synthetic-attempt-1')
        self.assertEqual(result['acquisition_evidence']['kind'],'saved_runtime_backend_artifact')
        csv_path.write_text(csv_path.read_text()+'\n')
        with self.assertRaises(ValueError): capture_rtds_results(request)

    def test_extrema_rocof_and_overshoot(self):
        t=[0,1,2,3]; y=[1,.5,1.2,1]
        expected={'voltage_nadir':.5,'frequency_nadir':.5,'reactive_power_peak':1.2,'reactive_current_injection':1.2}
        for name,value in expected.items():
            self.assertAlmostEqual(self.metric(name,t,y)[0]['value'],value)
            self.assertEqual(self.metric(name,t,y)[1],'not_evaluated')
        self.assertAlmostEqual(self.metric('overshoot',t,y,{'baseline':1})[0]['value'],.2)
        self.assertAlmostEqual(self.metric('RoCoF',t,[50,49,51,50],units='Hz')[0]['value'],2)

    def test_recovery_settling_and_left_hold_duration(self):
        for name in ('voltage_recovery_time','active_power_recovery','settling_time'):
            result=self.metric(name,[0,1,2,3,4],[1,.4,.91,.99,1],{'lower':.9,'upper':1.1,'event_time':1})
            self.assertEqual(result[0]['value'],1)
        value=self.metric('current_limit_duration',[0,1,3,4],[0,2,2,0],{'threshold':1})[0]['value']
        self.assertEqual(value,3)
        with self.assertRaisesRegex(ValueError,'not observed'): self.metric('settling_time',[0,1,2],[1,1,2],{'lower':.9,'upper':1.1,'event_time':0})

    def test_oscillation_and_damping_against_analytic_signal(self):
        t=[i*.001 for i in range(3001)]
        frequency=2; decay=.5
        y=[math.exp(-decay*x)*math.sin(2*math.pi*frequency*x) for x in t]
        self.assertAlmostEqual(self.metric('oscillation_frequency',t,y,{'baseline':0})[0]['value'],frequency,places=5)
        expected=decay/math.sqrt((2*math.pi*frequency)**2+decay**2)
        self.assertAlmostEqual(self.metric('damping_ratio',t,y,{'baseline':0})[0]['value'],expected,places=5)

    def test_thd_coherent_harmonics_and_reject_bad_sampling(self):
        t=[i/10000 for i in range(1000)]
        y=[math.sin(2*math.pi*50*x)+.1*math.sin(2*math.pi*150*x) for x in t]
        options={'fundamental_hz':50,'harmonics':10}
        self.assertAlmostEqual(self.metric('THD',t,y,options,units='V')[0]['value'],10,places=8)
        t[1]+=.00001
        with self.assertRaisesRegex(ValueError,'uniform'): self.metric('THD',t,y,options,units='V')
        with self.assertRaisesRegex(ValueError,'whole'): self.metric('THD',[0,.01,.02],[1,0,-1],{'fundamental_hz':1,'harmonics':2},units='V')

    def test_wrapped_angle_and_missing_acceptance(self):
        req={'metric':'angle_separation','metric_options':{'other_channel_id':'b'},'units':'deg','start_time':0,'end_time':2}
        result,status=compute_metric(req,[0,1,2],[179,10,20],[-179,15,30])
        self.assertEqual(result['value'],10)
        self.assertEqual(status,'not_evaluated')
        req['metric_acceptance']={'lower':0,'upper':20,'units':'rad'}
        with self.assertRaisesRegex(ValueError,'units mismatch'): compute_metric(req,[0,1,2],[179,10,20],[-179,15,30])

"""Synthetic exact scope and cleanup regression; never connects to RSCAD."""
import test_environment
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import test_runtime_backend as fixture
from rtds_agent.core.runtime_binding import bind_live_control
from rtds_agent.core.runtime_backend import RuntimeContractError, runtime_input_objects, validate_runtime_test_spec
from rtds_agent.core.state_machine import sha256_file

RTX='COMPONENT: TAGGED_V2.2_SWITCH\nNAME: LockFree\nGROUP: (NONE)\nGROUP: Subsystem #1|Machines|BUS39x1\nDESC: LockFree\nUUID: 603\nCOMPONENT-END:\n'


class RuntimeBindingTests(unittest.TestCase):
    def setUp(self):
        fixture.RscadFxRuntimeDriverTests.setUp(self)
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.path=str(Path(temporary.name)/'isolated.rtfx')
        self.write_layout()
        self.digest=sha256_file(Path(self.path))
        self.control=fixture.FakeRuntimeInput(position=1)
        self.case=fixture.FakeLiveCase(self.path,runtime_objects={603:self.control})
        self.action=validate_runtime_test_spec(fixture.runtime_control_spec())['runtime_controls']['runtime_parameter_writes'][0]

    def write_layout(self,text=RTX):
        with zipfile.ZipFile(self.path,'w') as z:z.writestr('isolated.rtx',text)

    def bind(self):return bind_live_control(self.case,self.path,self.digest,self.action)

    def capture(self):
        return fixture.RscadFxRuntimeDriverTests._capture(self,self.case,writes=[self.action])

    def test_exact_current_lookup_and_saved_group_header(self):
        self.assertEqual(runtime_input_objects(self.path)[603]['object_group'],self.action['object_group'])
        handle,receipt=self.bind()
        self.assertIs(handle,self.control);self.assertTrue(receipt['identity_verified'])
        self.assertFalse(receipt['value_verified'])
        result,app=self.capture()
        self.assertTrue(result['runtime_controls']['write_bindings'][0]['value_verified'])
        self.assertEqual(self.control.position,1)
        self.assertTrue(result['runtime_controls']['all_restored'])
        self.assertEqual(app.disconnect_calls,1)

    def test_duplicate_candidates_block_before_run_or_write(self):
        with patch.object(self.case.runtime,'get_objects',return_value=[self.control,copy.copy(self.control)]):
            with self.assertRaisesRegex(ValueError,'ambiguous'):self.bind()
            result,app=self.capture()
        self.assertEqual(self.case.run_calls,0);self.assertEqual(self.control.position,1)
        self.assertFalse(result['safety']['runtime_parameter_write_called'])
        self.assertTrue(result['errors']);self.assertEqual(app.disconnect_calls,1)

    def test_wrong_page_subtab_id_and_empty_lookup_refused(self):
        for attr,value in (('subpage','Other'),('subtab','Draft'),('unique_id',999),('unique_id',True)):
            with self.subTest(attr=attr,value=value),patch.object(self.control,attr,value):
                with self.assertRaises(ValueError):self.bind()
        for field in ('object_type','object_name'):
            with patch.dict(self.action,{field:'missing'}),self.assertRaises(ValueError):self.bind()

    def test_second_exact_lookup_must_agree(self):
        other=copy.copy(self.control);other.subpage='Changed'
        with patch.object(self.case.runtime,'get_object',return_value=other),self.assertRaises(ValueError):self.bind()

    def test_case_path_or_file_hash_change_refused(self):
        with patch.object(self.case,'file',self.path+'.other'),self.assertRaises(ValueError):self.bind()
        self.write_layout(RTX+'\n')
        with self.assertRaisesRegex(ValueError,'hash changed'):self.bind()

    def test_expected_initial_mismatch_prevents_write(self):
        self.control.position=0
        self.action['phase']='before_run'
        result,_=self.capture()
        self.assertEqual(self.case.run_calls,0)
        self.assertFalse(result['safety']['runtime_parameter_write_called'])
        self.assertTrue(any('initial value mismatch' in e['message'] for e in result['errors']))

    def test_restoration_rebinds_and_never_writes_changed_page(self):
        original=self.case.update_plots
        def change_page():
            original();self.control.subpage='Changed after write'
        with patch.object(self.case,'update_plots',side_effect=change_page):result,app=self.capture()
        self.assertEqual(result['runtime_controls']['applied'],1)
        self.assertEqual(result['runtime_controls']['restored'],0)
        self.assertFalse(result['runtime_controls']['all_restored'])
        self.assertEqual(self.control.position,self.action['value'])
        self.assertTrue(any('restore_runtime_input' in e['operation'] for e in result['cleanup_errors']))
        self.assertEqual(self.case.stop_calls,1);self.assertEqual(app.disconnect_calls,1)

    def test_changed_remote_case_blocks_restore_and_stop(self):
        app=fixture.FakeLiveApp(self.case)
        driver=fixture.InjectedRuntimeDriver(self.config,app)
        original=app._get_case_named
        def replace_case():
            app._get_case_named=lambda file,open_file: 999
        self.case.update_plots=replace_case
        result=driver.capture_case(working_copy=self.path,rack=1,
            channels=fixture.runtime_spec()['measurement_channels'],warmup_seconds=0,
            runtime_parameter_writes=[self.action])
        self.assertEqual(result['runtime_controls']['applied'],1)
        self.assertEqual(result['runtime_controls']['restored'],0)
        self.assertEqual(self.control.position,self.action['value'])
        self.assertEqual(self.case.stop_calls,0)
        self.assertEqual(self.case.close_calls,0)
        self.assertTrue(result['cleanup_errors'])
        self.assertEqual(app.disconnect_calls,1)

    def test_remote_case_change_before_write_never_changes_control(self):
        app=fixture.FakeLiveApp(self.case)
        driver=fixture.InjectedRuntimeDriver(self.config,app)
        original_run=self.case.run
        def replace_after_start():
            original_run()
            app._get_case_named=lambda file,open_file: 999
        self.case.run=replace_after_start
        result=driver.capture_case(working_copy=self.path,rack=1,
            channels=fixture.runtime_spec()['measurement_channels'],warmup_seconds=0,
            runtime_parameter_writes=[self.action])
        self.assertEqual(result['runtime_controls']['applied'],0)
        self.assertEqual(self.control.position,1)
        self.assertFalse(result['safety']['runtime_parameter_write_called'])
        self.assertEqual(self.case.stop_calls,0)
        self.assertEqual(self.case.close_calls,0)
        self.assertTrue(result['cleanup_errors'])

    def test_missing_subpage_contract_rejected_before_connection(self):
        self.action.pop('object_subpage')
        result,app=self.capture()
        self.assertEqual(app.connect_calls,0);self.assertEqual(self.case.run_calls,0)
        self.assertTrue(result['errors'])
        spec=fixture.runtime_control_spec()
        spec['runtime_controls']['runtime_parameter_writes'][0].pop('object_subpage')
        with self.assertRaises(RuntimeContractError):validate_runtime_test_spec(spec)

    def test_legacy_duplicate_saved_id_rejected_before_connection(self):
        self.write_layout(RTX+RTX.replace('TAGGED_V2.2_',''))
        with self.assertRaises(RuntimeContractError):runtime_input_objects(self.path)
        result,app=self.capture()
        self.assertEqual(app.connect_calls,0);self.assertTrue(result['errors'])

    def test_multiple_signal_references_refused_and_button_alias_supported(self):
        self.write_layout(RTX.replace('UUID: 603','GROUP: Extra\nDESC: another\nUUID: 603'))
        with self.assertRaises(RuntimeContractError):runtime_input_objects(self.path)
        self.write_layout(RTX.replace('SWITCH','PUSHBUTTON'))
        self.assertEqual(runtime_input_objects(self.path)[603]['object_type'],'button')


if __name__=='__main__':unittest.main()

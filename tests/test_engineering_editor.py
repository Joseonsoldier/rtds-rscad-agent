"""Authored simple DFX records; never qualifies vendor editing or a rack."""
import test_environment
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
import test_public_release as fixture
from rtds_agent.core.component_catalog import search_component_catalog, get_component_schema
from rtds_agent.core.component_policy import read_component_policy
from rtds_agent.model_editor import edit_rscad_model
from rtds_agent.model_check import check_rscad_model
from rtds_agent.project_tools import inspect_rscad_project, _document, list_rscad_projects
from rtds_agent.safety import sha256_file

GAIN_DEF = '''PARAMETERS:
 Gain "Gain" "pu" REAL 1 0 10
 Name "Name" "" NAME gain
 Mode "Mode" "Off;On" TOGGLE Off
NODES:
 #IF Mode=0
 OUT 1 0 OUTPUT REAL
 #ELSE
 OUT 2 0 OUTPUT REAL
 #END
'''
WIRE_DEF = 'PARAMETERS:\n' + ''.join(f' {k} "Coordinate" "pixels" INTEGER 0 -1000000 1000000\n' for k in ('x1','y1','x2','y2')) + 'NODES:\n'


def block(kind,identifier,parameters,location=(0,0)):
    return f'COMPONENT_TYPE={kind}\n{location[0]} {location[1]} 0 0 {len(parameters)}\nPARAMETERS-START:\n'+''.join(f'{k}: {v}\n' for k,v in parameters.items())+f'PARAMETERS-END:\nUUID: {identifier}\n'


class EngineeringEditorTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        (self.defs/'synthetic_gain').write_text(GAIN_DEF,encoding='utf-8')
        (self.defs/'WIRE').write_text(WIRE_DEF,encoding='utf-8')
        self.dfx = 'DRAFT 1\nSUBSYSTEM-START:\n'+block('synthetic_gain',1,{'Gain':'1','Name':'gain','Mode':'Off'})+block('WIRE',2,dict(x1='32',y1='0',x2='96',y2='0'))+'SUBSYSTEM-END:\n'
        self.write()
        self.policy = self.sources/'rtds-component-policy.json'
        self.policy.write_text(json.dumps({'allowed_components':['synthetic_gain','WIRE'],'denied_components':[],
           'allowed_parameters':{'synthetic_gain':['Gain','Name','Mode'],'WIRE':['x1','y1','x2','y2']},'structural_edits':True}),encoding='utf-8')
        self.identity = dict(component_id=1,context='subsystem:0',component_type='synthetic_gain')

    def write(self, extra=False):
        with zipfile.ZipFile(self.project,'w') as z:
            z.writestr('synthetic.dfx',self.dfx)
            if extra: z.writestr('synthetic.rtx','opaque runtime')
            z.comment=b'preserved'

    def request(self, operations):
        overview=inspect_rscad_project(str(self.project))
        self.assertEqual(overview['component_policy']['sha256'],sha256_file(self.policy))
        return dict(source_project=str(self.project),source_sha256=sha256_file(self.project),
                    snapshot_id=overview['snapshot_id'], policy_sha256=overview['component_policy']['sha256'],
                    project_label='engineering',mode='preview',operations=operations)

    def apply(self,ops):
        request=self.request(ops)
        before=self.project.read_bytes()
        preview=edit_rscad_model(request)
        self.assertEqual(self.project.read_bytes(),before)
        self.assertEqual(list((self.data/'.editor-staging').iterdir()),[])
        result=edit_rscad_model({**request,'mode':'apply','preview_id':preview['preview_id']})
        self.assertEqual(self.project.read_bytes(),before)
        self.assertFalse(result['integration_qualified'])
        self.assertEqual(sha256_file(Path(result['working_project'])),preview['candidate_sha256'])
        return result

    def test_catalog_schema_selector_and_snapshot(self):
        result=search_component_catalog('synthetic')
        schema=get_component_schema('synthetic_gain',parameters={'Mode':'On'},snapshot_id=result['catalog_snapshot_id'])
        self.assertEqual(schema['active_nodes'][0]['local'],[64,0])
        self.assertEqual(schema['selectors'],['Mode'])
        self.assertEqual(schema['observed_rscad_version'],'unknown')
        (self.defs/'new').write_text('NODES:\n')
        with self.assertRaises(ValueError): get_component_schema('synthetic_gain',snapshot_id=result['catalog_snapshot_id'])

    def test_catalog_duplicate_name_needs_library_identity(self):
        folder=self.defs/'second'; folder.mkdir()
        (folder/'synthetic_gain').write_text(GAIN_DEF)
        self.assertEqual(get_component_schema('synthetic_gain')['status'],'ambiguous')
        self.assertEqual(get_component_schema('synthetic_gain','second/synthetic_gain')['status'],'resolved')
        self.assertEqual(search_component_catalog('invented')['status'],'unresolved')

    def test_numeric_selector_string_move_roundtrip(self):
        ops=[{**self.identity,'op':'set_parameter','parameter':'Gain','expected_old_value':'1','new_value':'2'},
             {**self.identity,'op':'set_selector','parameter':'Mode','expected_old_value':'Off','new_value':'On'},
             {**self.identity,'op':'rename_component','parameter':'Name','expected_old_value':'gain','new_value':'new gain'},
             {**self.identity,'op':'move_component','expected_location':[0,0],'location':[64,32]}]
        result=self.apply(ops)
        row=_document(result['working_project'])[2]['components'][0]
        self.assertEqual(row['parameters'],{'Gain':'2','Name':'new gain','Mode':'On'})
        self.assertEqual(row['location'],[64,32])
        self.assertTrue(list_rscad_projects()['projects'])

    def test_insert_clone_createwire_remove_and_rewire(self):
        for name in ('insert_component','clone_component'):
            result=self.apply([{**self.identity,'op':name,'new_component_id':3,'location':[128,64],'parameters':{'Name':'copy'}}])
            self.assertEqual(len(_document(result['working_project'])[2]['components']),3)
        wire=dict(component_id=2,context='subsystem:0',component_type='WIRE')
        result=self.apply([{**wire,'op':'create_wire','new_component_id':4,'start':[128,0],'end':[192,0]}])
        self.assertEqual(_document(result['working_project'])[2]['components'][2]['uuid'],4)
        result=self.apply([{**wire,'op':'rewire','expected_parameters':dict(x1='32',y1='0',x2='96',y2='0'),'start':[32,0],'end':[128,0]}])
        self.assertEqual(_document(result['working_project'])[2]['components'][1]['parameters']['x2'],'128')
        for identity,op in ((self.identity,'remove_component'),(wire,'remove_wire')):
            result=self.apply([{**identity,'op':op}])
            self.assertEqual(len(_document(result['working_project'])[2]['components']),1)

    def test_opaque_archive_preserved_and_removal_rejected(self):
        self.write(extra=True)
        result=self.apply([{**self.identity,'op':'set_string','parameter':'Name','expected_old_value':'gain','new_value':'label'}])
        with zipfile.ZipFile(result['working_project']) as z:
            self.assertEqual(z.read('synthetic.rtx'),b'opaque runtime')
            self.assertEqual(z.comment,b'preserved')
        with self.assertRaisesRegex(ValueError,'opaque'): edit_rscad_model(self.request([{**self.identity,'op':'remove_component'}]))

    def test_stale_policy_preview_and_inputs_rejected(self):
        req=self.request([{**self.identity,'op':'set_selector','parameter':'Mode','expected_old_value':'Off','new_value':'On'}])
        preview=edit_rscad_model(req)
        with self.assertRaisesRegex(ValueError,'preview'): edit_rscad_model({**req,'mode':'apply','preview_id':'0'*64})
        self.policy.write_text(self.policy.read_text()+'\n')
        with self.assertRaises(ValueError): edit_rscad_model({**req,'mode':'apply','preview_id':preview['preview_id']})
        self.assertFalse((self.data/'projects/model_edits').exists())

    def test_default_deny_denied_type_and_bad_target(self):
        self.policy.unlink()
        self.assertFalse(read_component_policy(self.project)['policy']['structural_edits'])
        self.policy.write_text(json.dumps({'allowed_components':['synthetic_gain'],'denied_components':['synthetic_gain'],'allowed_parameters':{},'structural_edits':True}))
        with self.assertRaisesRegex(ValueError,'denies'): edit_rscad_model(self.request([{**self.identity,'op':'move_component','expected_location':[0,0],'location':[1,2]}]))

    def test_invalid_request_and_atomic_late_failure(self):
        base={**self.identity,'op':'set_parameter','parameter':'Gain','expected_old_value':'1','new_value':'2'}
        for changed in ({'component_id':True},{'new_value':'NaN'},{'new_value':'11'},{'expected_old_value':'wrong'},{'unexpected':1}):
            with self.assertRaises(ValueError): edit_rscad_model(self.request([{**base,**changed}]))
        before=self.project.read_bytes()
        with self.assertRaises(ValueError): edit_rscad_model(self.request([base,{**self.identity,'op':'set_selector','parameter':'Mode','expected_old_value':'wrong','new_value':'On'}]))
        self.assertEqual(before,self.project.read_bytes())
        self.assertFalse((self.data/'projects/model_edits').exists())

    def test_model_check_explicit_units_and_no_engineering_pass(self):
        field=dict(context='subsystem:0',component_id=1,parameter='Gain',units='pu')
        result=check_rscad_model(str(self.project),electrical_rules=[dict(rule_id='positive',kind='positive',field=field,provenance='authored requirement')])
        self.assertEqual(result['electrical_rules'][0]['status'],'passed')
        self.assertEqual(result['engineering_verdict'],'not_evaluated')
        result=check_rscad_model(str(self.project),electrical_rules=[dict(rule_id='units',kind='positive',field={**field,'units':'kV'},provenance='authored requirement')])
        self.assertEqual(result['electrical_rules'][0]['status'],'inconclusive')

    def test_duplicate_identity_and_parameter_violation(self):
        self.dfx=self.dfx.replace('UUID: 2','UUID: 1').replace('Gain: 1','Gain: 100')
        self.write()
        findings=check_rscad_model(str(self.project))['findings']
        self.assertIn('duplicate_identity',{f['finding'] for f in findings})
        self.assertIn('parameter_value_invalid',{f['finding'] for f in findings})

    def test_static_ir_and_safe_deterministic_diagram(self):
        from rtds_agent.core.model_ir import model_ir,mermaid_overview
        document=_document(str(self.project))[2]
        self.assertEqual(model_ir(document)['ir_sha256'],model_ir(document)['ir_sha256'])
        document['components'][0]['component_type']='x"] click c0 "javascript:alert(1)'
        diagram=mermaid_overview(document)
        self.assertNotIn('"] click',diagram)
        self.assertTrue(diagram.startswith('flowchart LR'))

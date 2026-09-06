"""Authored saved Runtime examples; no vendor format or live qualification."""
import test_environment
import builtins
import copy
import json
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch
import zipfile
import jsonschema
import test_public_release as fixture
from rtds_agent import runtime_layout
from rtds_agent.core.runtime_parser import parse_runtime_layout
from rtds_agent.core.runtime_ir import runtime_ir

PAGE = 'VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "saved-page" VIEW-CANVAS-SIZE:3000,2000\n'
CONTROL = '''COMPONENT: TAGGED_V2.2_SWITCH
NAME: Fault
UUID: 11
GROUP: (NONE)
GROUP: Authored|Inputs
DESC: SW
COMP_ID: 1
UNITS: state
POSITION: 1
POSITION 1 DATA: 0.0 TEXT_OVERRIDE: "Off"
COMPONENT-END:
'''
PLOT = '''COMPONENT: PLOT
NAME: Waveforms
UUID: 20
PLOT-DATA-START
GRAPH-START: GRAPH 1: 1 CURVE
GRAPH-DATA-START
NAME: Trace
UUID: 21
Y MIN: NaN
GRAPH-DATA-END
GUI-DATA-START
UUID: 999
GUI-DATA-END
CURVE-START
GROUP: Authored|Outputs
DESC: Voltage
COMP_ID: 1
LABEL: supplied label
CURVE-END
GRAPH-END
PLOT-DATA-END
COMPONENT-END:
'''
LAYOUT = PAGE + 'COMPONENT: FRAME\nNAME: Controls\nUUID: 10\n' + CONTROL + 'COMPONENT-END:\n' + PLOT
DOCUMENT = {"components":[{"uuid":1,"context":"subsystem:0","component_type":"authored_gain"}],
            "snapshot_id":"a"*64,"source":{"rtfx_sha256":"b"*64}}


def make_ir(text=LAYOUT, document=None):
    return runtime_ir(parse_runtime_layout(text), document or DOCUMENT,
                      snapshot_id="c"*64,member="authored.rtx",member_sha256="d"*64)


class RuntimeIrTests(unittest.TestCase):
    def test_six_entities_schema_determinism_and_explicit_reference(self):
        text=LAYOUT+'COMPONENT: METER\nNAME: V\nUUID: 30\nGROUP: A\nDESC: V\nCOMP_ID: 1\nCOMPONENT-END:\n'
        ir=make_ir(text)
        schema=json.loads((Path(runtime_layout.__file__).parent/'schemas/runtime_ir.schema.json').read_text())
        jsonschema.Draft202012Validator(schema).validate(ir)
        self.assertEqual(ir,make_ir(text))
        self.assertEqual([len(ir[k]) for k in ('pages','groups','controls','displays','plots','signal_references')],[1,1,1,1,1,3])
        control=ir['controls'][0]
        self.assertEqual(control['parent_key'],ir['groups'][0]['key'])
        self.assertIn(control['key'],ir['groups'][0]['children'])
        self.assertEqual(control['component_id'],11)
        self.assertEqual(ir['signal_references'][0]['draft_source']['candidates'][0]['component_id'],1)
        self.assertIsNone(control['units']);self.assertIsNone(control['current_value'])
        self.assertIsNone(control['control_semantics']['expected_current_value'])
        self.assertEqual(control['stored_units'],'state')
        self.assertIsNone(ir['pages'][0]['live_subpage_name'])
        self.assertFalse(ir['authoring_supported']);self.assertFalse(ir['live_target_verified'])

    def test_graph_id_is_scoped_to_graph_data_and_nan_remains_string(self):
        graph=make_ir()['plots'][0]['graphs'][0]
        self.assertEqual(graph['component_id'],21)
        self.assertEqual(graph['stored_fields']['Y MIN'],'NaN')
        self.assertEqual(make_ir()['plots'][0]['component_id'],20)

    def test_runtime_id_and_name_never_fallback_to_draft_identity(self):
        ir=make_ir(PAGE+CONTROL.replace('COMP_ID: 1\n','').replace('UUID: 11','UUID: 1'))
        self.assertEqual(ir['status'],'partial')
        self.assertEqual(ir['signal_references'][0]['draft_source']['status'],'unresolved')
        self.assertEqual(ir['signal_references'][0]['draft_source']['candidates'],[])

    def test_duplicate_draft_ids_across_contexts_stay_ambiguous(self):
        document=copy.deepcopy(DOCUMENT)
        document['components'].append({**document['components'][0],'context':'subsystem:1'})
        ir=make_ir(document=document)
        self.assertEqual(ir['status'],'partial')
        self.assertEqual(ir['signal_references'][0]['draft_source']['status'],'ambiguous')
        self.assertEqual(len(ir['signal_references'][0]['draft_source']['candidates']),2)

    def test_legacy_duplicates_and_unknown_records_are_retained(self):
        ir=make_ir(LAYOUT+PAGE+LAYOUT.removeprefix(PAGE).replace('TAGGED_V2.2_','')+'COMPONENT: DRAWING\nUUID: 90\nCOMPONENT-END:\n')
        self.assertEqual(len(ir['controls']),2);self.assertEqual(len(ir['pages']),2)
        self.assertEqual(len(ir['unknown_records']),1)
        self.assertTrue(all(p['identity_status']=='ambiguous' for p in ir['pages']))
        self.assertTrue(all(p['graphs'][0]['identity_status']=='ambiguous' for p in ir['plots']))
        self.assertEqual(ir['status'],'partial')

    def test_duplicate_reference_fields_cannot_bind(self):
        ir=make_ir(PAGE+CONTROL.replace('COMP_ID: 1','COMP_ID: 1\nCOMP_ID: 1'))
        self.assertEqual(ir['signal_references'][0]['draft_source']['status'],'unresolved')
        self.assertIn('COMP_ID',ir['signal_references'][0]['field_ambiguities'])

    def test_all_control_types_and_stored_position_rows(self):
        for kind,attribute in {'SLIDER':'value','BINARY_SWITCH':'value','SWITCH':'position','DIAL':'position','PUSHBUTTON':'position','BUTTON':'position','DRAFT_VARIABLE':'position'}.items():
            with self.subTest(kind=kind):
                ir=make_ir(PAGE+CONTROL.replace('TAGGED_V2.2_SWITCH',kind))
                self.assertEqual(ir['controls'][0]['control_semantics']['attribute'],attribute)
                self.assertEqual(len(ir['controls'][0]['control_semantics']['stored_positions']),1)

    def test_eof_page_and_empty_layout_supported_without_live_claim(self):
        self.assertEqual(make_ir(PAGE)['pages'][0]['end_line'],1)
        self.assertEqual(make_ir('')['pages'],[])

    def test_child_fields_do_not_overwrite_parent(self):
        ir=make_ir()
        self.assertEqual(ir['groups'][0]['name'],'Controls')
        self.assertEqual(ir['groups'][0]['signal_keys'],[])
        self.assertEqual(ir['controls'][0]['name'],'Fault')

    def test_unclosed_mismatched_graph_curve_data_and_view_rejected(self):
        for text in (LAYOUT.replace('GRAPH-END\n',''),LAYOUT.replace('CURVE-END\n',''),
                     LAYOUT.replace('PLOT-DATA-END\n',''),LAYOUT.replace('GRAPH-DATA-END','GUI-DATA-END'),
                     PAGE+'COMPONENT: FRAME\n'+PAGE, 'VIEW-END:\n'):
            with self.subTest(text=text[-70:]),self.assertRaises(ValueError):parse_runtime_layout(text)

    def test_graph_fields_outside_data_do_not_supply_identity(self):
        ir=make_ir(PAGE+PLOT.replace('GRAPH-DATA-START\n','').replace('GRAPH-DATA-END\n',''))
        self.assertIsNone(ir['plots'][0]['graphs'][0]['component_id'])
        self.assertEqual(ir['status'],'partial')

    def test_graph_and_control_id_collision_remains_ambiguous(self):
        ir=make_ir(LAYOUT.replace('UUID: 21','UUID: 11'))
        self.assertEqual(ir['controls'][0]['identity_status'],'ambiguous')
        self.assertEqual(ir['plots'][0]['graphs'][0]['identity_status'],'ambiguous')

    def test_unknown_data_scope_does_not_supply_graph_identity(self):
        text=LAYOUT.replace('GUI-DATA-START','UNKNOWN-DATA-START').replace('GUI-DATA-END','UNKNOWN-DATA-END')
        ir=make_ir(text)
        self.assertEqual(ir['plots'][0]['graphs'][0]['component_id'],21)
        self.assertEqual(ir['status'],'partial')

    def test_bounded_depth_line_and_header(self):
        for text in ('COMPONENT: FRAME\n'*33, 'X'*10001, PAGE+'COMPONENT: METER\nNAME: '+'a'*4097):
            with self.subTest(length=len(text)),self.assertRaises(ValueError):parse_runtime_layout(text)


class RuntimeIrPublicTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        with zipfile.ZipFile(self.project) as archive:self.dfx=archive.read('synthetic.dfx')
        self.write_layout()

    def write_layout(self,text=LAYOUT):
        with zipfile.ZipFile(self.project,'w') as z:
            z.writestr('synthetic.dfx',self.dfx);z.writestr('synthetic.rtx',text)

    def test_public_ir_and_inventory_no_import_socket_process_or_file_mutation(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original=builtins.__import__
        def guarded(name,*args,**kwargs):
            if name=='rtds' or name.startswith('rtds.'):raise AssertionError('vendor import')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=guarded),patch.object(socket,'socket',side_effect=AssertionError('socket')),patch.object(subprocess,'Popen',side_effect=AssertionError('process')):
            inventory=runtime_layout.inspect_runtime_layout(str(self.project))
            ir=runtime_layout.inspect_runtime_layout(str(self.project),representation='ir')
        self.assertEqual(inventory['total_count'],3)
        self.assertEqual(ir['runtime_ir']['signal_references'][0]['draft_source']['status'],'unique_saved_reference')
        self.assertFalse(ir['live_calls_made'])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_ir_pagination_and_stale_project_snapshot_rejected(self):
        result=runtime_layout.inspect_runtime_layout(str(self.project),representation='ir')
        for kwargs in ({'limit':1},{'offset':1},{'representation':'unknown'}):
            with self.assertRaises(ValueError):runtime_layout.inspect_runtime_layout(str(self.project),**({'representation':'ir'}|kwargs))
        self.write_layout(LAYOUT.replace('Fault','Changed'))
        with self.assertRaises(ValueError):runtime_layout.inspect_runtime_layout(str(self.project),result['snapshot_id'],representation='ir')

    def test_parser_source_hash_change_invalidates_snapshot(self):
        result=runtime_layout.inspect_runtime_layout(str(self.project))
        original=runtime_layout.sha256_file
        with patch.object(runtime_layout,'sha256_file',side_effect=lambda p:'e'*64 if p.name=='runtime_parser.py' else original(p)):
            with self.assertRaises(ValueError):runtime_layout.inspect_runtime_layout(str(self.project),result['snapshot_id'])

    def test_missing_runtime_member_and_encoding_fail_closed(self):
        with zipfile.ZipFile(self.project,'w') as z:z.writestr('synthetic.dfx',self.dfx)
        self.assertEqual(runtime_layout.inspect_runtime_layout(str(self.project),representation='ir')['status'],'unsupported')
        self.write_layout(b'\xff')
        with self.assertRaises(ValueError):runtime_layout.inspect_runtime_layout(str(self.project),representation='ir')


if __name__=='__main__':unittest.main()

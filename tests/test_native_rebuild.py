"""Authored reconstruction fixtures; no installed SDK imports or live calls."""
import test_environment
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

import test_engineering_editor as fixture
from rtds_agent.core.native_edit import NativeJournal
from rtds_agent.core.native_rebuild import compare_reconstruction, reconstruction_plan, wire_points
from rtds_agent.core.native_rebuild_adapter import rebuild_case, allow_rebuild_rpc
from rtds_agent.core.topology_parser import parse_rtfx_topology, parse_dfx_entities
from rtds_agent.model_editor import edit_rscad_model
from rtds_agent.safety import sha256_file


class Component:
    def __init__(self,case,row): self.case,self.row,self.unique_id=case,row,row['uuid']
    def get_path(self): return self.case.get_path()+'.draft.comp_id:'+str(self.unique_id)
    @property
    def component_type(self): return self.row['component_type']
    @property
    def parameters(self): return list(self.row['parameters'])
    def get_parameter(self,name): return self.row['parameters'][name]
    def set_parameter(self,name,value): self.row['parameters'][name]=value;self.case.state.modified=True
    @property
    def location(self): return self.row['location']
    @property
    def orientation(self): return self.row['orientation']
    @orientation.setter
    def orientation(self,value): self.row['orientation']=value;self.case.state.modified=True
    @property
    def mirrored(self): return self.row['mirrored']
    @mirrored.setter
    def mirrored(self,value): self.row['mirrored']=value;self.case.state.modified=True


class Canvas:
    identifier=1
    def __init__(self,case): self.case=case
    def get_path(self): return self.case.get_path()+'.draft.subpage:1'
    def select_area(self,lo,hi): pass
    def copy(self): self.case.app.clipboard=copy.deepcopy((self.case.rows,self.case.groups))
    def _paste(self,location,identifier):
        self.case.rows,self.case.groups=copy.deepcopy(self.case.app.clipboard)
        self.case.state.modified=True
        if self.case.app.fail=='paste': raise RuntimeError('Lost response after paste')
        if self.case.app.fail=='drop_group_member': self.case.rows.pop(0);self.case.groups=[]
        return [r['uuid'] for r in self.case.rows]+[-1]*len(self.case.groups)
    def _insert_component(self,kind,x,y,identifier):
        uid=10+len(self.case.rows)
        row=parse_dfx_entities(fixture.block(kind,uid,{'Gain':'0','Name':'default','Mode':'Off'},[x,y]))[0][0]
        self.case.rows.append(row);self.case.state.modified=True
        return uid
    def create_wire(self,phase,coordinates):
        uid=10+len(self.case.rows)
        row=parse_dfx_entities(fixture.block('WIRE',uid,dict(zip(('x1','y1','x2','y2'),map(str,[*coordinates[0],*coordinates[1]])))))[0][0]
        self.case.rows.append(row);self.case.state.modified=True


class Case:
    def __init__(self,app,path=''):
        self.app,self.file,self.caseid=app,path,len(app.cases)+1
        self.state=SimpleNamespace(run_state='stopped',modified=False)
        self.settings=SimpleNamespace(timestep=50.,title='Test Circuit',realtime=True)
        self.rows,self.groups=[],[];self.closed=False
        if path:
            with zipfile.ZipFile(path) as z:self.rows,self.groups=parse_dfx_entities(z.read('synthetic.dfx').decode())
        self.page=Canvas(self)
        self.draft=SimpleNamespace(num_subpages=lambda:1,get_subpage=lambda index:self.page,
             get_object=lambda uid:next((Component(self,r) for r in self.rows if r['uuid']==uid),None))
    def get_path(self): return 'rscad.case:'+str(self.caseid)
    def save(self,path):
        text='DRAFT 1\nSUBSYSTEM-START:\n'
        for row in self.rows:
            grouped=self.groups and row['uuid']==self.groups[0]['members'][0]['uuid']
            if grouped:text+='COMPONENT_TYPE=GROUP\n0 0 0 0 0\n'
            text+=fixture.block(row['component_type'],row['uuid'],row['parameters'],row['location'])
            if grouped:text+='GROUP-END:\n'
        text+='SUBSYSTEM-END:\n'
        with zipfile.ZipFile(self.app.source) as old,zipfile.ZipFile(path,'w') as z:
            for entry in old.infolist():z.writestr(entry,text if entry.filename=='synthetic.dfx' else old.read(entry))
            z.comment=old.comment
        self.file=path;self.state.modified=False
    def close(self,force=False):
        assert not force
        if self.app.fail=='close_new' and len(self.app.cases)>1:return False
        self.closed=True;return True


class App:
    def __init__(self,source,fail=None): self.source,self.fail,self.cases=source,fail,[]
    def get_path(self): return 'rscad'
    def connect(self): pass
    def disconnect(self,terminate=False): assert not terminate
    def get_version(self): return '2.7'
    def get_case(self,file,open_file): return next((c for c in self.cases if c.file==file and not c.closed),None)
    def open_case(self,path):
        c=Case(self,path);self.cases.append(c)
        if self.fail=='reopen' and len(self.cases)>2:c.rows[0]['location'][0]+=32
        return c
    def new_case(self):
        c=Case(self);self.cases.append(c)
        if self.fail=='existing_file':c.file=str(self.source)
        if self.fail=='new_response':raise RuntimeError('New case exists but response lost')
        if self.fail=='invalid_new':return None
        return c


class RebuildTests(unittest.TestCase):
    request=fixture.EngineeringEditorTests.request
    def setUp(self):
        fixture.EngineeringEditorTests.setUp(self)
        self.write()
    def write(self,extra=False):
        with zipfile.ZipFile(self.project,'w') as z:
            z.writestr('synthetic.dfx',self.dfx);z.writestr('synthetic.rtx','VIEW-START: VIEW-ID: "1"\nVIEW-END:\n')
            z.comment=b'preserved'
    def document(self): return parse_rtfx_topology(self.project,self.defs).document
    def grouped(self):
        self.dfx=self.dfx.replace('COMPONENT_TYPE=synthetic_gain','COMPONENT_TYPE=GROUP\n0 0 0 0 0\nCOMPONENT_TYPE=synthetic_gain').replace('COMPONENT_TYPE=WIRE','GROUP-END:\nCOMPONENT_TYPE=WIRE')
        self.write()
        policy=json.loads(self.policy.read_text());policy['allowed_components'].append('GROUP');self.policy.write_text(json.dumps(policy))
    def run_adapter(self,strategy,fail=None):
        folder=self.data/(strategy+'_'+str(fail));folder.mkdir(parents=True)
        journal=NativeJournal(folder/'journal.json');app=App(self.project,fail)
        return folder,journal,app
    def test_world_wire_coordinates_apply_rotation_and_mirror(self):
        r={'location':[432,112],'orientation':90,'mirrored':False,'parameters':{'x1':'-32','y1':'0','x2':'32','y2':'0'}}
        self.assertEqual(wire_points(r),[[432,80],[432,144]])
        r['mirrored']=True;self.assertEqual(wire_points(r),[[432,144],[432,80]])
    def test_insert_and_clipboard_roundtrip(self):
        for strategy in ('insert','clipboard'):
            with self.subTest(strategy=strategy):
                folder,journal,app=self.run_adapter(strategy)
                result=rebuild_case(app,self.project,folder/'result.rtfx',strategy,journal,self.defs)
                self.assertEqual(result['status'],'verified_edit');self.assertTrue(result['cleanup_verified'])
                self.assertEqual(result['reconstruction']['component_count'],2)
                self.assertTrue(all(c.closed for c in app.cases));self.assertEqual(len(app.cases),3)
                if strategy=='insert':self.assertEqual(result['reconstruction']['uuid_mapping'][0]['candidate_id'],10)
    def test_group_roundtrip_and_no_sentinel_handle(self):
        self.grouped();folder,journal,app=self.run_adapter('clipboard')
        result=rebuild_case(app,self.project,folder/'result.rtfx','clipboard',journal,self.defs)
        self.assertEqual(result['paste_result']['group_sentinels'],1)
        self.assertTrue(result['paste_result']['structure_verified']);self.assertNotIn(-1,journal.value['read_ids'])
        with self.assertRaisesRegex(ValueError,'flat'): reconstruction_plan(self.project,self.document(),'insert')
    def test_mutation_failures_and_unknown_creation_require_recovery(self):
        for fail in ('paste','new_response','invalid_new','close_new','existing_file'):
            with self.subTest(fail=fail):
                folder,journal,app=self.run_adapter('clipboard',fail)
                with self.assertRaises((RuntimeError,ValueError)):rebuild_case(app,self.project,folder/'result.rtfx','clipboard',journal,self.defs)
                self.assertEqual(journal.value['status'],'operator_recovery_required')
                self.assertFalse(journal.value['cleanup_verified']);self.assertEqual(len(app.cases),2)
                if fail=='close_new':self.assertEqual(sum(r['operation']=='close' for r in journal.value['native_calls']),2) # source then new, no retry
                if fail=='existing_file':self.assertEqual(journal.value['case_history'][-1]['observed_file'],str(self.project))
    def test_reopen_readback_failure_is_not_success(self):
        folder,journal,app=self.run_adapter('clipboard','reopen')
        with self.assertRaisesRegex(ValueError,'readback'):rebuild_case(app,self.project,folder/'result.rtfx','clipboard',journal,self.defs)
        self.assertEqual(journal.value['status'],'failed');self.assertTrue(journal.value['cleanup_verified'])
    def test_lost_group_member_prevents_reopen(self):
        self.grouped();folder,journal,app=self.run_adapter('clipboard','drop_group_member')
        with self.assertRaises(ValueError):rebuild_case(app,self.project,folder/'result.rtfx','clipboard',journal,self.defs)
        self.assertEqual(len(app.cases),2);self.assertTrue(journal.value['cleanup_verified'])
    def test_saved_runtime_and_opaque_payloads_are_refused(self):
        for name,data in [('synthetic.rtx','COMPONENT: METER\nUUID: 1\nCOMPONENT-END:\n'),('extra.bin','opaque')]:
            self.write()
            # Rewrite, not duplicate ZIP entries.
            with zipfile.ZipFile(self.project) as z:members={n:z.read(n) for n in z.namelist()}
            members[name]=data.encode()
            with zipfile.ZipFile(self.project,'w') as z:
                for n,v in members.items():z.writestr(n,v)
            with self.assertRaisesRegex(ValueError,'discard'):reconstruction_plan(self.project,self.document(),'clipboard')
    def test_public_preview_apply_and_group_policy(self):
        self.grouped();sdk={'available':True,'evidence_id':'synthetic'}
        def worker(command,**kwargs):
            p=Path(command[-1]);job=json.loads(p.read_text(encoding='utf-8'));journal=NativeJournal(p.parent/'native_journal.json')
            rebuild_case(App(job['input_path']),job['input_path'],job['output_path'],'clipboard',journal,self.defs)
            return SimpleNamespace(returncode=0)
        req={**self.request([{'op':'rebuild_draft','strategy':'clipboard'}]),'backend':'native'}
        with patch('rtds_agent.native_editor.inspect_native_sdk',return_value=sdk),patch('rtds_agent.native_editor.subprocess.run',side_effect=worker) as run:
            preview=edit_rscad_model(req);self.assertFalse(run.called)
            result=edit_rscad_model({**req,'mode':'apply','preview_id':preview['preview_id']})
            self.assertEqual(result['reconstruction']['group_count'],1)
            self.assertEqual(sha256_file(self.project),req['source_sha256'])
            policy=json.loads(self.policy.read_text());policy['denied_components']=['GROUP'];self.policy.write_text(json.dumps(policy))
            req=self.request([{'op':'rebuild_draft','strategy':'clipboard'}])
            with self.assertRaisesRegex(ValueError,'denies'):edit_rscad_model({**req,'backend':'native'})
    def test_no_static_rebuild_mixed_operations_or_auto_apply(self):
        req=self.request([{'op':'rebuild_draft','strategy':'insert'}])
        with self.assertRaises(ValueError):edit_rscad_model(req)
        with self.assertRaises(ValueError):edit_rscad_model({**req,'backend':'native','operations':req['operations']*2})
        with patch('rtds_agent.native_editor.subprocess.run',side_effect=AssertionError('No process')):
            preview=edit_rscad_model({**req,'backend':'auto'})
            with self.assertRaisesRegex(ValueError,'preview only'):edit_rscad_model({**req,'backend':'auto','mode':'apply','preview_id':preview['preview_id']})
    def test_transport_denies_rack_runtime_compile_and_unbound_mutation(self):
        folder,journal,_=self.run_adapter('clipboard');journal.value.update(owned_case=3,identity_verified=True)
        for path,method,args in [('rscad','getRacks',[]),('rscad.case:3','compile',[]),('rscad.case:3.rtx','run',[]),('rscad','newCase',[]),('rscad.case:4','getFile',[]),('rscad.case:3','close',[True])]:
            self.assertFalse(allow_rebuild_rpc(path,method,args,journal,self.project,folder/'out.rtfx'))
        self.assertTrue(allow_rebuild_rpc('rscad.case:3','getRunState',[],journal,self.project,folder/'out.rtfx'))
        journal.lost_identity()
        self.assertTrue(allow_rebuild_rpc('rscad','ping',[],journal,self.project,folder/'out.rtfx'))
        self.assertFalse(allow_rebuild_rpc('rscad.case:3','getRunState',[],journal,self.project,folder/'out.rtfx'))
    def test_recovery_marker_blocks_private_sdk_entry_before_inspection(self):
        from rtds_agent.core.native_edit_worker import run_isolated_sdk
        folder,journal,_=self.run_adapter('clipboard')
        (self.data/'native_recovery_required.json').write_text('{}')
        with patch('rtds_agent.core.native_edit_worker.inspect_native_sdk',side_effect=AssertionError('No SDK work')):
            with self.assertRaisesRegex(ValueError,'recovery'):run_isolated_sdk(self.settings,self.project,folder/'out.rtfx',[],journal,{})
    def test_native_wire_storage_can_change_without_changing_endpoints(self):
        a=self.document();b=copy.deepcopy(a)
        wire=b['components'][1];wire['location']=[64,0]
        wire['parameters'].update(x1='-32',x2='32')
        self.assertTrue(compare_reconstruction(a,b)['same_static_topology'])
        wire['parameters']['x2']='64'
        with self.assertRaisesRegex(ValueError,'geometry'):compare_reconstruction(a,b)
    def test_same_records_with_different_nets_are_not_equivalent(self):
        a=self.document();b=copy.deepcopy(a);b['nets']=[]
        with self.assertRaisesRegex(ValueError,'topology'):compare_reconstruction(a,b)
    def test_group_identity_renumbering_is_mapped_but_member_changes_fail(self):
        self.grouped();a=self.document();b=copy.deepcopy(a)
        b['components'][0]['uuid']=30
        b['groups'][0]['group_id']='subsystem:0/group:9'
        b['groups'][0]['members'][0]['uuid']=30
        for net in b['nets']:
            for member in net['members']:
                if member['component_id']==1:member['component_id']=30
        self.assertEqual(compare_reconstruction(a,b)['group_count'],1)
        b['groups'][0]['members']=[]
        with self.assertRaisesRegex(ValueError,'GROUP'):compare_reconstruction(a,b)
    def test_renumbered_contexts_do_not_merge_identical_hierarchy_names(self):
        def hierarchy(uid,x,gain):
            return 'HIERARCHY-START:\n'+fixture.block('HIERARCHY',uid,{'Name':'same'},[x,0])+fixture.block('synthetic_gain',uid+1,{'Gain':gain,'Name':'gain','Mode':'Off'})+'HIERARCHY-END:\n'
        self.dfx='DRAFT 1\nSUBSYSTEM-START:\n'+hierarchy(10,0,'1')+hierarchy(20,320,'2')+'SUBSYSTEM-END:\n';self.write()
        a=self.document();b=copy.deepcopy(a)
        for r in b['components']:
            if r['context']=='subsystem:0':r['uuid']+=100;r['location'][0]+=64
            else:r['context']=r['context'].replace('same:10','same:110').replace('same:20','same:120')
        # No topology is needed to test the context identity proof independently.
        a['nets']=[];b['nets']=[]
        result=compare_reconstruction(a,b);self.assertEqual(len(result['context_translations']),3)
        b['components'][1]['parameters']['Gain']='2';b['components'][3]['parameters']['Gain']='1'
        with self.assertRaisesRegex(ValueError,'content'):compare_reconstruction(a,b)
    def test_ambiguous_mapping_and_nonuniform_geometry_are_rejected(self):
        a=self.document();b=copy.deepcopy(a);b['components'][0]['location'][0]+=32
        with self.assertRaises(ValueError):compare_reconstruction(a,b)
        row=copy.deepcopy(a['components'][0]);row['uuid']=99;a['components'].append(row)
        with self.assertRaisesRegex(ValueError,'Ambiguous'):compare_reconstruction(a,a)


if __name__=='__main__':unittest.main()

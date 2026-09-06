"""Optional domain criteria bind exact authored sources without executing RSCAD."""
import test_environment
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

import test_public_release as fixture
from rtds_agent.model_check import check_rscad_model
from rtds_agent import rulepacks


DEFINITION = '''PARAMETERS:
 R "Declared resistance" "Ohm" REAL 0 -100 100
 V "Declared line RMS voltage" "V" REAL 100 -1000 1000
 V2 "Second voltage" "V" REAL 100 -1000 1000
 F "Frequency" "Hz" REAL 60 0 300
 Mode "Declared mode" "Off;On" TOGGLE 1
 Name "Name only" "" NAME authored
NODES:
'''


class RulepackPublicTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        self.definition = self.defs/'synthetic_gain'
        self.definition.write_text(DEFINITION, encoding='utf-8')
        self.parameters = {'R':'0','V':'100','V2':'100','F':'60','Mode':'On','Name':'123'}
        self.write()

    def write(self, duplicate=None, missing=None, duplicate_identity=False):
        parameters = {key:value for key,value in self.parameters.items() if key != missing}
        raw = ''.join(f'{key}: {value}\n' for key,value in parameters.items())
        if duplicate: raw += f'{duplicate}: {parameters[duplicate]}\n'
        block = f'COMPONENT_TYPE=synthetic_gain\n0 0 0 0 {len(parameters)+(1 if duplicate else 0)}\nPARAMETERS-START:\n{raw}PARAMETERS-END:\nUUID: 1\n'
        self.dfx = 'DRAFT 1\nSUBSYSTEM-START:\n'+block*(2 if duplicate_identity else 1)+'SUBSYSTEM-END:\n'
        with zipfile.ZipFile(self.project,'w') as archive:
            archive.writestr('synthetic.dfx', self.dfx)

    def digest(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def snapshot(self):
        return {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def binding(self, parameter='R', **changes):
        values = {'R':('resistance','Ohm'),'V':('voltage_ll_rms','V'),'V2':('voltage_ll_rms','V'),'F':('frequency','Hz'),'Name':('dimensionless','1')}
        quantity, units = values[parameter]
        return {'binding_id':parameter,'context':'subsystem:0','component_id':1,'component_type':'synthetic_gain',
            'definition_sha256':self.digest(self.definition),'parameter':parameter,'expected_value':self.parameters[parameter],
            'origin':'stored','quantity':quantity,'units':units,'basis':'Authored shared declared reference', 'pu_base':None,
            'selectors':[{'parameter':'Mode','expected_value':'On'}],**changes}

    def request(self, bindings=None, check='nonnegative_resistance', inputs=None, limits=None, **rule_changes):
        bindings = bindings or [self.binding()]
        rule = {'rule_id':'criterion','check':check,'inputs':inputs or {'value':bindings[0]['binding_id']},'limits':limits or {},
            'source':[{'source_path':str(self.definition),'source_sha256':self.digest(self.definition),'locator':'Authored exact definition'},
                      {'source_path':str(self.guide),'source_sha256':self.digest(self.guide),'locator':'Authored test criterion; no official requirement'}],
            'scope':'Explicit synthetic design intent','severity':'error','confidence':{'level':'low','rationale':'Authored fixture only'},
            'assumptions':[],**rule_changes}
        return {'schema_version':'1.0','input_project_sha256':self.digest(self.project),
                'packs':[{'pack_id':'device','domain':'transformer','bindings':bindings,'rules':[rule]}]}

    def inspect(self, request=None):
        return check_rscad_model(str(self.project), rulepacks=request or self.request())

    def result(self, request=None):
        return self.inspect(request)['rulepacks']

    def test_read_only_zero_resistance_retains_source_scope_severity_confidence(self):
        before=self.snapshot()
        with patch('socket.create_connection',side_effect=AssertionError('network')), patch('subprocess.Popen',side_effect=AssertionError('native')):
            result=self.result()
        self.assertEqual(result['counts']['passed'],1)
        self.assertEqual(before,self.snapshot())
        self.assertFalse(result['applicability_verified'])
        self.assertFalse(result['execution_authorized'])
        self.assertFalse(result['integration_qualified'])
        self.assertTrue(result['source_hashes_verified'])
        self.assertEqual(result['rules'][0]['confidence']['level'],'low')
        self.assertEqual(result,self.result())

    def test_negative_criterion_updates_optional_top_level_status(self):
        self.parameters['R']='-1';self.write()
        result=self.inspect()
        self.assertEqual(result['rulepacks']['counts']['failed'],1)
        self.assertEqual(result['status'],'errors_found')
        self.assertTrue(any(row['finding']=='domain_criterion_failed' for row in result['findings']))
        self.assertEqual(result['engineering_verdict'],'not_evaluated')

    def test_optional_absent_keeps_legacy_explicit_rules(self):
        field={'context':'subsystem:0','component_id':1,'parameter':'V','units':'V'}
        legacy={'rule_id':'legacy','kind':'positive','field':field,'provenance':'authored criterion'}
        result=check_rscad_model(str(self.project),electrical_rules=[legacy])
        self.assertNotIn('rulepacks',result)
        self.assertEqual(result['electrical_rules'][0]['status'],'passed')
        both=check_rscad_model(str(self.project),electrical_rules=[legacy],rulepacks=self.request())
        self.assertEqual(both['electrical_rules'],result['electrical_rules'])
        self.assertEqual(both['rulepacks']['counts']['passed'],1)

    def test_unit_and_basis_mismatch_are_inconclusive(self):
        for change in ({'units':'ohms'}, {'component_id':404}, {'expected_value':'1'}, {'origin':'definition_default'}):
            result=self.result(self.request([self.binding(**change)]))
            self.assertEqual(result['counts']['inconclusive'],1,change)
        left,right=self.binding('V'),self.binding('V2',basis='Different phase/reference')
        result=self.result(self.request([left,right],check='nominal_voltage_match',inputs={'left':'V','right':'V2'},limits={'absolute_tolerance':0}))
        self.assertEqual(result['counts']['inconclusive'],1)

    def test_missing_selector_and_wrong_selector_do_not_apply(self):
        for selectors in ([{'parameter':'Mode','expected_value':'Off'}],[{'parameter':'Missing','expected_value':'On'}],
                          [{'parameter':'R','expected_value':'0'}]):
            result=self.result(self.request([self.binding(selectors=selectors)]))
            self.assertEqual(result['counts']['inconclusive'],1)

    def test_default_value_and_default_toggle_are_explicit(self):
        self.write(missing='R')
        request=self.request([self.binding(origin='definition_default')])
        result=self.result(request)
        self.assertEqual(result['counts']['passed'],1)
        self.assertEqual(result['binding_observations'][0]['origin'],'definition_default')
        self.write(missing='Mode')
        result=self.result()
        self.assertEqual(result['counts']['passed'],1)
        observed=result['binding_observations'][0]['evidence'][0]['observed']['selector_conditions'][0]
        self.assertEqual((observed['value'],observed['origin']),('On','definition_default'))

    def test_duplicate_raw_values_or_identity_cannot_pass(self):
        for key in ('R','Mode'):
            self.write(duplicate=key)
            self.assertEqual(self.result()['counts']['inconclusive'],1)
        self.write(duplicate_identity=True)
        self.assertEqual(self.result()['counts']['inconclusive'],1)

    def test_repeated_definition_declaration_is_not_collapsed(self):
        self.definition.write_text(DEFINITION.replace('NODES:', ' R "Other mode" "Ohm" REAL 5 -100 100\nNODES:'))
        result=self.result()
        self.assertEqual(result['counts']['inconclusive'],1)
        self.assertIn('repeated',result['binding_observations'][0]['reason'])

    def test_nested_group_boundaries_keep_exact_component_binding(self):
        block = self.dfx.split('SUBSYSTEM-START:\n', 1)[1].split('SUBSYSTEM-END:', 1)[0]
        for indent in ('', '  '):
            grouped = ('DRAFT 1\nSUBSYSTEM-START:\n' + indent + 'COMPONENT_TYPE=GROUP\n0 0 0 0 0\n'
                       + 'COMPONENT_TYPE=GROUP\n0 0 0 0 0\n' + block
                       + 'GROUP-END:\nGROUP-END:\nSUBSYSTEM-END:\n')
            with zipfile.ZipFile(self.project, 'w') as archive:
                archive.writestr('synthetic.dfx', grouped)
            before = self.snapshot()
            result = self.result()
            self.assertEqual(result['counts']['passed'], 1)
            self.assertEqual(before, self.snapshot())

    def test_raw_hierarchy_context_and_boundary_metadata_do_not_bleed(self):
        block = self.dfx.split('SUBSYSTEM-START:\n', 1)[1].split('SUBSYSTEM-END:', 1)[0]
        hierarchy = ('HIERARCHY-START:\nCOMPONENT_TYPE=HIERARCHY\n0 0 0 0 1\n'
                     'PARAMETERS-START:\nName: child\nPARAMETERS-END:\nUUID: 9\n')
        tail = 'PARAMETERS-START:\nR: 99\nPARAMETERS-END:\nUUID: 999\n'
        raw = ('DRAFT 1\nSUBSYSTEM-START:\n' + block + hierarchy
               + block.replace('R: 0', 'R: 7') + 'HIERARCHY-END:\n' + tail + 'SUBSYSTEM-END:\n')
        inventory = rulepacks._raw_inventory(raw.encode())
        self.assertEqual(inventory[('subsystem:0', 1)][0]['values']['R'], ['0'])
        self.assertEqual(inventory[('subsystem:0/child:9', 1)][0]['values']['R'], ['7'])
        self.assertTrue(inventory[('subsystem:0/child:9', 1)][0]['sections_exact'])

    def test_duplicate_raw_uuid_cannot_pass(self):
        with zipfile.ZipFile(self.project, 'w') as archive:
            archive.writestr('synthetic.dfx', self.dfx.replace('UUID: 1', 'UUID: 1\nUUID: 1'))
        self.assertEqual(self.result()['counts']['inconclusive'], 1)

    def test_nonnumeric_type_symbolic_and_nonfinite_values_do_not_pass(self):
        result=self.result(self.request([self.binding('Name')]))
        self.assertEqual(result['counts']['inconclusive'],1)
        for value in ('unknown+1','NaN','Infinity','1e300'):
            self.parameters['R']=value;self.write()
            self.assertEqual(self.result()['counts']['inconclusive'],1,value)

    def test_hash_mismatch_and_omitted_definition_provenance_refuse(self):
        request=self.request()
        for change in ('project','definition','provenance','omit'):
            altered=copy.deepcopy(request)
            if change=='project': altered['input_project_sha256']='0'*64
            elif change=='definition': altered['packs'][0]['bindings'][0]['definition_sha256']='0'*64
            elif change=='provenance': altered['packs'][0]['rules'][0]['source'][1]['source_sha256']='0'*64
            else: altered['packs'][0]['rules'][0]['source']=altered['packs'][0]['rules'][0]['source'][1:]
            with self.subTest(change=change),self.assertRaises(ValueError): self.result(altered)

    def test_sources_changed_during_evaluation_refuse_return(self):
        original=rulepacks.evaluate_rulepacks
        def evaluate(*args):
            result=original(*args)
            self.guide.write_text('changed while evaluating')
            return result
        with patch.object(rulepacks,'evaluate_rulepacks',side_effect=evaluate):
            with self.assertRaisesRegex(ValueError,'changed'): self.result()

    def test_companion_changed_during_evaluation_refuse_return(self):
        self.definition.write_text(DEFINITION.replace('NODES:', ' File "Dependency" "" FILE companion.txt\nNODES:'))
        self.parameters['File']='companion.txt';self.write()
        companion=self.sources/'companion.txt';companion.write_text('authored dependency')
        original=rulepacks.evaluate_rulepacks
        def evaluate(*args):
            result=original(*args);companion.write_text('changed dependency');return result
        with patch.object(rulepacks,'evaluate_rulepacks',side_effect=evaluate):
            with self.assertRaises(ValueError): self.result()

    def test_bad_request_rejected_before_model_reads(self):
        request=self.request();request['execute']=True
        with patch('rtds_agent.model_check._document',side_effect=AssertionError('unexpected read')):
            with self.assertRaises(ValueError): self.inspect(request)

    def test_outside_and_linked_sources_refuse(self):
        outside=self.root/'outside.md';outside.write_text('outside allowed roots')
        request=self.request();request['packs'][0]['rules'][0]['source'][1].update(source_path=str(outside),source_sha256=self.digest(outside))
        with self.assertRaises(ValueError): self.result(request)
        with patch.object(Path,'is_junction',return_value=True):
            with self.assertRaises(ValueError): rulepacks._file(str(self.guide),(self.docs,))

    def test_oversize_provenance_never_opens(self):
        class Huge:
            def is_file(self): return True
            def stat(self): return type('Stat',(),{'st_size':rulepacks.MAX_SOURCE_BYTES+1})()
            def open(self,*args): raise AssertionError('oversize read')
        with self.assertRaises(ValueError): rulepacks._hash(Huge())

    def test_cli_catalog_does_not_read_models_or_write(self):
        from rtds_agent.cli import main
        before=self.snapshot();stream=io.StringIO()
        with redirect_stdout(stream),patch.object(rulepacks,'_document',side_effect=AssertionError('model read')):
            self.assertEqual(main(['rulepacks','list']),0)
        catalog=json.loads(stream.getvalue())
        self.assertEqual(len(catalog['domains']),10)
        self.assertFalse(catalog['execution_authorized'])
        self.assertEqual(before,self.snapshot())


if __name__=='__main__':
    unittest.main()

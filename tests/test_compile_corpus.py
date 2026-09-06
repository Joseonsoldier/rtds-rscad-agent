"""Synthetic source-bound corpus inspection without native authority."""
import test_environment
import hashlib
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rtds_agent import compile_corpus as corpus
from rtds_agent.settings import Settings
from rtds_agent.safety import ToolSafetyError


class CompileCorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(self.root)
        self.settings_patch = patch.object(corpus, 'get_settings', return_value=self.settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.raw = self.root / 'fixture.log'
        self.raw.write_bytes(b'authored unknown\r\n')
        self.manifest = self.root / 'corpus.json'
        self.value = {'schema_version':'1.0', 'corpus_id':'authored', 'description':'Synthetic parser regression',
                      'cases':[self.case()]}
        self.save()

    def case(self):
        digest = hashlib.sha256(self.raw.read_bytes()).hexdigest()
        return {'case_id':'one', 'evidence_kind':'synthetic_authored', 'format_id':'rscad_compile_errs_v1',
                'raw_ref':{'path':str(self.raw), 'sha256':digest, 'bytes':self.raw.stat().st_size, 'encoding':'utf-8'},
                'expectations':{'categories':['unknown'], 'component_mappings':['unknown'], 'parser_coverage':'partial'},
                'provenance':[{'source_path':str(self.raw), 'source_sha256':digest, 'locator':'authored fixture'}],
                'sanitization':None, 'limitations':[]}

    def save(self):
        self.manifest.write_text(json.dumps(self.value), encoding='utf-8')

    def inspect(self):
        return corpus.inspect_compile_corpus(str(self.manifest))

    def snapshot(self):
        return {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_pass_is_deterministic_read_only_and_not_native(self):
        before = self.snapshot()
        with patch('socket.create_connection', side_effect=AssertionError('network')), patch('subprocess.Popen', side_effect=AssertionError('native')):
            result = self.inspect()
        self.assertEqual(result, self.inspect())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result['counts'], {'cases':1,'passed':1,'failed':0})
        self.assertEqual(result['native_outcome'], 'not_evaluated')
        self.assertFalse(result['execution_authorized'])
        self.assertNotIn('authored unknown', json.dumps(result))

    def test_cli_catalog_and_corpus_exit_status_are_read_only(self):
        from rtds_agent.cli import main
        output=io.StringIO();before=self.snapshot()
        with redirect_stdout(output),patch.object(corpus,'get_settings',side_effect=AssertionError('catalog settings read')):
            self.assertEqual(main(['diagnostics','list']),0)
        self.assertEqual(len(json.loads(output.getvalue())['taxonomy']),9)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['diagnostics','corpus',str(self.manifest)]),0)
        self.assertEqual(before,self.snapshot())
        self.value['cases'][0]['expectations']['categories']=['parameter'];self.save()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['diagnostics','corpus',str(self.manifest)]),1)

    def test_tampered_fixture_and_provenance_refused(self):
        self.raw.write_bytes(b'changed')
        with self.assertRaises(ToolSafetyError): self.inspect()
        self.value['cases'] = [self.case()]
        source = self.root/'guide.txt';source.write_bytes(b'guide')
        self.value['cases'][0]['provenance'].append({'source_path':str(source),'source_sha256':'0'*64,'locator':'guide'})
        self.save()
        with self.assertRaises(ToolSafetyError): self.inspect()

    def test_expectation_failure_does_not_map_without_model(self):
        self.value['cases'][0]['expectations']['component_mappings'] = ['exact_context_uuid']
        self.save();result=self.inspect()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['cases'][0]['actual']['component_mappings'], ['unknown'])
        self.assertEqual(result['component_mapping_scope'], 'not_model_mapped')

    def test_unknown_format_retained(self):
        self.value['cases'][0]['format_id']='future_format'
        self.value['cases'][0]['expectations']['parser_coverage']='unsupported'
        self.save();self.assertEqual(self.inspect()['status'], 'passed')

    def test_declared_native_empty_fixture_never_proves_compile(self):
        self.raw.write_bytes(b'');case=self.case()
        case.update(evidence_kind='native_observed_private', expectations={'categories':[], 'component_mappings':[], 'parser_coverage':'empty'})
        self.value['cases']=[case];self.save();result=self.inspect()
        self.assertEqual(result['status'],'passed')
        self.assertFalse(result['native_origin_verified'])
        self.assertFalse(result['integration_qualified'])
        self.assertEqual(result['native_outcome'],'not_evaluated')

    def test_fixture_changes_during_parse_refused(self):
        original=corpus.diagnostics.parse_compile_log
        def mutate(*args):
            result=original(*args);self.raw.write_bytes(b'changed');return result
        with patch.object(corpus.diagnostics,'parse_compile_log',side_effect=mutate):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_manifest_changes_during_parse_refused(self):
        original=corpus.diagnostics.parse_compile_log
        def mutate(*args):
            result=original(*args);self.manifest.write_text('{}');return result
        with patch.object(corpus.diagnostics,'parse_compile_log',side_effect=mutate):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_settings_changes_refused(self):
        with patch.object(corpus,'get_settings',side_effect=[self.settings,Settings(self.root/'changed')]):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_provenance_changes_during_parse_refused(self):
        guide=self.root/'guide.txt';guide.write_bytes(b'guide')
        self.value['cases'][0]['provenance'].append({'source_path':str(guide),
            'source_sha256':hashlib.sha256(b'guide').hexdigest(),'locator':'authored guide'})
        self.save();original=corpus.diagnostics.parse_compile_log
        def mutate(*args):
            result=original(*args);guide.write_bytes(b'changed');return result
        with patch.object(corpus.diagnostics,'parse_compile_log',side_effect=mutate):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_aggregate_source_bound(self):
        with patch.object(corpus,'MAX_TOTAL_BYTES',10):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_strict_json_and_boolean_byte_count_refused(self):
        self.manifest.write_text('{"cases":[],"cases":[]}')
        with self.assertRaises(ToolSafetyError):self.inspect()
        self.value['cases'][0]['raw_ref']['bytes']=True;self.save()
        with self.assertRaises(ValueError):self.inspect()

    def test_manifest_fixture_and_response_bounds(self):
        with patch.object(corpus,'MAX_MANIFEST_BYTES',10):
            with self.assertRaises(ToolSafetyError):self.inspect()
        with patch.object(corpus,'MAX_OUTPUT_BYTES',10):
            with self.assertRaises(ToolSafetyError):self.inspect()
        self.raw.write_bytes(b'x'*(1048576+1))
        with self.assertRaises(ToolSafetyError):self.inspect()

    def test_outside_root_and_linked_ancestor_refused(self):
        with patch.object(corpus,'get_settings',return_value=Settings(self.root/'elsewhere')):
            with self.assertRaises(ToolSafetyError):self.inspect()
        with patch.object(Path,'is_junction',return_value=True):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_loaded_schema_drift_refused(self):
        with patch.object(corpus.diagnostics,'CORPUS_SCHEMA',{}):
            with self.assertRaises(ToolSafetyError):self.inspect()

    def test_implementation_change_refused(self):
        original=corpus._hash;count={}
        def changed(path):
            result=original(path);count[str(path)]=count.get(str(path),0)+1
            if path.name=='compile_corpus.py' and count[str(path)]>1:
                result['source_sha256']='0'*64
            return result
        with patch.object(corpus,'_hash',side_effect=changed):
            with self.assertRaises(ToolSafetyError):self.inspect()


if __name__ == '__main__':
    unittest.main()

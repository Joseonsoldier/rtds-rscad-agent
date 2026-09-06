"""Public graph/cache boundaries against authored temporary inputs only."""
import test_environment
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import unittest
import zipfile
from unittest.mock import patch

import test_public_release as fixture
from rtds_agent import component_knowledge as knowledge
from rtds_agent.core import component_graph_store as store


class ComponentKnowledgeTests(unittest.TestCase):
    setUp = fixture.PublicReleaseTests.setUp

    def build(self, annotations=None):
        return knowledge.build_component_knowledge([str(self.project)], annotations)

    def query(self, built, **changes):
        return knowledge.query_component_knowledge({'graph_id': built['graph_id'], 'mode': 'search', 'query': 'synthetic_gain', **changes})

    def snapshot(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}

    def annotation(self):
        path = self.docs/'assertions.json'
        value = {'schema_version': '1.0', 'field_assertions': [{
            'definition_id': 'synthetic_gain', 'field': 'engineering_role', 'value': 'Authored regulator',
            'scope': 'Synthetic assertion only', 'provenance': [{'source_path': str(self.guide),
                'source_sha256': hashlib.sha256(self.guide.read_bytes()).hexdigest(), 'locator': 'line 1'},
                {'source_path': str(self.defs/'synthetic_gain'), 'source_sha256': hashlib.sha256((self.defs/'synthetic_gain').read_bytes()).hexdigest(),
                 'locator': 'exact definition version'}]}], 'edge_assertions': []}
        path.write_text(json.dumps(value), encoding='utf-8')
        return path, value

    def test_build_search_get_neighbors_preserve_sources_and_read_queries(self):
        before = self.snapshot()
        with patch('socket.create_connection', side_effect=AssertionError('network')), patch('subprocess.Popen', side_effect=AssertionError('process')):
            built = self.build()
            after = self.snapshot()
            self.assertTrue(all(after[key] == value for key, value in before.items()))
            found = self.query(built)
            self.assertEqual(found['status'], 'found')
            self.assertFalse(found['compatibility_verified'])
            node = found['nodes'][0]
            self.assertEqual(node['fields']['compatible_neighbors']['status'], 'unresolved')
            for mode in ('get', 'neighbors'):
                result = knowledge.query_component_knowledge({'graph_id': built['graph_id'], 'mode': mode, 'node_id': node['node_id']})
                self.assertFalse(result['mutations_performed'])
                self.assertFalse(result['live_calls_made'])
            self.assertEqual(after, self.snapshot())

    def test_deterministic_immutable_rebuild_and_status(self):
        first = self.build()
        before = self.snapshot()
        second = self.build()
        self.assertEqual(first['graph_id'], second['graph_id'])
        self.assertEqual(second['status'], 'already_present')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(store.status()['graph_ids'], [first['graph_id']])
        self.assertEqual(store.status()['status'], 'available_unverified')

    def test_absent_status_and_missing_query_never_index_or_write(self):
        before = self.snapshot()
        self.assertEqual(store.status()['status'], 'absent')
        with self.assertRaises(ValueError):
            self.query({'graph_id': '0'*64})
        self.assertEqual(before, self.snapshot())
        self.assertFalse(store.cache_root().exists())

    def test_definition_tamper_addition_and_project_tamper_refuse(self):
        built = self.build()
        for path in (self.defs/'synthetic_gain', self.project):
            original = path.read_bytes()
            try:
                path.write_bytes(original + b'\nchanged')
                with self.assertRaises(ValueError): self.query(built)
            finally:
                path.write_bytes(original)
        (self.defs/'new_definition').write_text('PARAMETERS:\nNODES:\n')
        with self.assertRaises(ValueError): self.query(built)

    def test_settings_and_implementation_identity_changes_refuse(self):
        built = self.build()
        with patch.object(knowledge, '_implementations', return_value=set()):
            with self.assertRaises(ValueError): self.query(built)
        config = json.loads(self.config.read_text())
        config['document_roots'] = [str(self.sources)]
        self.config.write_text(json.dumps(config))
        with self.assertRaises(ValueError): self.query(built)

    def test_annotation_claim_retained_but_provenance_and_annotation_tamper_refuse(self):
        path, _ = self.annotation()
        built = self.build(str(path))
        found = self.query(built, query='Authored regulator')
        self.assertEqual(found['nodes'][0]['fields']['engineering_role']['status'], 'asserted')
        self.assertFalse(found['integration_qualified'])
        for source in (self.guide, path):
            original = source.read_bytes()
            try:
                source.write_bytes(original+b' ')
                with self.assertRaises(ValueError): self.query(built)
            finally:
                source.write_bytes(original)

    def test_invalid_annotation_provenance_cannot_publish(self):
        path, value = self.annotation()
        value['field_assertions'][0]['provenance'][0]['source_sha256'] = '0'*64
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.build(str(path))
        self.assertEqual(store.status()['graph_ids'], [])

    def test_rebuild_cannot_transfer_old_assertion_to_changed_definition(self):
        path, _ = self.annotation()
        self.build(str(path))
        definition = self.defs/'synthetic_gain'
        definition.write_bytes(definition.read_bytes()+b'\n// different definition version\n')
        with self.assertRaises(ValueError): self.build(str(path))

    def test_companion_change_invalidates_entire_graph(self):
        definition = self.defs/'synthetic_gain'
        definition.write_text('PARAMETERS:\n Gain "Gain" "pu" REAL 1 0 10\n File "Input file" "" FILE companion.txt\nNODES:\n')
        with zipfile.ZipFile(self.project, 'w') as archive:
            archive.writestr('synthetic.dfx', 'DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 2\nPARAMETERS-START:\nGain: 1\nFile: companion.txt\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n')
        companion = self.sources/'companion.txt'; companion.write_text('authored companion')
        built = self.build()
        self.assertEqual(self.query(built)['status'], 'found')
        companion.write_text('changed companion')
        with self.assertRaises(ValueError): self.query(built)

    def test_search_ignores_provenance_hashes_and_empty_match_is_explicit(self):
        built = self.build()
        result = self.query(built, query=hashlib.sha256(self.project.read_bytes()).hexdigest())
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['nodes'], [])

    def test_pagination_is_stable_and_bounded(self):
        (self.defs/'second_gain').write_text('PARAMETERS:\n Gain "Synthetic gain" "pu" REAL 1 0 10\nNODES:\n')
        built = self.build()
        one = self.query(built, query='gain', limit=1)
        two = self.query(built, query='gain', limit=1, offset=one['next_offset'])
        self.assertEqual(one['total'], 2)
        self.assertNotEqual(one['nodes'][0]['node_id'], two['nodes'][0]['node_id'])
        self.assertIsNone(two['next_offset'])

    def test_query_contract_rejects_cross_mode_unknown_bool_and_path_fields(self):
        request = {'graph_id': '0'*64, 'mode': 'search', 'query': 'gain'}
        for changes in ({'depth': 2}, {'limit': True}, {'limit': 101}, {'offset': -1}, {'query': ' '},
                        {'mode': 'execute'}, {'graph_id': '../escape'}, {'write': True}, {'node_id': 'x'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                knowledge.validate_query({**request, **changes})
        for paths in ([{}], ['x']*17, ['x','x'], [True]):
            with self.assertRaises(ValueError): knowledge.build_component_knowledge(paths)

    def test_cache_tamper_does_not_overwrite_or_self_repair(self):
        built = self.build()
        path = Path(built['graph_path'])
        graph = json.loads(path.read_text(encoding='utf-8'))
        graph['integration_qualified'] = True
        path.write_text(json.dumps(graph))
        before = path.read_bytes()
        with self.assertRaises(ValueError): self.query(built)
        with self.assertRaises(ValueError): self.build()
        self.assertEqual(path.read_bytes(), before)

    def test_query_revalidates_inputs_at_return_boundary(self):
        built = self.build()
        original = knowledge._context_check
        calls = []
        def check(context):
            calls.append(1)
            if len(calls) == 2:
                self.guide.write_text('Not a graph source; source definition below is.')
                (self.defs/'synthetic_gain').write_text('changed')
            return original(context)
        with patch.object(knowledge, '_context_check', side_effect=check):
            with self.assertRaises(ValueError): self.query(built)
        self.assertEqual(len(calls), 2)

    def test_existing_generation_revalidates_after_cache_read(self):
        built = self.build()
        graph, _ = store.read_object(Path(built['graph_path']))
        calls = []
        def revalidate():
            calls.append(1)
            if len(calls) == 2: raise ValueError('source changed during read')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            store.publish(graph, revalidate)
        self.assertEqual(len(calls), 2)
        self.assertFalse((store.cache_root()/'.writer-lock').exists())

    def test_failed_publication_keeps_staging_but_no_queryable_generation(self):
        built = self.build()
        graph, _ = store.read_object(Path(built['graph_path']))
        graph['graph_sha256'] = 'f'*64
        calls = []
        def revalidate():
            calls.append(1)
            if len(calls) == 2: raise ValueError('changed before commit')
        with self.assertRaises(ValueError): store.publish(graph, revalidate)
        self.assertFalse(store.graph_path('f'*64).exists())
        self.assertEqual(store.status()['graph_ids'], [built['graph_id']])
        self.assertTrue(list(store.cache_root().glob('.staging-*')))

    def test_writer_conflict_and_generation_limit_preserve_existing_data(self):
        root = store.cache_root()
        root.mkdir(parents=True)
        lock = root/'.writer-lock'; lock.mkdir()
        with self.assertRaisesRegex(ValueError, 'writer conflict'): self.build()
        self.assertTrue(lock.is_dir())
        lock.rmdir()
        with patch.object(store, 'MAX_GENERATIONS', 0):
            with self.assertRaises(ValueError): self.build()
        self.assertEqual(store.status()['graph_ids'], [])

    def test_duplicate_nonfinite_oversize_and_growing_json_refuse(self):
        path = self.data/'bad.json'
        for text in ('{"x":1,"x":2}', '{"x":NaN}', '[]', '{'):
            path.write_text(text)
            with self.assertRaises(ValueError): store.read_object(path)
        path.write_text('{}')
        with self.assertRaises(ValueError): store.read_object(path, maximum=1)
        with patch.object(Path, 'open', return_value=io.BytesIO(b' '*32)):
            with self.assertRaises(ValueError): store.read_object(path, maximum=8)

    def test_oversized_source_is_rejected_before_open(self):
        class Oversized:
            def is_file(self): return True
            def stat(self): return type('Stat', (), {'st_size': 256*1024*1024+1})()
            def open(self, *args): raise AssertionError('opened oversize source')
        with self.assertRaises(ValueError): knowledge._source(Oversized(), 'provenance')

    def test_linked_cache_ancestor_is_refused_without_publication(self):
        with patch.object(Path, 'is_junction', side_effect=lambda: True):
            with self.assertRaises(ValueError): store.cache_root()
        self.assertFalse((self.data/'knowledge'/'component_graphs').exists())

    def test_cli_build_query_and_status(self):
        from rtds_agent.cli import main
        def call(args):
            stream = io.StringIO()
            with redirect_stdout(stream): self.assertIn(main(args), (None, 0))
            return json.loads(stream.getvalue())
        built = call(['knowledge','graph','build','--project',str(self.project)])
        found = call(['knowledge','graph','query','--graph-id',built['graph_id'],'--query','gain'])
        self.assertEqual(found['status'], 'found')
        self.assertEqual(call(['knowledge','graph','status'])['graph_ids'], [built['graph_id']])


if __name__ == '__main__':
    unittest.main()

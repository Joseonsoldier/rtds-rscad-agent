"""Authored scalar fixtures exercise the read-only boundary, never RSCAD."""
import test_environment
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rtds_agent import line_authoring as reader
from rtds_agent.safety import ToolSafetyError
from rtds_agent.settings import Settings


AUTHORED = b'''Line Summary:
  {
  Line Length = 75.0
  Steady State Frequency = 50.0
  }
Line Constants Ground Data:
  {
  GroundResistivity = 120.0
  }
RLC Options:
  {
  Data Entry Format = 0
  Positive Sequence Series Resistance = 0.03
  Positive Sequence Series Ind Reactance = 0.4
  Positive Sequence Series Cap Reactance = 0.2
  Zero Sequence Series Resistance = 0.2
  Zero Sequence Series Ind Reactance = 1.1
  Zero Sequence Series Cap Reactance = 0.3
  Number of Phases = 3
  }
'''


class LineAuthoringToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.settings = Settings(self.data)
        settings_patch = patch.object(reader, 'get_settings', return_value=self.settings)
        settings_patch.start()
        self.addCleanup(settings_patch.stop)
        self.source = self.data / 'authored.tli'
        self.source.write_bytes(AUTHORED)
        self.guide = self.data / 'authored-evidence.txt'
        self.guide.write_text('Authored test declaration; no vendor or engineering authority.', encoding='utf-8')
        self.request = self.data / 'preview.json'
        self.value = {'schema_version': '1.0', 'profile_id': 'tline_rlc_3phase_ohmic_v1',
            'source': {'path': str(self.source), 'sha256': self.sha(self.source)},
            'assumptions': {'ideally_transposed': True, 'frequency_independent_bergeron': True},
            'changes': [{'field': 'line_length_km', 'expected': 75.0, 'value': 80.0}],
            'provenance': [{'source_path': str(self.source), 'source_sha256': self.sha(self.source), 'locator': 'authored source'},
                           {'source_path': str(self.guide), 'source_sha256': self.sha(self.guide), 'locator': 'authored declaration'}]}
        self.save()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save(self):
        self.request.write_text(json.dumps(self.value), encoding='utf-8')

    def preview(self):
        return reader.preview_line_authoring_request(str(self.request))

    def snapshot(self):
        return {str(path): path.read_bytes() for path in self.data.rglob('*') if path.is_file()}

    def test_deterministic_read_only_preview_preserves_all_files_and_no_native_calls(self):
        before = self.snapshot()
        with (patch('socket.create_connection', side_effect=AssertionError('network')),
              patch('subprocess.Popen', side_effect=AssertionError('process'))):
            result = self.preview()
        self.assertEqual(result, self.preview())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result['status'], 'preview_only')
        self.assertEqual(result['files_written'], 0)
        self.assertFalse(result['candidate']['persisted'])
        self.assertFalse(result['integration_qualified'])
        self.assertFalse(result['grounding']['interpretation_verified'])
        self.assertFalse(result['execution_authorized'])
        self.assertNotEqual(result['candidate']['sha256'], self.sha(self.source))
        self.assertNotIn('raw_candidate', result)

    def test_hash_bound_inspection_reports_supported_subset(self):
        report = reader.inspect_line_authoring_input(str(self.source), self.sha(self.source))
        self.assertEqual(report['status'], 'supported')
        self.assertFalse(report['live_calls_made'])
        self.assertEqual(report['source']['sha256'], self.sha(self.source))

    def test_unsupported_format_is_not_validation_success(self):
        self.source.write_bytes(b'!RTDS_REVISION=3\nUnknown Geometry\n')
        report = reader.inspect_line_authoring_input(str(self.source), self.sha(self.source))
        self.assertEqual(report['status'], 'unsupported')
        self.assertTrue(report['reasons'])

    def test_cli_list_inspect_preview_and_unsupported_exit_codes(self):
        from rtds_agent.cli import main
        before = self.snapshot()
        with redirect_stdout(io.StringIO()), patch.object(reader, 'get_settings', side_effect=AssertionError('catalog settings')):
            self.assertEqual(main(['lines', 'list']), 0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['lines', 'inspect', str(self.source), '--sha256', self.sha(self.source)]), 0)
            self.assertEqual(main(['lines', 'preview', str(self.request)]), 0)
            self.assertEqual(main(['lines', 'inspect', str(self.source), '--sha256', self.sha(self.source), '--profile', 'unknown']), 1)
        self.assertEqual(before, self.snapshot())

    def test_source_and_provenance_tamper_refused(self):
        self.source.write_bytes(AUTHORED + b'\n')
        with self.assertRaises(ToolSafetyError): self.preview()
        self.source.write_bytes(AUTHORED)
        self.guide.write_text('Changed', encoding='utf-8')
        with self.assertRaises(ToolSafetyError): self.preview()

    def test_changed_source_during_core_preview_refuses_return(self):
        original = reader.core.preview_line_input
        def mutate(*args):
            result = original(*args)
            self.source.write_bytes(AUTHORED + b'\n')
            return result
        with patch.object(reader.core, 'preview_line_input', side_effect=mutate):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_changed_provenance_during_core_preview_refuses_return(self):
        original = reader.core.preview_line_input
        def mutate(*args):
            result = original(*args)
            self.guide.write_bytes(b'Changed evidence')
            return result
        with patch.object(reader.core, 'preview_line_input', side_effect=mutate):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_changed_request_during_core_preview_refuses_return(self):
        original = reader.core.preview_line_input
        def mutate(*args):
            result = original(*args)
            self.request.write_bytes(self.request.read_bytes() + b'\n')
            return result
        with patch.object(reader.core, 'preview_line_input', side_effect=mutate):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_changed_settings_refuses_return(self):
        with patch.object(reader, 'get_settings', side_effect=[self.settings, Settings(self.root / 'other')]):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_changed_implementation_refuses_return(self):
        implementation = self.data / 'authored-implementation.py'
        implementation.write_bytes(b'original implementation')
        files = [implementation, reader._implementation_files()[-1]]
        original = reader.core.preview_line_input
        def mutate(*args):
            result = original(*args)
            implementation.write_bytes(b'changed implementation')
            return result
        with patch.object(reader, '_implementation_files', return_value=files), patch.object(reader.core, 'preview_line_input', side_effect=mutate):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_outside_relative_traversal_and_absent_references_refused(self):
        outside = self.root / 'outside.tli'
        outside.write_bytes(AUTHORED)
        for path in (str(outside), 'authored.tli', str(self.data / '..' / 'data' / 'authored.tli'), str(self.data / 'missing.tli')):
            with self.subTest(path=path):
                with self.assertRaises(ToolSafetyError):
                    reader.inspect_line_authoring_input(path, self.sha(self.source))

    def test_linked_ancestor_refused(self):
        original = Path.is_symlink
        with patch.object(Path, 'is_symlink', lambda path: path == self.data or original(path)):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_cable_and_imperial_filenames_cannot_inherit_metric_tline_profile(self):
        for suffix in ('.cli', '.tlx', '.txt'):
            path = self.data / ('renamed' + suffix)
            path.write_bytes(AUTHORED)
            with self.subTest(suffix=suffix):
                with self.assertRaises(ToolSafetyError):
                    reader.inspect_line_authoring_input(str(path), self.sha(path))
                self.value['source'] = {'path': str(path), 'sha256': self.sha(path)}
                self.value['provenance'][0] = {'source_path': str(path), 'source_sha256': self.sha(path), 'locator': 'authored source'}
                self.save()
                with self.assertRaises(ToolSafetyError): self.preview()

    def test_duplicate_nonfinite_oversized_request_and_log_bounds(self):
        for payload in (b'{"schema_version":"1.0","schema_version":"1.0"}', b'{"x":NaN}', b' ' * (reader.MAX_REQUEST_BYTES + 1)):
            self.request.write_bytes(payload)
            with self.subTest(payload_bytes=len(payload)):
                with self.assertRaises((ToolSafetyError, ValueError)): self.preview()
        self.save()
        self.source.write_bytes(b' ' * 65537)
        with self.assertRaises(ToolSafetyError):
            reader.inspect_line_authoring_input(str(self.source), self.sha(self.source))

    def test_loaded_schema_change_refuses_return(self):
        with patch.object(reader.core, 'LINE_AUTHORING_SCHEMA', {}):
            with self.assertRaises(ToolSafetyError): self.preview()

    def test_json_expected_and_requested_values_cannot_round_into_a_false_match(self):
        original = self.request.read_text(encoding='utf-8')
        for before, after in (('"expected": 75.0', '"expected": 75.0000000000000000001'),
                              ('"value": 80.0', '"value": 80.0000000000000000001')):
            self.assertIn(before, original)
            self.request.write_text(original.replace(before, after), encoding='utf-8')
            with self.subTest(field=before):
                with self.assertRaises(ToolSafetyError): self.preview()

    def test_reference_aggregate_and_output_bounds(self):
        with patch.object(reader, 'MAX_TOTAL_BYTES', 10):
            with self.assertRaises(ToolSafetyError): self.preview()
        with patch.object(reader, 'MAX_OUTPUT_BYTES', 10):
            with self.assertRaises(ToolSafetyError): self.preview()


if __name__ == '__main__':
    unittest.main()

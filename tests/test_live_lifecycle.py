"""Authored lifecycle failures: never connect to a native SDK or rack."""
import test_environment
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rtds_agent.core.live_lifecycle import close_owned_case, claim_case, assert_owned_case, observe_state, require_absent_case
from rtds_agent.core.production_backend import ProductionBackendConfig, RscadFxCompileDriver
from rtds_agent.settings import Settings, ConfigurationError
from test_runtime_backend import FakeLiveCase, FakeLiveApp, InjectedRuntimeDriver


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.case = FakeLiveCase('C:/authored/working/case.rtfx')
        self.app = FakeLiveApp(self.case)
        self.app.opened = True

    def test_false_close_or_remaining_case_is_not_cleanup(self):
        for returned, remaining in ((False, 123), (None, -1), (True, 123), (True, False)):
            with self.subTest(returned=returned, remaining=remaining):
                with patch.object(self.case, 'close', return_value=returned), patch.object(
                    self.app, '_get_case_named', side_effect=[123, remaining]):
                    with self.assertRaises(ValueError):
                        close_owned_case(self.app, self.case, self.case.file, 123)

    def test_unknown_absence_is_not_hidden_as_no_case(self):
        with patch.object(self.app, '_get_case_named', side_effect=[123, RuntimeError('transport')]):
            with self.assertRaisesRegex(RuntimeError, 'transport'):
                close_owned_case(self.app, self.case, self.case.file, 123)

    def test_changed_identity_modified_or_running_case_is_never_closed(self):
        for mutation in ('id', 'file', 'modified', 'running', 'remote'):
            self.setUp()
            expected = self.case.file
            if mutation == 'id': self.case.caseid = 999
            if mutation == 'file': self.case.file = 'C:/other.rtfx'
            if mutation == 'modified': self.case.state.modified = True
            if mutation == 'running': self.case.state.run_state = 'running'
            with patch.object(self.app, '_get_case_named', return_value=999 if mutation == 'remote' else 123):
                with self.assertRaises(ValueError):
                    close_owned_case(self.app, self.case, expected, 123)
            self.assertEqual(self.case.close_calls, 0)

    def test_close_confirms_absence_without_force(self):
        result = close_owned_case(self.app, self.case, self.case.file, claim_case(self.case, self.case.file))
        self.assertTrue(result['case_absence_confirmed'])
        self.assertFalse(result['force'])

    def test_downloading_is_bounded_and_recorded(self):
        sleeps = []
        def advance(seconds):
            sleeps.append(seconds)
            self.case.state.run_state = 'running'
        self.case.state.run_state = 'downloading'
        self.assertEqual(observe_state(self.case, 'running', advance), ['downloading', 'running'])
        self.assertEqual(sleeps, [.25])
        self.case.state.run_state = 'stopped'
        self.assertEqual(len(observe_state(self.case, 'running', sleeps.append, attempts=3)), 3)

    def test_explicit_family_version_keeps_default_and_rejects_other_versions(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(Settings(Path(root)).validated().expected_rscad_version, '2.7.3')
            self.assertEqual(Settings(Path(root), expected_rscad_version='2.7').validated().expected_rscad_version, '2.7')
            with self.assertRaises(ConfigurationError):
                Settings(Path(root), expected_rscad_version='2.8').validated()

    def test_compile_refuses_unsaved_rack_reassignment(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'case.rtfx'; path.write_bytes(b'authored')
            self.case.file = str(path); self.case.settings.starting_rack = 2
            self.app.opened = False
            driver = RscadFxCompileDriver(ProductionBackendConfig(Path(root), Path(root)))
            with patch.object(driver, '_new_connection', return_value=self.app):
                result = driver.compile_case(working_copy=str(path), rack=1)
            self.assertFalse(result['compile_called'])
            self.assertFalse(result['starting_rack_changed_in_memory'])
            self.assertEqual(self.case.settings.starting_rack, 2)
            self.assertTrue(result['case_closed'])

    def test_preopen_lookup_error_cannot_establish_absence(self):
        for observed in (123, False, True, 0, -2, 'absent'):
            with patch.object(self.app, '_get_case_named', return_value=observed):
                with self.assertRaises(ValueError):
                    require_absent_case(self.app, self.case.file)
        with patch.object(self.app, '_get_case_named', side_effect=RuntimeError('lookup failed')):
            with self.assertRaises(RuntimeError):
                require_absent_case(self.app, self.case.file)

    def test_boolean_or_float_cannot_supply_remote_case_id(self):
        self.case.caseid = 1
        for observed in (True, 1.0):
            with patch.object(self.app, '_get_case_named', return_value=observed):
                with self.assertRaises(ValueError):
                    assert_owned_case(self.app, self.case, self.case.file, 1)


if __name__ == '__main__':
    unittest.main()

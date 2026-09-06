"""Regression for unsupported legacy LF before authority or native dispatch."""
import test_environment
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_public_release as public
from test_runtime_backend import runtime_spec
from rtds_agent import execution
from rtds_agent.core.execution_requirements import require_executable_spec
from rtds_agent.input_contracts import validate_test_spec


class LoadflowGuards(unittest.TestCase):
    setUp = public.PublicReleaseTests.setUp

    def spec(self):
        value = runtime_spec()
        value['loadflow_initialization'] = {'enabled': True, 'timeout_seconds': 30,
            'zero_impedance_threshold_pu': 1e-6, 'flat_start': True, 'method': 'FAST_DECOUPLED'}
        return value

    def test_public_actions_refuse_before_backend_installation_or_grant(self):
        prepared = execution.prepare_workflow(str(self.project), self.spec(), [str(self.guide)])
        path = prepared['workflow_path']
        public.configure_policy(self.settings, ['compile', 'offline_test', 'runtime_start_stop'], [2], 'synthetic operator')
        before = {p: p.read_bytes() for p in Path(path).parent.rglob('*') if p.is_file()}
        with patch.object(execution, '_backend', side_effect=AssertionError('backend')) as backend, \
             patch.object(execution, 'inspect_installation', side_effect=AssertionError('installation')) as installation:
            for call in (lambda: execution.compile_project(path), lambda: execution.run_offline_test(path),
                         lambda: execution.prepare_simulation_run(path),
                         lambda: execution.run_simulation(path, str(self.data/'missing.json'), '0'*64)):
                with self.assertRaisesRegex(ValueError, 'frequency, not timeout'):
                    call()
            backend.assert_not_called()
            installation.assert_not_called()
        self.assertEqual(before, {p: p.read_bytes() for p in Path(path).parent.rglob('*') if p.is_file()})
        self.assertFalse(list(self.data.rglob('runtime-request-*.json')))

    def test_disabled_and_omitted_requests_remain_valid(self):
        for spec in (runtime_spec(), {**runtime_spec(), 'loadflow_initialization': {'enabled': False}}):
            before = copy.deepcopy(spec)
            validate_test_spec(spec)
            require_executable_spec(spec)
            self.assertEqual(spec, before)

    def test_legacy_plan_is_inspectable_but_never_executable(self):
        spec = self.spec()
        self.assertEqual(validate_test_spec(spec), spec)
        for value in (spec['loadflow_initialization'], {}, None, {'enabled': 0}, {'enabled': 'false'}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'loadflow_initialization'):
                require_executable_spec({'loadflow_initialization': value})

    def test_disabled_request_cannot_smuggle_solver_parameters(self):
        spec = self.spec()
        spec['loadflow_initialization']['enabled'] = False
        with self.assertRaises(ValueError):
            validate_test_spec(spec)


if __name__ == '__main__':
    unittest.main()

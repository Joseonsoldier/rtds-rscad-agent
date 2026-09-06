"""Public profiles, skill manifests, diagnostic grounding and eval trace contracts."""
import test_environment
import asyncio
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_public_release as fixture
from rtds_agent import skill_catalog


class EngineeringIntegrationTests(unittest.TestCase):
    setUp=fixture.PublicReleaseTests.setUp

    def test_default_full_contract_and_opt_in_profiles(self):
        from rtds_agent.mcp_server import server,build_server,CORE_NAMES,ENGINEERING_NAMES
        full={t.name:t for t in asyncio.run(server.list_tools())}
        self.assertEqual(len(full),50)
        for profile,names in [('core',CORE_NAMES),('engineering',ENGINEERING_NAMES)]:
            actual={t.name for t in asyncio.run(build_server(profile).list_tools())}
            self.assertEqual(actual,set(names)); self.assertLess(actual,set(full))
        self.assertTrue(full['run_experiment_suite'].annotations.destructive_hint)
        self.assertFalse(full['capture_rtds_results'].annotations.read_only_hint)
        with self.assertRaises(ValueError): build_server('unsafe')

    def test_skill_manifests_reference_real_tools_and_packaged_resources(self):
        from rtds_agent.mcp_server import server
        names={t.name for t in asyncio.run(server.list_tools())}
        for skill in skill_catalog.list_skills()['skills']:
            manifest=skill['manifest']
            self.assertLessEqual(set(manifest['required_tools']+manifest['optional_tools']),names)
            self.assertTrue(manifest['examples'])
            self.assertIn('manifest.json',skill_catalog._bundled_files(skill['name']))

    def test_grounded_diagnostic_uses_exact_exception_class_not_guessed_log(self):
        import test_diagnostics
        helper=test_diagnostics.DiagnosticTests
        self.prepare=lambda: Path(fixture.PublicReleaseTests.prepare(self))
        workflow,_,_=helper.evidence(self,[{'type':'CommunicationError','message':'authored transport error','context':'subsystem:0','component_id':1}],operational=True)
        sdk=self.settings.sdk_root/'rtds'; sdk.mkdir(parents=True)
        (sdk/'__init__.py').write_text('__version__="1.1"\n')
        (sdk/'error.py').write_text('class CommunicationError(Exception):\n    """Authored communication failure."""\n')
        from rtds_agent.diagnostics import get_execution_diagnostics
        result=get_execution_diagnostics(str(workflow),include_grounding=True)
        self.assertEqual(result['status'],'available')
        row=result['diagnostics'][0]['grounding']
        self.assertEqual(row['native_log_grammar'],'unqualified')
        self.assertEqual(row['api_evidence']['status'],'found')
        self.assertEqual(row['likely_causes'][0]['rank'],1)
        self.assertFalse(row['automatic_repair'])

    def test_evaluation_scorer_rejects_forbidden_missing_and_false_claims(self):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('eval_runner',root/'tools/run_evals.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        tasks=json.loads((root/'evals/tasks.json').read_text())['tasks']
        self.assertEqual(len(tasks),9)
        for task in tasks:
            trace={'calls':[{'tool':n,'is_error':task['requires_tool_error'],'arguments':{'request':{'mode':task['allowed_suite_modes'][0]}} if n=='run_experiment_suite' else {}} for n in task['required_tools']],
                   'final_state':task['expected_final_state'],'evidence':{key:'authored' for key in task['required_evidence']}}
            trace['evidence'].update(task['evidence_assertions'])
            self.assertEqual(module.score(task,trace)['status'],'passed')
            trace['calls'].append({'tool':'execute_shell','is_error':False,'arguments':{}})
            result=module.score(task,trace)
            self.assertEqual(result['status'],'failed'); self.assertFalse(result['llm_executed'])
            trace['calls'].pop(); trace['evidence'].clear()
            self.assertEqual(module.score(task,trace)['status'],'failed')
        task=next(t for t in tasks if t['task_id']=='EVAL-07')
        trace={'calls':[{'tool':'get_manual_page','is_error':False,'arguments':{}},
                         {'tool':'run_experiment_suite','is_error':False,'arguments':{'request':{'mode':'execute'}}}],
               'final_state':task['expected_final_state'],'evidence':{k:'authored' for k in task['required_evidence']}}
        trace['evidence'].update(task['evidence_assertions'])
        self.assertEqual(module.score(task,trace)['status'],'failed')

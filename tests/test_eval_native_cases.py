"""Synthetic bridge/lifecycle qualification only; no installed SDK or app calls."""
import test_environment
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import eval_native_cases as native
from rtds_agent.settings import Settings
from rtds_agent.core.native_edit import NativeJournal
from rtds_agent.core.native_rebuild_adapter import rebuild_case
from rtds_agent.core.state_machine import sha256_json
from rtds_agent.safety import sha256_file
from test_engineering_editor import block, GAIN_DEF, WIRE_DEF
from test_native_rebuild import App


class NativeEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eval-native-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.fixture = self.root / "fixture"
        self.sources = self.fixture / "sources"
        self.vendor = self.root / "vendor"
        self.defs = self.vendor / "MLIB/COMPONENTS"
        self.docs = self.vendor / "DOC"
        self.data = self.root / "data"
        self.temp_root = self.root / "native-temp"
        for p in (self.sources, self.defs, self.docs, self.data, self.temp_root):
            p.mkdir(parents=True)
        self.source = self.sources / "synthetic.rtfx"
        self.dfx = ('DRAFT 1\nSUBSYSTEM-START:\n'
                    + block('synthetic_gain', 1, {'Gain': '1', 'Name': 'gain', 'Mode': 'Off'})
                    + block('WIRE', 2, {'x1': '32', 'y1': '0', 'x2': '96', 'y2': '0'})
                    + 'SUBSYSTEM-END:\n')
        (self.defs / "synthetic_gain").write_text(GAIN_DEF)
        (self.defs / "WIRE").write_text(WIRE_DEF)
        self.write_source()
        self.settings = Settings(self.data, self.vendor, (self.sources,), (self.docs,)).validated()
        self.coordination = Settings(self.root / "operator-data", self.vendor,
                                     (self.sources,), (self.docs,)).validated()
        self.sdk = {"available": True, "evidence_id": "b" * 64}
        self.sdk_patch = patch.object(native, "inspect_native_sdk", return_value=self.sdk)
        self.sdk_patch.start()
        self.addCleanup(self.sdk_patch.stop)
        self.impl_patch = patch.object(native, "implementation_digest", return_value="c" * 64)
        self.impl_patch.start()
        self.addCleanup(self.impl_patch.stop)
        temp_patch = patch('rtds_agent.core.native_temp.tempfile.gettempdir', return_value=str(self.temp_root))
        temp_patch.start()
        self.addCleanup(temp_patch.stop)
        self.manifest_path = self.fixture / "manifest.json"
        self.manifest = {"schema_version": "1.0", "task_id": "EVAL-N03", "fixture_id": "authored",
                         "cohort_id": "synthetic-cohort",
                         "source": self.source.name, "source_sha256": sha256_file(self.source),
                         "files": {self.source.name: sha256_file(self.source)},
                         "definitions": {p.name: sha256_file(p) for p in self.defs.iterdir()},
                         "strategy": "insert", "required_component_types": ["synthetic_gain", "WIRE"],
                         "sdk_evidence_id": "b" * 64, "implementation_sha256": "c" * 64}
        self.save_manifest()

    def write_source(self):
        with zipfile.ZipFile(self.source, "w") as z:
            z.writestr("synthetic.dfx", self.dfx)
            z.writestr("synthetic.rtx", 'VIEW-START: VIEW-ID: "1"\nVIEW-END:\n')
            z.comment = b"preserved"

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def bridge(self, enabled=True):
        return native.NativeCaseBridge(self.manifest_path, self.settings, self.coordination, allow_native=enabled)

    def request(self, bridge):
        return {k: v for k, v in bridge.inspect().items() if k in
                {"task_id", "fixture_id", "fixture_sha256", "source_sha256", "snapshot_id", "plan"}}

    def synthetic_worker(self, path, digest):
        self.assertEqual(sha256_file(path), digest)
        self.assertTrue((self.settings.data_dir / "execution.lock").exists())
        self.assertTrue((self.coordination.data_dir / "execution.lock").exists())
        job = json.loads(path.read_text())
        journal = NativeJournal(path.parent / "native_journal.json")
        inp = path.parent / "input" / self.source.name
        out = path.parent / "working" / self.source.name
        if job["action"] == "construct":
            rebuild_case(App(inp), inp, out, self.manifest["strategy"], journal, self.defs)
        else:
            app = CompileApp()
            code = native.compile_case(app, out, sha256_file(inp), journal)
            build = out.parent / ("build_" + out.stem)
            build.mkdir()
            (build / (out.stem + ".log")).write_text("Compile completed successfully.")
            (build / (out.stem + "_errs.log")).write_bytes(b"")
            for path in (out.parent, build):
                (path / (out.stem + "_r1")).write_bytes(b"synthetic binary")
            return code
        return 0

    def test_inspection_is_readonly_and_exact_model_plan_is_required(self):
        bridge = self.bridge(False)
        evidence = bridge.inspect()
        self.assertFalse(evidence["live_calls_made"])
        self.assertEqual(evidence["plan"]["components"][0]["parameters"]["Gain"], "1")
        self.assertIn("definition_sha256", evidence["definition_evidence"]["synthetic_gain"])
        request = self.request(bridge)
        request["plan"]["components"][0]["parameters"]["Gain"] = "2"
        with patch.object(native, "run_worker") as worker:
            with self.assertRaisesRegex(ValueError, "binding mismatch"):
                bridge.construct(request)
            worker.assert_not_called()
        self.assertFalse(bridge.stage.exists())

    def test_native_requires_host_optin_without_policy_creation(self):
        bridge = self.bridge(False)
        with self.assertRaisesRegex(ValueError, "opt-in"):
            bridge.construct(self.request(bridge))
        self.assertFalse(list(self.root.rglob("execution_policy.json")))

    def test_successful_actual_synthetic_adapter_and_separate_compile(self):
        bridge = self.bridge()
        original = self.source.read_bytes()
        with patch.object(native, "run_worker", side_effect=self.synthetic_worker) as runner:
            result = bridge.construct(self.request(bridge))
            self.assertEqual(result["status"], "verified")
            self.assertTrue(result["native_evidence"]["reopened"])
            self.assertEqual(result["reconstruction"]["uuid_mapping_count"], 2)
            request = {"task_id": "EVAL-N03", "fixture_id": "authored",
                       "construction_receipt_sha256": result["receipt_sha256"],
                       "candidate_sha256": result["candidate_sha256"]}
            compiled = bridge.compile(request)
            self.assertEqual(compiled["status"], "verified")
            self.assertFalse(compiled["artifact_review_required"])
            self.assertTrue(compiled["cleanup_verified"])
            with self.assertRaises(FileExistsError):
                bridge.compile(request)
            self.assertEqual(runner.call_count, 2)
        self.assertEqual(original, self.source.read_bytes())
        self.assertFalse((self.coordination.data_dir / "execution.lock").exists())
        self.assertFalse(list(self.root.rglob("execution_policy.json")))

    def test_manifest_path_and_extra_fields_fail_closed(self):
        for change in ({"source": "../outside.rtfx"}, {"files": {"../outside": "a" * 64}},
                       {"script": "arbitrary"}, {"source": "C:/outside.rtfx"}):
            with self.subTest(change=change):
                altered = {**self.manifest, **change}
                self.manifest_path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    self.bridge()
        self.save_manifest()

    def test_changed_definition_or_added_companion_blocks_before_worker(self):
        bridge = self.bridge()
        request = self.request(bridge)
        (self.defs / "synthetic_gain").write_text(GAIN_DEF + "\n")
        with patch.object(native, "run_worker") as worker:
            with self.assertRaisesRegex(ValueError, "changed"):
                bridge.construct(request)
            worker.assert_not_called()
        (self.defs / "synthetic_gain").write_text(GAIN_DEF)
        (self.sources / "extra.tli").write_text("unbound")
        with self.assertRaisesRegex(ValueError, "inventory"):
            bridge.verify()

    def test_sdk_or_code_drift_blocks_dispatch(self):
        bridge = self.bridge()
        with patch.object(native, "implementation_digest", return_value="d" * 64):
            with self.assertRaisesRegex(ValueError, "implementation"):
                bridge.verify()
        with patch.object(native, "inspect_native_sdk", return_value={**self.sdk, "extra": True}):
            with self.assertRaisesRegex(ValueError, "SDK"):
                bridge.verify()

    def test_timeout_marks_recovery_and_stops_cohort(self):
        bridge = self.bridge()
        request = self.request(bridge)
        with patch.object(native, "run_worker", side_effect=TimeoutError("synthetic timeout")) as runner:
            with self.assertRaises(TimeoutError):
                bridge.construct(request)
            self.assertTrue((self.coordination.data_dir / "native_recovery_required.json").exists())
            self.assertTrue((self.coordination.data_dir / "eval-native/cohorts/synthetic-cohort/dispatch_stopped.json").exists())
            with self.assertRaisesRegex(ValueError, "marker"):
                bridge.construct(request)
            self.assertEqual(runner.call_count, 1)
        receipt = native.read_json(bridge.stage / "construct/receipt.json")
        self.assertFalse(receipt["cleanup_verified"])
        self.assertEqual(receipt["status"], "failed")

    def test_cleanup_confirmed_failure_still_stops_cohort_without_recovery_claim(self):
        bridge = self.bridge()
        def fail(path, digest):
            journal = NativeJournal(path.parent / "native_journal.json")
            journal.value.update(status="failed", cleanup_verified=True, error="synthetic failure")
            journal.flush()
            return 1
        with patch.object(native, "run_worker", side_effect=fail):
            with self.assertRaisesRegex(ValueError, "worker"):
                bridge.construct(self.request(bridge))
        self.assertFalse((self.coordination.data_dir / "native_recovery_required.json").exists())
        self.assertTrue((self.coordination.data_dir / "eval-native/cohorts/synthetic-cohort/dispatch_stopped.json").exists())
        self.manifest["fixture_id"] = "second-fixture"
        self.save_manifest()
        second = self.bridge()
        with self.assertRaisesRegex(ValueError, "cohort"):
            second.construct(self.request(second))

    def test_group_and_network_clipboard_plan_preserves_meaningful_identity(self):
        self.dfx = self.dfx.replace('COMPONENT_TYPE=synthetic_gain',
            'COMPONENT_TYPE=GROUP\n0 0 0 0 0\nCOMPONENT_TYPE=synthetic_gain').replace(
            'COMPONENT_TYPE=WIRE', 'GROUP-END:\nCOMPONENT_TYPE=WIRE')
        self.write_source()
        self.manifest.update(task_id="EVAL-N10", strategy="clipboard", source_sha256=sha256_file(self.source),
                             files={self.source.name: sha256_file(self.source)})
        self.save_manifest()
        bridge = self.bridge()
        request = self.request(bridge)
        self.assertTrue(request["plan"]["groups"])
        self.assertNotIn("parameters", request["plan"]["components"][0])
        self.assertIn("stored_parameters_sha256", request["plan"]["components"][0])
        with patch.object(native, "run_worker", side_effect=self.synthetic_worker):
            result = bridge.construct(request)
        self.assertTrue(result["native_evidence"]["grouped_source_readback_count"])
        self.manifest.update(task_id="EVAL-N04", fixture_id="network")
        self.save_manifest()
        self.assertEqual(self.bridge().inspect()["plan"]["strategy"], "clipboard")

    def test_worker_rejects_wrong_job_hash_before_sdk(self):
        job = self.data / "wrong-job.json"
        job.write_text('{}')
        with self.assertRaisesRegex(ValueError, "job hash"):
            native.worker_main(job, "0" * 64)

    def test_coordination_lock_and_unknown_tool_block_without_attempt(self):
        bridge = self.bridge()
        request = self.request(bridge)
        self.coordination.data_dir.mkdir()
        lock = self.coordination.data_dir / 'execution.lock'
        lock.write_text('operator-owned lock')
        with patch.object(native, 'run_worker') as runner:
            with self.assertRaises(PermissionError):
                bridge.construct(request)
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                bridge.dispatch('compile_project', {})
            runner.assert_not_called()
        self.assertEqual(lock.read_text(), 'operator-owned lock')
        self.assertFalse(bridge.stage.exists())

    def test_changed_candidate_refuses_compile_before_dispatch(self):
        bridge = self.bridge()
        with patch.object(native, 'run_worker', side_effect=self.synthetic_worker) as runner:
            built = bridge.construct(self.request(bridge))
            candidate = bridge.stage / 'construct/working' / self.source.name
            candidate.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'candidate changed'):
                bridge.compile({'task_id': 'EVAL-N03', 'fixture_id': 'authored',
                    'construction_receipt_sha256': built['receipt_sha256'],
                    'candidate_sha256': built['candidate_sha256']})
            self.assertEqual(runner.call_count, 1)


class CompileApp:
    def __init__(self, fail=None):
        self.fail, self.current, self.compile_count = fail, None, 0
    def connect(self): pass
    def disconnect(self, terminate):
        assert terminate is False
        if self.fail == "disconnect":
            raise RuntimeError("synthetic disconnect failure")
    def get_case(self, file, open_file):
        assert open_file is False
        return self.current
    def open_case(self, path):
        owner = self
        class Case:
            caseid = 12
            file = path
            state = SimpleNamespace(run_state="stopped", modified=False)
            def compile(self):
                owner.compile_count += 1
                if owner.fail == "compile":
                    raise RuntimeError("synthetic native compile failure")
                if owner.fail == "identity":
                    self.file = "different.rtfx"
                return True
            def close(self, force):
                assert force is False
                if owner.fail == "close":
                    return False
                owner.current = None
                return True
        self.current = Case()
        return self.current


class CompileBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eval-native-compile-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.working = self.root / "synthetic.rtfx"
        self.working.write_bytes(b"synthetic")

    def test_compile_failure_retained_and_cleanup_independent(self):
        for failure in (None, "compile", "close", "disconnect", "identity"):
            with self.subTest(failure=failure):
                journal = NativeJournal(self.root / (str(failure) + '.json'))
                app = CompileApp(failure)
                code = native.compile_case(app, self.working, sha256_file(self.working), journal)
                self.assertEqual(code, 0 if failure is None else 1)
                self.assertEqual(app.compile_count, 1)
                self.assertEqual(journal.value["cleanup_verified"], failure in {None, "compile"})
                if failure == "compile":
                    self.assertIn("synthetic native compile failure", journal.value["error"])
                if failure == "identity":
                    self.assertIsNotNone(app.current)

    def test_rpc_compile_requires_exact_owned_durable_single_dispatch(self):
        journal = NativeJournal(self.root / "journal.json")
        journal.value.update(owned_case=12, identity_verified=True,
            native_calls=[{"operation": "compile", "status": "started"}])
        def allowed(path, method, args):
            return native.compile_rpc_allowed(path, method, args, journal, self.working, sha256_file(self.working))
        self.assertTrue(allowed('rscad.case:12', 'compile', []))
        for path, method, args in [('rscad', 'getRacks', []), ('rscad.case:13', 'compile', []),
                                 ('rscad.case:12', 'run', []), ('rscad.case:12', 'loadFlow', []),
                                 ('rscad.case:12', 'saveAs', [str(self.working)]),
                                 ('rscad', 'openCase', ['arbitrary.rtfx'])]:
            self.assertFalse(allowed(path, method, args))
        journal.value["compile_rpc_dispatched"] = True
        self.assertFalse(allowed('rscad.case:12', 'compile', []))

    def test_compile_artifacts_require_success_empty_errors_and_matching_binaries(self):
        build = self.root / 'build_synthetic'
        build.mkdir()
        log = build / 'synthetic.log'
        errors = build / 'synthetic_errs.log'
        log.write_text('Compile completed successfully.')
        errors.write_bytes(b'')
        (build / 'synthetic_r1').write_bytes(b'complete')
        (self.root / 'synthetic_r1').write_bytes(b'complete')
        self.assertEqual(native.verify_compile_artifacts(self.working, 0)['status'], 'verified')
        (self.root / 'synthetic_r1').write_bytes(b'mismatch')
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            native.verify_compile_artifacts(self.working, 0)
        (self.root / 'synthetic_r1').write_bytes(b'complete')
        errors.write_text('error')
        with self.assertRaisesRegex(ValueError, 'nonempty'):
            native.verify_compile_artifacts(self.working, 0)
        errors.write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'freshness'):
            native.verify_compile_artifacts(self.working, 2**63)


if __name__ == "__main__":
    unittest.main()

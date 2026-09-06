"""Harmless Windows children validate atomic ownership and bounded cleanup."""
import test_environment
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from eval_process import EvaluationJob, run_bounded


@unittest.skipUnless(os.name == "nt", "Windows Job Object qualification")
class EvaluationProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="authored-process-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_child(self, code, **kwargs):
        return run_bounded([sys.executable, "-c", code], cwd=str(self.root),
            env=dict(os.environ, PYTHONUTF8="1"), prompt=kwargs.pop("prompt", b""),
            stdout=self.root / "stdout.json", stderr=self.root / "stderr.txt", **kwargs)

    def test_success_unicode_stdin_and_environment(self):
        prompt = "실험 입력 Ω 😀\n".encode()
        result = self.run_child("import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())", prompt=prompt)
        self.assertEqual((self.root / "stdout.json").read_bytes(), prompt)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["job_assigned"])
        self.assertTrue(result["cleanup_verified"])
        self.assertFalse(result["timed_out"])
        self.assertFalse(result["output_limit_exceeded"])

    def test_timeout_cleans_owned_job(self):
        result = self.run_child("import time; time.sleep(30)", timeout=1)
        self.assertTrue(result["timed_out"])
        self.assertTrue(result["cleanup_verified"])
        self.assertTrue(result["job_assigned"])
        self.assertIsNone(result["exit_code"])
        self.assertLess(result["elapsed_seconds"], 10)

    def test_output_overflow_cleans_owned_job(self):
        result = self.run_child("import sys,time; sys.stdout.buffer.write(b'x'*8192); sys.stdout.flush(); time.sleep(30)", max_bytes=1024)
        self.assertTrue(result["output_limit_exceeded"])
        self.assertTrue(result["cleanup_verified"])
        self.assertFalse(result["timed_out"])
        self.assertLess(result["elapsed_seconds"], 10)

    def test_rapid_parent_exit_descendant_is_already_owned(self):
        observed_active = []
        original_finish = EvaluationJob.finish
        def finish(job):
            observed_active.append(job.active())
            return original_finish(job)
        descendant = "from pathlib import Path; import time; Path('ready').write_text('owned'); time.sleep(30)"
        parent = ("import subprocess,sys,time; from pathlib import Path; "
                  f"child=subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
                  "\nwhile not Path('ready').exists(): time.sleep(.005)\n"
                  "print(child.pid,flush=True)\n")
        with patch.object(EvaluationJob, "finish", finish):
            result = self.run_child(parent)
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue(result["cleanup_verified"])
        self.assertGreaterEqual(observed_active[0], 1)
        self.assertTrue((self.root / "ready").exists())
        self.assertGreater(int((self.root / "stdout.json").read_text()), 0)
        self.assertLess(result["elapsed_seconds"], 10)

    def test_attribute_assignment_failure_never_creates_child(self):
        job = EvaluationJob()
        self.addCleanup(job.finish)
        original_update = job.api.UpdateProcThreadAttribute
        def fail_job_attribute(attributes, flags, attribute, *rest):
            if attribute == 0x2000D:
                ctypes.set_last_error(5)
                return 0
            return original_update(attributes, flags, attribute, *rest)
        with tempfile.TemporaryFile() as stream, patch.object(job.api, "UpdateProcThreadAttribute", side_effect=fail_job_attribute), \
                patch.object(job.api, "CreateProcessW", wraps=job.api.CreateProcessW) as create:
            with self.assertRaises(OSError):
                job.spawn([sys.executable, "-c", "raise AssertionError('must not execute')"], cwd=self.root,
                          env=dict(os.environ), stdin=stream, stdout=stream, stderr=stream)
            create.assert_not_called()
        self.assertEqual(job.active(), 0)

    def test_create_failure_has_no_child_and_closes_attribute_handles(self):
        job = EvaluationJob()
        self.addCleanup(job.finish)
        with tempfile.TemporaryFile() as stream, patch.object(job.api, "CreateProcessW", return_value=0), \
                patch.object(job.api, "CloseHandle", wraps=job.api.CloseHandle) as close, \
                patch.object(job.api, "DeleteProcThreadAttributeList", wraps=job.api.DeleteProcThreadAttributeList) as delete:
            ctypes.set_last_error(5)
            with self.assertRaises(OSError):
                job.spawn([sys.executable, "-c", "raise AssertionError('must not execute')"], cwd=self.root,
                          env=dict(os.environ), stdin=stream, stdout=stream, stderr=stream)
            self.assertEqual(close.call_count, 3)
            delete.assert_called_once()
        self.assertEqual(job.active(), 0)


if __name__ == "__main__":
    unittest.main()

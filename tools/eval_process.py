"""Bound a Windows evaluation child and its descendants to one owned job.

No shell is used. This development helper never controls an existing process or
an RSCAD session. A failed ownership assignment is an error, not a fallback.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import tempfile
import time


class StartupInfo(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
        ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR)] + [
        (name, wintypes.DWORD) for name in ("x", "y", "x_size", "y_size", "x_chars", "y_chars", "fill", "flags")] + [
        ("show", wintypes.WORD), ("reserved_size", wintypes.WORD), ("reserved_bytes", ctypes.c_void_p),
        ("stdin", wintypes.HANDLE), ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]


class StartupInfoEx(ctypes.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", ctypes.c_void_p)]


class ProcessInformation(ctypes.Structure):
    _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
                ("pid", wintypes.DWORD), ("thread_id", wintypes.DWORD)]


class OwnedProcess:
    def __init__(self, api, information):
        self.api, self.handle, self.pid = api, information.process, information.pid

    def poll(self):
        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 258:  # WAIT_TIMEOUT
            return None
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        result = wintypes.DWORD()
        if not self.api.GetExitCodeProcess(self.handle, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value

    def wait(self, timeout=10):
        status = self.api.WaitForSingleObject(self.handle, int(timeout * 1000))
        if status == 258:
            raise TimeoutError("Owned evaluation process did not exit")
        if status != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


class EvaluationJob:
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Model evaluation process isolation is qualified on Windows only")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        size = ctypes.c_size_t

        class Limits(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_longlong), ("job_time", ctypes.c_longlong),
                        ("flags", wintypes.DWORD), ("min_ws", size), ("max_ws", size),
                        ("active_limit", wintypes.DWORD), ("affinity", size),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Limits), ("io", Io), ("process_memory", size),
                        ("job_memory", size), ("peak_process", size), ("peak_job", size)]

        class Accounting(ctypes.Structure):
            _fields_ = [(name, ctypes.c_longlong) for name in
                        ("user", "kernel", "period_user", "period_kernel")] + [
                        (name, wintypes.DWORD) for name in ("faults", "total", "active", "terminated")]

        self.Accounting = Accounting
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            "QueryInformationJobObject": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "GetCurrentProcess": ([], wintypes.HANDLE),
            "DuplicateHandle": ([wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE),
                                 wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
            "InitializeProcThreadAttributeList": ([ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(size)], wintypes.BOOL),
            "UpdateProcThreadAttribute": ([ctypes.c_void_p, wintypes.DWORD, size, ctypes.c_void_p, size,
                                          ctypes.c_void_p, ctypes.c_void_p], wintypes.BOOL),
            "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
            "CreateProcessW": ([wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                ctypes.POINTER(StartupInfoEx), ctypes.POINTER(ProcessInformation)], wintypes.BOOL),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        settings = Extended()
        settings.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(settings), ctypes.sizeof(settings)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.api.CloseHandle(self.handle)
            self.handle = None
            raise error

    def spawn(self, command, *, cwd, env, stdin, stdout, stderr):
        """Atomically create the child in this job; failed assignment cannot run it.

        Windows 10+ JOB_LIST and HANDLE_LIST contracts:
        https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
        """
        import msvcrt
        if not isinstance(command, (list, tuple)) or not command or not all(isinstance(x, str) and "\0" not in x for x in command):
            raise ValueError("An explicit argument vector is required")
        executable = Path(command[0])
        if not executable.is_absolute() or executable.suffix.lower() != ".exe" or not executable.is_file():
            raise ValueError("An existing absolute executable path is required")
        if not isinstance(env, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                or not k or "=" in k or "\0" in k or "\0" in v for k, v in env.items()):
            raise ValueError("An explicit valid Unicode environment is required")
        duplicates, attributes_ready = [], False
        attributes = None
        try:
            current = self.api.GetCurrentProcess()
            for stream in (stdin, stdout, stderr):
                target = wintypes.HANDLE()
                if not self.api.DuplicateHandle(current, msvcrt.get_osfhandle(stream.fileno()), current,
                        ctypes.byref(target), 0, True, 2):  # DUPLICATE_SAME_ACCESS
                    raise ctypes.WinError(ctypes.get_last_error())
                duplicates.append(target.value)
            size = ctypes.c_size_t()
            self.api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if not size.value:
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = ctypes.create_string_buffer(size.value)
            if not self.api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            attributes_ready = True
            handles = (wintypes.HANDLE * 3)(*duplicates)
            jobs = (wintypes.HANDLE * 1)(self.handle)
            for attribute, value in ((0x20002, handles), (0x2000D, jobs)):
                if not self.api.UpdateProcThreadAttribute(attributes, 0, attribute, value,
                                                          ctypes.sizeof(value), None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            startup = StartupInfoEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = duplicates
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            information = ProcessInformation()
            command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
            environment = ctypes.create_unicode_buffer("\0".join(f"{key}={env[key]}" for key in sorted(env, key=str.upper)) + "\0\0")
            flags = 0x80000 | 0x400 | 0x08000000  # EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW
            if not self.api.CreateProcessW(str(executable), command_line, None, None, True, flags,
                    environment, str(Path(cwd).absolute()), ctypes.byref(startup), ctypes.byref(information)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.api.CloseHandle(information.thread)
            return OwnedProcess(self.api, information)
        finally:
            if attributes_ready:
                self.api.DeleteProcThreadAttributeList(attributes)
            for handle in duplicates:
                self.api.CloseHandle(handle)

    def active(self):
        value = self.Accounting()
        if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return value.active

    def finish(self):
        if self.handle is None:
            return
        try:
            if self.active() and not self.api.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + 10
            while self.active():
                if time.monotonic() >= deadline:
                    raise RuntimeError("Evaluation child cleanup is unconfirmed")
                time.sleep(0.02)
        finally:
            self.api.CloseHandle(self.handle)
            self.handle = None


def run_bounded(command, *, cwd, env, prompt, stdout, stderr, timeout=240, max_bytes=16 * 1024 * 1024):
    """Record exact child output; timeout/overflow never become a completed run."""
    if not 1 <= timeout <= 600 or not 1024 <= max_bytes <= 32 * 1024 * 1024:
        raise ValueError("Evaluation process limits are out of bounds")
    if not isinstance(prompt, bytes) or len(prompt) > 65536:
        raise ValueError("Bounded UTF-8 prompt bytes required")
    stdout, stderr = Path(stdout), Path(stderr)
    job, child = EvaluationJob(), None
    report = {"exit_code": None, "timed_out": False, "output_limit_exceeded": False,
              "cleanup_verified": False, "job_assigned": False}
    started = time.monotonic()
    try:
        with stdout.open("xb") as output, stderr.open("xb") as errors, tempfile.TemporaryFile() as input_file:
            input_file.write(prompt)
            input_file.seek(0)
            child = job.spawn(command, cwd=cwd, env=env, stdin=input_file, stdout=output, stderr=errors)
            report["pid"] = child.pid
            report["job_assigned"] = True
            while child.poll() is None:
                if stdout.stat().st_size > max_bytes or stderr.stat().st_size > max_bytes:
                    report["output_limit_exceeded"] = True
                    break
                if time.monotonic() - started >= timeout:
                    report["timed_out"] = True
                    break
                time.sleep(0.05)
            report["exit_code"] = child.poll()
    finally:
        try:
            job.finish()
            if child is not None:
                child.wait(timeout=10)
            report["cleanup_verified"] = True
        finally:
            if child is not None:
                child.close()
            report["elapsed_seconds"] = time.monotonic() - started
    report["output_limit_exceeded"] |= stdout.stat().st_size > max_bytes or stderr.stat().st_size > max_bytes
    return report

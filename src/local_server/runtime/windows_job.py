"""Windows child containment using atomic CreateProcess job assignment.

JOB_LIST attaches children before they execute, including the launch/crash window.
The non-inheritable kill-on-close job contains descendants, including Nginx workers.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes as w
from pathlib import Path
from typing import Mapping, Sequence


class _Basic(ctypes.Structure):
    _fields_ = [("ProcessTime", ctypes.c_int64), ("JobTime", ctypes.c_int64),
                ("LimitFlags", w.DWORD), ("MinWorkingSet", ctypes.c_size_t),
                ("MaxWorkingSet", ctypes.c_size_t), ("ActiveLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("Priority", w.DWORD), ("Scheduling", w.DWORD)]


class _IO(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in
                ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


class _Extended(ctypes.Structure):
    _fields_ = [("Basic", _Basic), ("IO", _IO), ("ProcessMemory", ctypes.c_size_t),
                ("JobMemory", ctypes.c_size_t), ("PeakProcess", ctypes.c_size_t),
                ("PeakJob", ctypes.c_size_t)]


class _Accounting(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int64) for name in ("User", "Kernel", "PeriodUser", "PeriodKernel")] + [
        (name, w.DWORD) for name in ("Faults", "Total", "Active", "Terminated")]


class _Startup(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("Reserved", w.LPWSTR), ("Desktop", w.LPWSTR), ("Title", w.LPWSTR),
                *[(name, w.DWORD) for name in ("X", "Y", "Width", "Height", "XChars", "YChars", "Fill", "Flags")],
                ("Show", w.WORD), ("ReservedSize", w.WORD), ("ReservedBytes", ctypes.c_void_p),
                ("Input", w.HANDLE), ("Output", w.HANDLE), ("Error", w.HANDLE)]


class _StartupEx(ctypes.Structure):
    _fields_ = [("Startup", _Startup), ("Attributes", ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("Process", w.HANDLE), ("Thread", w.HANDLE), ("PID", w.DWORD), ("TID", w.DWORD)]


class WindowsProcess:
    """Minimal Popen-compatible process operations on an owned kernel handle."""

    def __init__(self, api: ctypes.WinDLL, handle: int, pid: int, argv: Sequence[str]) -> None:
        self.api, self.handle, self.pid, self.args = api, handle, pid, list(argv)
        self.returncode: int | None = None

    def poll(self) -> int | None:
        """Read actual exit status; STILL_ACTIVE is an exit code, not a liveness test."""
        result = self.api.WaitForSingleObject(self.handle, 0) if self.returncode is None else 0
        if result not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        if self.returncode is None and result == 0:
            code = w.DWORD()
            if not self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.returncode = code.value
            self.api.CloseHandle(self.handle)
            self.handle = None
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        """Wait for the owned handle with subprocess-compatible timeout behavior."""
        if self.returncode is None:
            result = self.api.WaitForSingleObject(self.handle, 0xFFFFFFFF if timeout is None else int(timeout * 1000))
            if result == 258:
                raise subprocess.TimeoutExpired(self.args, timeout)
            if result != 0:
                raise ctypes.WinError(ctypes.get_last_error())
        code = self.poll()
        assert code is not None
        return code

    def terminate(self) -> None:
        """Signal only this owned process; job shutdown handles descendants."""
        if self.poll() is None and not self.api.TerminateProcess(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    kill = terminate


class WindowsJob:
    """Own a non-inheritable job and create processes atomically inside it."""

    def __init__(self) -> None:
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            "InitializeProcThreadAttributeList": ([ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)], w.BOOL),
            "UpdateProcThreadAttribute": ([ctypes.c_void_p, w.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p], w.BOOL),
            "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
            "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, w.BOOL,
                                w.DWORD, ctypes.c_void_p, w.LPCWSTR, ctypes.POINTER(_StartupEx), ctypes.POINTER(_ProcessInfo)], w.BOOL),
            "GetCurrentProcess": ([], w.HANDLE),
            "DuplicateHandle": ([w.HANDLE, w.HANDLE, w.HANDLE, ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "GetExitCodeProcess": ([w.HANDLE, ctypes.POINTER(w.DWORD)], w.BOOL),
            "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
            "QueryInformationJobObject": ([w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.c_void_p], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _Extended()
        limits.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def start(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None,
              log_descriptor: int) -> WindowsProcess:
        """Create a child with JOB_LIST and only explicit standard handles inherited."""
        import msvcrt
        size = ctypes.c_size_t()
        self.api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        attributes = ctypes.create_string_buffer(size.value)
        if not self.api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        inherited = []
        null_descriptor = os.open(os.devnull, os.O_RDONLY)
        try:
            current = self.api.GetCurrentProcess()
            for descriptor in (null_descriptor, log_descriptor):
                duplicate = w.HANDLE()
                if not self.api.DuplicateHandle(current, msvcrt.get_osfhandle(descriptor), current,
                                                ctypes.byref(duplicate), 0, True, 2):
                    raise ctypes.WinError(ctypes.get_last_error())
                inherited.append(duplicate.value)
            jobs = (w.HANDLE * 1)(self.handle)
            handles = (w.HANDLE * len(inherited))(*inherited)
            for key, value in ((0x0002000D, jobs), (0x00020002, handles)):
                if not self.api.UpdateProcThreadAttribute(attributes, 0, key, value, ctypes.sizeof(value), None, None):
                    raise ctypes.WinError(ctypes.get_last_error())
            startup = _StartupEx()
            startup.Startup.cb = ctypes.sizeof(startup)
            startup.Startup.Flags = 0x100  # STARTF_USESTDHANDLES
            startup.Startup.Input = inherited[0]
            startup.Startup.Output = startup.Startup.Error = inherited[1]
            startup.Attributes = ctypes.addressof(attributes)
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
            environment = dict(os.environ if env is None else env)
            block = ctypes.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in
                                                 sorted(environment.items(), key=lambda item: item[0].upper())) + "\0\0")
            process = _ProcessInfo()
            if not self.api.CreateProcessW(argv[0], command, None, None, True,
                    0x00080000 | 0x08000000 | 0x00000400, block, str(cwd), ctypes.byref(startup), ctypes.byref(process)):
                raise ctypes.WinError(ctypes.get_last_error())
            self.api.CloseHandle(process.Thread)
            return WindowsProcess(self.api, process.Process, process.PID, argv)
        finally:
            for handle in inherited:
                self.api.CloseHandle(handle)
            os.close(null_descriptor)
            self.api.DeleteProcThreadAttributeList(attributes)

    def close(self) -> None:
        """Terminate the owned job tree and release its kernel handle."""
        if self.handle:
            if not self.api.TerminateJobObject(self.handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            deadline = time.monotonic() + 5
            while True:
                accounting = _Accounting()
                if not self.api.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None):
                    raise ctypes.WinError(ctypes.get_last_error())
                if not accounting.Active:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Owned process tree has not stopped; package protection retained")
                time.sleep(0.02)
            self.api.CloseHandle(self.handle)
            self.handle = None

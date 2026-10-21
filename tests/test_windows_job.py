"""Real Windows kernel tests using disposable Python child processes only."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from ctypes import wintypes as w
from pathlib import Path


@unittest.skipUnless(sys.platform == "win32", "Windows Job Object APIs")
class WindowsJobTests(unittest.TestCase):
    """Check kernel containment and crash behavior independently of server builds."""

    def test_atomic_creation_and_close_terminate_owned_process(self) -> None:
        from local_server.runtime.windows_job import WindowsJob
        with tempfile.TemporaryDirectory() as folder:
            job = WindowsJob()
            try:
                with (Path(folder) / "output.log").open("wb") as stream:
                    process = job.start([sys.executable, "-c", "import time; time.sleep(60)"],
                                        cwd=Path(folder), env=None, log_descriptor=stream.fileno())
                self.assertIsNone(process.poll())
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.03)
            finally:
                job.close()
            self.assertNotEqual(process.wait(timeout=5), 0)

    def test_parent_crash_kills_child_tree_and_releases_ownership(self) -> None:
        from local_server.runtime.ownership import OwnershipLock
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            status = root / "children.json"
            script = root / "owner.py"
            script.write_text('''
import json, os, subprocess, sys, time
from pathlib import Path
from local_server.runtime.windows_job import WindowsJob
from local_server.runtime.ownership import OwnershipLock
root = Path(sys.argv[1])
lock = OwnershipLock(root / "owner.lock")
job = WindowsJob()
child_code = "import json, os, subprocess, sys, time; from pathlib import Path; grand = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); Path(sys.argv[1]).write_text(json.dumps([os.getpid(), grand.pid])); time.sleep(60)"
with (root / "output.log").open("wb") as log:
    child = job.start([sys.executable, '-c', child_code, str(root / "children.json")], cwd=root, env=None, log_descriptor=log.fileno())
time.sleep(60)
''', encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
            parent = subprocess.Popen([sys.executable, str(script), str(root)], env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=0x08000000)
            api = ctypes.WinDLL("kernel32", use_last_error=True)
            api.OpenProcess.argtypes, api.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
            api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
            api.CloseHandle.argtypes, api.CloseHandle.restype = [w.HANDLE], w.BOOL
            handles = []
            try:
                deadline = time.monotonic() + 10
                children = None
                while time.monotonic() < deadline:
                    if parent.poll() is not None:
                        self.fail(parent.stderr.read().decode(errors="replace"))
                    try:
                        children = json.loads(status.read_text())
                        break
                    except (FileNotFoundError, ValueError):
                        time.sleep(0.02)
                self.assertIsNotNone(children, "Owned children did not start")
                for pid in children:
                    handle = api.OpenProcess(0x100000, False, pid)  # SYNCHRONIZE, never a PID kill
                    self.assertTrue(handle)
                    handles.append(handle)
                with self.assertRaises(OSError):
                    OwnershipLock(root / "owner.lock")
                parent.terminate()  # own Popen handle, simulating an unhandled GUI crash
                parent.wait(timeout=5)
                for handle in handles:
                    self.assertEqual(api.WaitForSingleObject(handle, 5000), 0)
                recovered = OwnershipLock(root / "owner.lock")
                recovered.close()
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.wait(timeout=5)
                parent.stderr.close()
                for handle in handles:
                    api.CloseHandle(handle)


if __name__ == "__main__":
    unittest.main()

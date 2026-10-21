"""Managed-process admission and ownership tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_server.core.paths import AppPaths
from local_server.runtime.processes import ProcessSupervisor


class ProcessSupervisorTests(unittest.TestCase):
    """Only managed binaries may be spawned, without invoking any shell."""

    def setUp(self) -> None:
        """Create isolated test resources."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths(self.root / "data")
        self.paths.ensure()
        self.executable = self.paths.components / "nginx" / "1.0" / "nginx"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"not executed")
        self.supervisor = ProcessSupervisor(self.paths)

    def test_reject_external_program(self) -> None:
        """Launching executable paths outside the private component root is blocked."""
        external = self.root / "outside"
        external.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.supervisor.start("outside", [str(external)], cwd=self.root)

    def test_start_and_stop_owns_child(self) -> None:
        """Managed processes are tracked, logged and terminated explicitly."""
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        with patch(
            "local_server.runtime.processes.subprocess.Popen",
            return_value=fake_process,
        ) as spawn:
            managed = self.supervisor.start(
                "project_1", [str(self.executable), "--foreground"], cwd=self.root
            )
        self.assertTrue(managed.running)
        self.assertEqual(self.supervisor.status("project_1"), "running")
        self.assertFalse(spawn.call_args.kwargs["shell"])
        self.assertTrue(self.supervisor.stop("project_1"))
        fake_process.terminate.assert_called_once()
        self.assertEqual(self.supervisor.status("project_1"), "unmanaged")

    def test_reject_duplicate_owned_name(self) -> None:
        """The supervisor will not overwrite an already tracked live process."""
        fake_process = MagicMock()
        fake_process.poll.return_value = None
        with patch(
            "local_server.runtime.processes.subprocess.Popen",
            return_value=fake_process,
        ):
            self.supervisor.start("first", [str(self.executable)], cwd=self.root)
            with self.assertRaises(RuntimeError):
                self.supervisor.start("first", [str(self.executable)], cwd=self.root)
        self.supervisor.stop_all()


if __name__ == "__main__":
    unittest.main()

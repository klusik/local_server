"""Receipt inventory, removal boundaries, usage guards and worker errors."""

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from local_server.components.catalog import PackageSpec
from local_server.components.installer import ComponentInstaller
from local_server.components.locking import package_lock
from local_server.components.manager import PackageManager, PackageWorker
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore


class Response(io.BytesIO):
    """Bounded in-memory HTTPS response for acquisition tests."""

    def geturl(self) -> str:
        return "https://example.org/package.zip"


class PackageManagerTests(unittest.TestCase):
    """Only complete, unused packages may be removed from the binary root."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths(self.root / "state", self.root / "application")
        self.store = ProjectStore(self.paths.projects_file)
        self.installer = ComponentInstaller(self.paths, PlatformTarget("windows", "x86_64"))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("bin/nginx.exe", b"binary")
        self.archive = buffer.getvalue()
        self.package = PackageSpec("nginx", "1.0.0", "windows", "x86_64", "https://example.org/package.zip", hashlib.sha256(self.archive).hexdigest(), "zip", "bin/nginx.exe")
        self.manager = PackageManager(self.installer, self.store)

    def install(self) -> Path:
        with patch.object(self.installer, "_open", return_value=Response(self.archive)):
            return self.installer.install(self.package)

    def test_only_receipt_backed_complete_versions_are_local(self) -> None:
        self.paths.ensure()
        incomplete = self.paths.components / "nginx" / "untracked"
        incomplete.mkdir(parents=True)
        self.assertEqual(self.manager.inventory(), ())
        self.install()
        self.assertEqual(self.manager.inventory(), (self.package,))

    def test_removal_never_touches_project_or_database_data(self) -> None:
        target = self.install()
        source = self.root / "project"
        source.mkdir()
        (source / "index.php").write_text("<?php")
        data = self.paths.databases / "future-database"
        data.mkdir()
        (data / "keep").write_text("database")
        self.manager.remove(self.package)
        self.assertFalse(target.exists())
        self.assertEqual((source / "index.php").read_text(), "<?php")
        self.assertEqual((data / "keep").read_text(), "database")

    def test_profile_reference_prevents_removal(self) -> None:
        target = self.install()
        self.store.save([ProjectProfile.create("Requested", self.root, server="nginx")])
        with self.assertRaisesRegex(RuntimeError, "Requested"):
            self.manager.remove(self.package)
        self.assertTrue(target.exists())

    def test_usage_reservations_are_reference_counted(self) -> None:
        self.install()
        self.manager.acquire_use(self.package)
        self.manager.acquire_use(self.package)
        self.manager.release_use(self.package)
        with self.assertRaisesRegex(RuntimeError, "in use"):
            self.manager.remove(self.package)
        self.manager.release_use(self.package)
        self.manager.remove(self.package)

    def test_project_root_inside_package_prevents_deletion(self) -> None:
        target = self.install()
        self.store.save([ProjectProfile.create("Inside", target, server="apache")])
        with self.assertRaisesRegex(RuntimeError, "document root"):
            self.manager.remove(self.package)
        self.assertTrue(target.exists())

    def test_package_lock_rejects_second_manager(self) -> None:
        self.paths.ensure()
        with package_lock(self.paths.components):
            with self.assertRaises(RuntimeError):
                with package_lock(self.paths.components):
                    self.fail("concurrent mutation was allowed")

    def test_worker_errors_can_be_retried(self) -> None:
        worker = PackageWorker(self.manager, (self.package,))
        with patch.object(self.installer, "_open", side_effect=OSError("offline")):
            worker.start("download", self.package)
            worker.thread.join(timeout=5)
        events = []
        while not worker.events.empty():
            events.append(worker.events.get_nowait())
        self.assertEqual(events[-1].state, "error")
        self.assertIn("offline", events[-1].details)
        with patch.object(self.installer, "_open", return_value=Response(self.archive)):
            worker.start("download", self.package)
            worker.thread.join(timeout=5)
        events = []
        while not worker.events.empty():
            events.append(worker.events.get_nowait())
        self.assertEqual(events[-1].state, "ready")
        self.assertEqual(events[-1].local, (self.package,))

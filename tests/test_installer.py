"""End-to-end private installer tests with an in-memory HTTPS response."""

import hashlib
import io
import json
import tempfile
import threading
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from local_server.components.catalog import PackageSpec
from local_server.components.installer import (
    RECEIPT,
    ComponentInstaller,
    DownloadCancelled,
    HTTPSOnlyRedirectHandler,
    IntegrityError,
)
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget


class FakeHttpsResponse(io.BytesIO):
    """HTTP-response double for deterministic, network-free installer tests."""

    def geturl(self) -> str:
        """Report the HTTPS location used by the installer.

        Returns:
            str: Fixed HTTPS URL identifying the in-memory response fixture.
        """
        return "https://example.org/nginx.zip"


class InstallerTests(unittest.TestCase):
    """Installs are checksum-gated, private and atomic."""

    def setUp(self) -> None:
        """Create isolated test resources."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths(self.root / "app-data")
        self.target = PlatformTarget("windows", "x86_64")
        self.installer = ComponentInstaller(self.paths, self.target)
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("nginx-1.0/nginx.exe", b"binary")
        self.archive_content = archive_buffer.getvalue()
        self.package = PackageSpec(
            component="nginx",
            version="1.0.0",
            os="windows",
            arch="x86_64",
            url="https://example.org/nginx.zip",
            sha256=hashlib.sha256(self.archive_content).hexdigest(),
            archive="zip",
            entrypoint="nginx.exe",
            strip_components=1,
        )

    def test_install_verified_archive(self) -> None:
        """A digest-checked archive lands in a versioned private folder."""
        with patch.object(
            self.installer,
            "_open",
            return_value=FakeHttpsResponse(self.archive_content),
        ):
            target = self.installer.install(self.package)
        self.assertEqual((target / "nginx.exe").read_bytes(), b"binary")
        self.assertTrue(str(target).startswith(str(self.paths.components)))
        with self.assertRaises(FileExistsError):
            self.installer.install(self.package)

    def test_bad_checksum_keeps_target_absent(self) -> None:
        """Checksum mismatches must leave no installed component behind."""
        bad = replace(self.package, sha256="0" * 64)
        with (
            patch.object(
                self.installer,
                "_open",
                return_value=FakeHttpsResponse(self.archive_content),
            ),
            self.assertRaises(IntegrityError),
        ):
            self.installer.install(bad)
        self.assertFalse(self.installer.installed_path(bad).exists())

    def test_https_downgrade_redirect_is_refused(self) -> None:
        """Redirect handlers must block HTTP before sending downgraded requests."""
        handler = HTTPSOnlyRedirectHandler()
        request = Request("https://example.org/nginx.zip")
        with self.assertRaises(ValueError):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://example.org/nginx.zip"
            )

    def test_wrong_platform_rejected(self) -> None:
        """Packages for other operating systems are never installed."""
        wrong = replace(self.package, os="macos")
        with self.assertRaises(ValueError):
            self.installer.install(wrong)

    def test_receipt_commits_only_after_all_phases(self) -> None:
        """Availability includes a relative receipt and never implies health."""
        phases: list[str] = []

        def progress(state: str, done: int, total: int) -> None:
            """Forward acquisition progress as an immutable worker event.

            Args:
                state (str): Lifecycle state delivered to the main-thread poller.
                done (int): Number of bytes already processed.
                total (int): Total number of bytes expected for the operation.
            """
            phases.append(state)
            if state != "local":
                self.assertFalse(self.installer.installed_path(self.package).exists())

        with patch.object(
            self.installer,
            "_open",
            return_value=FakeHttpsResponse(self.archive_content),
        ):
            target = self.installer.install(self.package, progress=progress)
        self.assertEqual(
            list(dict.fromkeys(phases)),
            ["downloading", "verifying", "extracting", "local"],
        )
        receipt = json.loads((target / RECEIPT).read_text())
        self.assertFalse(receipt["runtime_verified"])
        self.assertNotIn(str(self.root), json.dumps(receipt))
        self.assertEqual(list(self.paths.downloads.iterdir()), [])

    def test_cancel_each_phase_cleans_up_and_can_retry(self) -> None:
        """Cancelled downloads, verification and extraction never become local."""
        for phase in ("downloading", "verifying", "extracting"):
            cancel = threading.Event()

            def progress(state: str, done: int, total: int) -> None:
                """Forward acquisition progress as an immutable worker event.

                Args:
                    state (str): Lifecycle state delivered to the main-thread poller.
                    done (int): Number of bytes already processed.
                    total (int): Total number of bytes expected for the operation.
                """
                if state == phase:
                    cancel.set()

            with (
                self.subTest(phase=phase),
                patch.object(
                    self.installer,
                    "_open",
                    return_value=FakeHttpsResponse(self.archive_content),
                ),
                self.assertRaises(DownloadCancelled),
            ):
                self.installer.install(self.package, cancel=cancel, progress=progress)
            self.assertFalse(self.installer.installed_path(self.package).exists())
            self.assertEqual(list(self.paths.downloads.iterdir()), [])
        with patch.object(
            self.installer,
            "_open",
            return_value=FakeHttpsResponse(self.archive_content),
        ):
            self.installer.install(self.package)

    def test_size_mismatch_rejected_before_availability(self) -> None:
        """A truncated response fails even when a server ends it cleanly."""
        package = replace(self.package, size_bytes=len(self.archive_content) + 1)
        with (
            patch.object(
                self.installer,
                "_open",
                return_value=FakeHttpsResponse(self.archive_content),
            ),
            self.assertRaises(IntegrityError),
        ):
            self.installer.install(package)
        self.assertFalse(self.installer.installed_path(package).exists())

    def test_recovery_deletes_only_owned_staging(self) -> None:
        """Crash recovery leaves unrelated files and persistent data untouched."""
        self.paths.ensure()
        partial = self.paths.downloads / ".install-abandoned"
        partial.mkdir()
        (partial / "binary").write_bytes(b"partial")
        unrelated = self.paths.downloads / "keep.txt"
        unrelated.write_text("keep")
        self.installer.cleanup_incomplete()
        self.assertFalse(partial.exists())
        self.assertEqual(unrelated.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()

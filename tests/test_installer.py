"""End-to-end private installer tests with an in-memory HTTPS response."""

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request

from local_server.components.catalog import PackageSpec
from local_server.components.installer import (
    ComponentInstaller,
    HTTPSOnlyRedirectHandler,
    IntegrityError,
)
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget


class FakeHttpsResponse(io.BytesIO):
    """HTTP-response double for deterministic, network-free installer tests."""

    def geturl(self) -> str:
        """Report the HTTPS location used by the installer."""
        return "https://example.org/nginx.zip"


class InstallerTests(unittest.TestCase):
    """Installs are checksum-gated, private and atomic."""

    def setUp(self) -> None:
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
            self.installer, "_open",
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
        with patch.object(
            self.installer, "_open",
            return_value=FakeHttpsResponse(self.archive_content),
        ), self.assertRaises(IntegrityError):
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


if __name__ == "__main__":
    unittest.main()

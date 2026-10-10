"""Archive traversal, symlink and regular-file extraction tests."""

from __future__ import annotations

import io
import stat
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from local_server.components.archive import ArchiveSafetyError, safe_extract


class ArchiveTests(unittest.TestCase):
    """Untrusted package extraction must never escape its staging directory."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.staging = self.root / "stage"
        self.staging.mkdir()

    def test_extract_zip_strip_root(self) -> None:
        """Normal ZIP archives can discard a single distribution root folder."""
        archive = self.root / "component.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("nginx-1.0/bin/nginx.exe", b"binary")
        safe_extract(archive, self.staging, "zip", strip_components=1)
        self.assertEqual((self.staging / "bin" / "nginx.exe").read_bytes(), b"binary")

    def test_reject_zip_traversal(self) -> None:
        """Parent traversal is rejected before writing any file."""
        archive = self.root / "unsafe.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("../outside.txt", b"escape")
        with self.assertRaises(ArchiveSafetyError):
            safe_extract(archive, self.staging, "zip")
        self.assertFalse((self.root / "outside.txt").exists())

    def test_reject_windows_drive_path(self) -> None:
        """Absolute Windows drive paths must never escape extraction."""
        archive = self.root / "drive.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("C:/windows/system.ini", b"escape")
        with self.assertRaises(ArchiveSafetyError):
            safe_extract(archive, self.staging, "zip")

    def test_reject_zip_symlink(self) -> None:
        """Symlinks in ZIP entries are never written to disk."""
        archive = self.root / "link.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            link = zipfile.ZipInfo("payload/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            writer.writestr(link, "../outside.txt")
        with self.assertRaises(ArchiveSafetyError):
            safe_extract(archive, self.staging, "zip")

    def test_extract_tar_regular_file(self) -> None:
        """Regular tar.gz files extract into a private staging folder."""
        archive = self.root / "component.tar.gz"
        with tarfile.open(archive, "w:gz") as writer:
            content = b"#!/bin/sh\n"
            item = tarfile.TarInfo("pkg/bin/run")
            item.mode = 0o755
            item.size = len(content)
            writer.addfile(item, io.BytesIO(content))
        safe_extract(archive, self.staging, "tar.gz", strip_components=1)
        self.assertEqual((self.staging / "bin" / "run").read_bytes(), content)

    def test_reject_tar_symlink(self) -> None:
        """Tar symlinks are rejected before extraction starts."""
        archive = self.root / "links.tar.gz"
        with tarfile.open(archive, "w:gz") as writer:
            item = tarfile.TarInfo("pkg/link")
            item.type = tarfile.SYMTYPE
            item.linkname = "../../outside"
            writer.addfile(item)
        with self.assertRaises(ArchiveSafetyError):
            safe_extract(archive, self.staging, "tar.gz")


if __name__ == "__main__":
    unittest.main()

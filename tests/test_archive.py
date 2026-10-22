"""Archive traversal, symlink and regular-file extraction tests."""

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
        """Create isolated test resources."""
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

    def test_reject_windows_special_names(self) -> None:
        """Reject Windows device aliases and alternate data stream paths."""
        for index, member in enumerate(
            ("NUL.txt", "dir/file.txt:evil", "dir./file.txt", "COM1/log")
        ):
            with self.subTest(member=member):
                archive = self.root / f"windows-{index}.zip"
                with zipfile.ZipFile(archive, "w") as writer:
                    writer.writestr(member, b"bad")
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

    def test_reject_case_collisions_on_every_host(self) -> None:
        """Archives reviewed on Linux must also be safe on Windows filesystems."""
        for paths in (("BIN/php.exe", "bin/PHP.exe"), ("Bin", "bin/php.exe")):
            archive = self.root / "case.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                for name in paths:
                    writer.writestr(name, b"payload")
            with self.assertRaises(ArchiveSafetyError):
                safe_extract(archive, self.staging, "zip")
            self.assertEqual(list(self.staging.iterdir()), [])

    def test_reject_additional_windows_names(self) -> None:
        """DOS superscript aliases, controls and illegal characters are unsafe."""
        for name in ("COM¹.txt", "LPT²", "a?b", 'a"b', "a\x01b", "NUL .txt"):
            archive = self.root / "name.zip"
            with zipfile.ZipFile(archive, "w") as writer:
                writer.writestr(name, b"payload")
            with self.subTest(name=name), self.assertRaises(ArchiveSafetyError):
                safe_extract(archive, self.staging, "zip")

    def test_cancel_during_large_member(self) -> None:
        """Cancellation is observed between disk writes, not just between files."""
        archive = self.root / "large.zip"
        with zipfile.ZipFile(archive, "w") as writer:
            writer.writestr("large", b"x" * (3 * 1024 * 1024))
        written = 0

        def progress(done: int, total: int) -> None:
            """Forward acquisition progress as an immutable worker event.

            Args:
                done (int): Number of bytes already processed.
                total (int): Total number of bytes expected for the operation.
            """
            nonlocal written
            written = done

        def check() -> None:
            """Abort acquisition promptly after cancellation is requested."""
            if written:
                raise InterruptedError("cancelled")

        with self.assertRaises(InterruptedError):
            safe_extract(archive, self.staging, "zip", check=check, progress=progress)


if __name__ == "__main__":
    unittest.main()

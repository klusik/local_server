"""Pinned app-local MSVC acquisition without SDKs, installers or host changes."""

import hashlib
import io
import json
import struct
import tempfile
import threading
import unittest
import zipfile
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from local_server.components.app_local import RuntimeIntegrityError
from local_server.components.catalog import PackageCatalog, PackageSpec
from local_server.components.installer import (
    RECEIPT,
    ComponentInstaller,
    DownloadCancelled,
)
from local_server.components.manager import PackageManager
from local_server.components.runtime_bundle import RuntimeBundle, RuntimeDLL
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore


def pe_image(machine: int = 0x8664) -> bytes:
    """Minimal data fixture for static header checks, never an executable program.

    Args:
        machine (int): PE machine identifier encoded in the inert test fixture.

    Returns:
        bytes: Inert fixture bytes with the requested PE machine identifier.
    """
    data = bytearray(128)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 64)
    data[64:68] = b"PE\0\0"
    struct.pack_into("<H", data, 68, machine)
    return bytes(data)


class Response(io.BytesIO):
    """Provide a bounded in-memory HTTPS download response fixture."""

    def geturl(self) -> str:
        """Return the fixed HTTPS URL of this in-memory response fixture.

        Returns:
            str: Fixed HTTPS URL identifying the in-memory response fixture.
        """
        return "https://example.org/reviewed.zip"


class AppLocalRuntimeTests(unittest.TestCase):
    """Only a curated, hash-checked DLL set can replace the host-runtime guard."""

    def setUp(self) -> None:
        """Create isolated test resources."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.paths = AppPaths(Path(self.temp.name))
        self.image = pe_image()
        dll_hash = hashlib.sha256(self.image).hexdigest()
        self.dlls = tuple(
            RuntimeDLL("redist/" + name, name, dll_hash)
            for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            for dll in self.dlls:
                z.writestr(dll.source, self.image)
            z.writestr(
                "license.txt", "fixture license, not Microsoft redistributable code"
            )
        self.runtime_zip = buffer.getvalue()
        self.bundle = RuntimeBundle(
            "vc14-fixture-x64",
            "14.51.36247.0",
            "windows",
            "x86_64",
            "https://example.org/reviewed-runtime.zip",
            hashlib.sha256(self.runtime_zip).hexdigest(),
            len(self.runtime_zip),
            "https://example.org/source",
            "Fixture only",
            "https://example.org/license",
            self.dlls,
            ("license.txt",),
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("bin/php-cgi.exe", self.image)
        self.server_zip = buffer.getvalue()
        self.package = PackageSpec(
            "php",
            "8.4.1",
            "windows",
            "x86_64",
            "https://example.org/server.zip",
            hashlib.sha256(self.server_zip).hexdigest(),
            "zip",
            "bin/php-cgi.exe",
            variant="nts-cgi",
            source="https://example.org/source",
            size_bytes=len(self.server_zip),
            vc_minimum="14.44.35211.0",
            runtime_bundle=self.bundle.id,
        )
        self.installer = ComponentInstaller(
            self.paths,
            PlatformTarget("windows", "x86_64"),
            runtime_bundles={self.bundle.id: self.bundle},
        )

    def download_response(self, request: object, **kwargs: object) -> Response:
        """Serve the selected reviewed-archive fixture without network access.

        Args:
            request (object): urllib request whose URL selects the fixture archive.
            kwargs (object): Keyword options forwarded to the underlying Tk button.

        Returns:
            Response: In-memory response containing the requested fixture archive.
        """
        return Response(
            self.runtime_zip if "runtime" in request.full_url else self.server_zip
        )

    def test_acquisition_places_dlls_beside_server_and_keeps_notices(self) -> None:
        """Verify acquisition places dlls beside server and keeps notices."""
        with (
            patch.object(self.installer, "_open", side_effect=self.download_response),
            patch(
                "local_server.components.installer.prerequisite_issues", return_value=[]
            ) as prerequisites,
        ):
            target = self.installer.install(self.package)
        prerequisites.assert_called_once_with(self.package, app_local=True)
        for dll in self.dlls:
            self.assertEqual((target / "bin" / dll.name).read_bytes(), self.image)
        self.assertTrue(
            (
                target
                / "bin"
                / ".local-server-runtime-notices"
                / self.bundle.id
                / "license.txt"
            ).is_file()
        )
        receipt = json.loads((target / RECEIPT).read_text())
        self.assertEqual(receipt["app_local_runtime"]["id"], self.bundle.id)
        self.assertFalse(receipt["runtime_verified"])
        self.assertNotIn(str(self.paths.root), json.dumps(receipt))
        manager = PackageManager(self.installer, ProjectStore(self.paths.projects_file))
        self.assertEqual(manager.inventory(), (self.package,))
        manager.remove(self.package)
        self.assertTrue((self.paths.runtime_cache / self.bundle.id).is_dir())

    def test_modified_dll_hash_blocks_package_commit(self) -> None:
        """Verify modified dll hash blocks package commit."""
        bad = replace(
            self.bundle, files=(replace(self.dlls[0], sha256="a" * 64), *self.dlls[1:])
        )
        self.installer.runtime_bundles[bad.id] = bad
        with (
            patch.object(self.installer, "_open", side_effect=self.download_response),
            patch(
                "local_server.components.installer.prerequisite_issues", return_value=[]
            ),
            self.assertRaises(RuntimeIntegrityError),
        ):
            self.installer.install(self.package)
        self.assertFalse(self.installer.installed_path(self.package).exists())
        self.assertEqual(list(self.paths.downloads.iterdir()), [])

    def test_cancel_during_dependency_download_cleans_partial_files(self) -> None:
        """Verify cancel during dependency download cleans partial files."""
        cancel = threading.Event()

        def progress(state: str, done: int, total: int) -> None:
            """Forward acquisition progress as an immutable worker event.

            Args:
                state (str): Lifecycle state delivered to the main-thread poller.
                done (int): Number of bytes already processed.
                total (int): Total number of bytes expected for the operation.
            """
            if state == "runtime-downloading":
                cancel.set()

        with (
            patch.object(self.installer, "_open", side_effect=self.download_response),
            patch(
                "local_server.components.installer.prerequisite_issues", return_value=[]
            ),
            self.assertRaises(DownloadCancelled),
        ):
            self.installer.install(self.package, cancel=cancel, progress=progress)
        self.assertFalse((self.paths.runtime_cache / self.bundle.id).exists())
        self.assertFalse(self.installer.installed_path(self.package).exists())
        self.assertEqual(list(self.paths.downloads.iterdir()), [])

    def test_catalog_rejects_missing_old_or_wrong_architecture_bundle(self) -> None:
        """Verify catalog rejects missing old or wrong architecture bundle."""
        with self.assertRaises(ValueError):
            PackageCatalog([self.package])
        with self.assertRaises(ValueError):
            PackageCatalog(
                [self.package], [replace(self.bundle, version="14.20.10000.0")]
            )
        with self.assertRaises(ValueError):
            PackageCatalog([self.package], [replace(self.bundle, arch="arm64")])
        catalog = PackageCatalog.from_json(
            json.dumps(
                {
                    "schema_version": 1,
                    "packages": [asdict(self.package)],
                    "runtime_bundles": [asdict(self.bundle)],
                }
            )
        )
        self.assertEqual(catalog.runtime_bundles[self.bundle.id], self.bundle)

    def test_bundle_rejects_system_dlls_and_unpinned_files(self) -> None:
        """Verify bundle rejects system dlls and unpinned files."""
        for dll in (
            replace(self.dlls[0], name="kernel32.dll"),
            replace(self.dlls[0], source="../escape.dll"),
            replace(self.dlls[0], sha256=""),
        ):
            with self.assertRaises(ValueError):
                replace(self.bundle, files=(dll, *self.dlls[1:])).validate()

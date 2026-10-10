"""Secure component-catalog resolution tests."""

from __future__ import annotations

import unittest
from dataclasses import replace

from local_server.components.catalog import PackageCatalog, PackageSpec
from local_server.core.platform import PlatformTarget


class CatalogTests(unittest.TestCase):
    """Package metadata must be deterministic, strict, and checksum pinned."""

    def setUp(self) -> None:
        self.package = PackageSpec(
            component="nginx",
            version="1.30.0",
            os="windows",
            arch="x86_64",
            url="https://example.org/nginx.zip",
            sha256="a" * 64,
            archive="zip",
            entrypoint="nginx.exe",
            strip_components=1,
        )

    def test_bundled_catalog_starts_empty(self) -> None:
        """An intentionally uncurated catalog is never advertised as ready."""
        self.assertEqual(PackageCatalog.bundled().packages, ())

    def test_find_by_component_version_platform(self) -> None:
        """Only the exact platform-specific package may be selected."""
        catalog = PackageCatalog([self.package])
        self.assertEqual(
            catalog.find("nginx", "1.30.0", PlatformTarget("windows", "x86_64")),
            self.package,
        )
        with self.assertRaises(LookupError):
            catalog.find("nginx", "1.30.0", PlatformTarget("macos", "arm64"))

    def test_reject_unverified_package(self) -> None:
        """Invalid checksums and insecure protocols are rejected."""
        for invalid in (
            replace(self.package, url="http://example.org/nginx.zip"),
            replace(self.package, sha256="123"),
            replace(self.package, entrypoint="../../escape"),
            replace(self.package, version="../1.30.0"),
            replace(self.package, strip_components=True),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                invalid.validate()

    def test_reject_duplicate_package(self) -> None:
        """Catalog entries cannot ambiguously shadow another checksum."""
        with self.assertRaises(ValueError):
            PackageCatalog([self.package, self.package])

    def test_reject_unsupported_catalog_schema(self) -> None:
        """Unknown manifest versions fail explicitly."""
        with self.assertRaises(ValueError):
            PackageCatalog.from_json('{"schema_version":2,"packages":[]}')


if __name__ == "__main__":
    unittest.main()

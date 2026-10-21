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
        packages = PackageCatalog.bundled().packages
        self.assertEqual({p.component for p in packages}, {"apache", "nginx", "php", "mysql"})
        self.assertTrue(all(p.source and p.checksum_source and p.license and p.size_bytes > 0 for p in packages))
        self.assertTrue(all((p.os, p.arch) == ("windows", "x86_64") for p in packages))
        self.assertGreaterEqual(sum(p.component == "php" for p in packages), 2)

    def test_windows_php_rejects_incompatible_builds(self) -> None:
        """Windows acquisition cannot mistake FPM or mod_php for FastCGI."""
        for variant in ("ts", "fpm", "default"):
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                replace(self.package, component="php", variant=variant).validate()
        replace(self.package, component="php", variant="nts-cgi").validate()

    def test_identifiers_reject_windows_aliases(self) -> None:
        """Version folders must not become device names or trailing-dot aliases."""
        for version in ("NUL", "COM1.txt", "1.0."):
            with self.subTest(version=version), self.assertRaises(ValueError):
                replace(self.package, version=version).validate()

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

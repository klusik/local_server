"""Domain-profile validation regression tests."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from local_server.core.models import ProjectProfile


class ProjectProfileTests(unittest.TestCase):
    """Verify strict profile validation and stable serialization."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_round_trip(self) -> None:
        """A valid project survives JSON-compatible round trips."""
        original = ProjectProfile.create(
            "Site", self.root, php_version="8.4", http_port=8085, mysql_enabled=True
        )
        self.assertEqual(ProjectProfile.from_dict(original.to_dict()), original)
        self.assertTrue(original.id)

    def test_reject_invalid_php_versions(self) -> None:
        """Versions cannot inject command-line or config fragments."""
        profile = ProjectProfile.create("Site", self.root)
        for unsafe in ("latest", "8.4;rm -rf /", "../8.4", "8.4\nhello", ""):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                replace(profile, php_version=unsafe).validate()

    def test_reject_invalid_ports_and_types(self) -> None:
        """HTTP ports must be numeric, safe, and non-privileged."""
        profile = ProjectProfile.create("Site", self.root)
        for port in (0, 80, 65536, True, "8080"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                replace(profile, http_port=port).validate()

    def test_reject_relative_root(self) -> None:
        """Project paths must be absolute before persisted."""
        profile = ProjectProfile.create("Site", self.root)
        with self.assertRaises(ValueError):
            replace(profile, document_root="../outside").validate()

    def test_reject_invalid_mysql_type(self) -> None:
        """JSON strings must not silently become booleans."""
        profile = ProjectProfile.create("Site", self.root)
        with self.assertRaises(ValueError):
            replace(profile, mysql_enabled="false").validate()


if __name__ == "__main__":
    unittest.main()

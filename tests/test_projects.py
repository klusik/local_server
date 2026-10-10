"""Application-service profile CRUD tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_server.core.store import ProjectStore
from local_server.services.projects import ProjectService


class ProjectServiceTests(unittest.TestCase):
    """Project CRUD must never modify a user's source code directories."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = ProjectService(ProjectStore(self.root / "projects.json"))

    def test_create_switch_php_and_delete(self) -> None:
        """Version selection is persisted and profile removal preserves sources."""
        site_dir = self.root / "site"
        site_dir.mkdir()
        source = site_dir / "index.php"
        source.write_text("<?php echo 'hi';", encoding="utf-8")

        created = self.service.create_project(
            "One", site_dir, php_version="8.2", http_port=8080
        )
        self.service.select_php_version(created.id, "8.4")
        self.assertEqual(self.service.get_project(created.id).php_version, "8.4")
        self.service.delete_project(created.id)
        self.assertTrue(source.exists())
        self.assertEqual(self.service.list_projects(), [])

    def test_reject_missing_document_root(self) -> None:
        """Creating a profile never silently creates the document root."""
        with self.assertRaises(ValueError):
            self.service.create_project("One", self.root / "missing")
        self.assertFalse((self.root / "missing").exists())

    def test_reject_duplicate_http_port(self) -> None:
        """New projects must use unique local ports."""
        self.service.create_project("One", self.root, http_port=8080)
        with self.assertRaises(ValueError):
            self.service.create_project("Two", self.root, http_port=8080)

    def test_delete_unknown_does_not_write(self) -> None:
        """Unknown project IDs fail explicitly."""
        with self.assertRaises(KeyError):
            self.service.delete_project("unrecognized")


if __name__ == "__main__":
    unittest.main()

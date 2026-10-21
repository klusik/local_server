"""Atomic persistence and corrupt-config handling tests."""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from local_server.core.models import ProjectProfile
from local_server.core.store import ConfigurationError, ProjectStore


class ProjectStoreTests(unittest.TestCase):
    """Project storage must preserve valid workspaces and reject corruption."""

    def setUp(self) -> None:
        """Create isolated test resources."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / "state" / "projects.json")

    def test_missing_file_is_first_run(self) -> None:
        """An absent file is an empty workspace, not an error."""
        self.assertEqual(self.store.load(), [])

    def test_save_and_load_round_trip(self) -> None:
        """Serialized profiles are recovered without changing any fields."""
        site = ProjectProfile.create("One", self.root, http_port=8080)
        self.store.save([site])
        self.assertEqual(self.store.load(), [site])
        data = json.loads(self.store.filename.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(list(self.store.filename.parent.glob("*.tmp")), [])

    def test_invalid_json_is_not_overwritten(self) -> None:
        """Corrupt settings are reported and remain available for recovery."""
        self.store.filename.parent.mkdir(parents=True)
        self.store.filename.write_text("{corrupt", encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            self.store.load()
        self.assertEqual(self.store.filename.read_text(encoding="utf-8"), "{corrupt")

    def test_future_schema_is_rejected(self) -> None:
        """Unsupported future schema versions do not load as empty settings."""
        self.store.filename.parent.mkdir(parents=True)
        self.store.filename.write_text(
            '{"schema_version":42,"projects":[]}', encoding="utf-8"
        )
        with self.assertRaises(ConfigurationError):
            self.store.load()

    def test_duplicate_port_cannot_be_saved(self) -> None:
        """Two sites cannot claim the same configured HTTP port."""
        first = ProjectProfile.create("One", self.root, http_port=8080)
        second = ProjectProfile.create("Two", self.root, http_port=8080)
        with self.assertRaises(ValueError):
            self.store.save([first, second])

    def test_duplicate_names_case_insensitive(self) -> None:
        """Case-only duplicate names are rejected across platforms."""
        first = ProjectProfile.create("One", self.root, http_port=8080)
        second = replace(
            ProjectProfile.create("Two", self.root, http_port=8081), name="one"
        )
        with self.assertRaises(ValueError):
            self.store.save([first, second])


if __name__ == "__main__":
    unittest.main()

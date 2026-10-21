"""Portable root resolution and path persistence across folder/drive moves."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths, application_root, default_app_data_dir
from local_server.core.store import ConfigurationError, ProjectStore


class PortablePathsTests(unittest.TestCase):
    """Application location owns defaults; explicit state overrides remain valid."""

    def test_source_root_ignores_working_directory(self) -> None:
        with patch("pathlib.Path.cwd", side_effect=AssertionError("cwd consulted")):
            self.assertEqual(application_root(), Path(__file__).resolve().parents[1])

    def test_frozen_root_uses_executable_not_bundle_resources(self) -> None:
        with patch("sys.frozen", True, create=True), patch("sys.executable", str(Path("/portable/LocalServer/server.exe").resolve())):
            self.assertEqual(application_root(), Path("/portable/LocalServer").resolve())

    def test_mac_app_state_is_next_to_bundle(self) -> None:
        exe = Path("/portable/LocalServer.app/Contents/MacOS/LocalServer").resolve()
        with patch("sys.frozen", True, create=True), patch("sys.executable", str(exe)):
            self.assertEqual(application_root(), Path("/portable").resolve())

    def test_environment_override_requires_absolute_path(self) -> None:
        with patch.dict(os.environ, {"LOCAL_SERVER_HOME": "relative"}):
            with self.assertRaises(ValueError):
                default_app_data_dir()
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {"LOCAL_SERVER_HOME": temp}):
                self.assertEqual(default_app_data_dir(), Path(temp))

    def test_state_override_keeps_packages_next_to_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            paths = AppPaths(base / "external-state", base / "portable-app")
            paths.ensure()
            self.assertEqual(paths.components, base / "portable-app" / "packages")
            self.assertEqual(paths.databases, base / "external-state" / "data")

    def test_internal_root_rebases_after_move(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            app = base / "old"
            site = app / "sites" / "gallery"
            site.mkdir(parents=True)
            store = ProjectStore(app / ".local-server" / "projects.json", portable_root=app)
            project = ProjectProfile.create("Gallery", site)
            store.save([project])
            raw = json.loads(store.filename.read_text())
            self.assertEqual(raw["projects"][0]["document_root"], {"portable": "sites/gallery"})
            self.assertNotIn(str(app), store.filename.read_text())
            moved = base / "new"
            app.rename(moved)
            loaded = ProjectStore(moved / ".local-server" / "projects.json", portable_root=moved).load()[0]
            # Profiles store canonical paths: temp roots can use /var aliases on
            # macOS or short (8.3) user-folder names on Windows CI runners.
            self.assertEqual(loaded.document_root, str((moved / "sites" / "gallery").resolve()))

    def test_external_root_stays_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            store = ProjectStore(base / "app" / "state.json", portable_root=base / "app")
            project = ProjectProfile.create("External", base / "external")
            store.save([project])
            self.assertEqual(store.load()[0], project)
            self.assertIsInstance(json.loads(store.filename.read_text())["projects"][0]["document_root"], str)

    def test_reject_portable_escape(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            store = ProjectStore(app / "projects.json", portable_root=app)
            project = ProjectProfile.create("Site", app).to_dict()
            for root in ({"portable": "../escape"}, {"portable": "C:/escape"}, {"portable": "/escape"}):
                project["document_root"] = root
                store.filename.write_text(json.dumps({"schema_version": 2, "projects": [project]}))
                with self.assertRaises(ConfigurationError):
                    store.load()

    def test_legacy_schema_one_remains_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp)
            store = ProjectStore(app / "projects.json", portable_root=app)
            project = ProjectProfile.create("Legacy", app)
            store.filename.write_text(json.dumps({"schema_version": 1, "projects": [project.to_dict()]}))
            self.assertEqual(store.load(), [project])
            store.save(store.load())
            self.assertEqual(json.loads(store.filename.read_text())["schema_version"], 2)

    def test_unwritable_portable_storage_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with patch("local_server.core.paths.tempfile.TemporaryFile", side_effect=PermissionError("read only")):
                with self.assertRaisesRegex(OSError, "Cannot write to portable storage"):
                    AppPaths(Path(temp)).ensure()

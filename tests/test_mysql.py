"""MySQL data identity, secret boundaries and transactional stack regression tests."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import test_runtime
from local_server.components.installer import RECEIPT
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths
from local_server.runtime.controller import RuntimeController
from local_server.runtime.mysql import MysqlAdapter, mysql_environment, render_mysql_config
from local_server.runtime.ownership import OwnershipLock
from local_server.runtime.ports import PortReservation
from local_server.runtime.secrets import WindowsCredentialStore, restrict_directory


class MysqlControllerTests(unittest.TestCase):
    """Compose MySQL into the existing runtime fixture without executing fake binaries."""

    def setUp(self) -> None:
        test_runtime.RuntimeTests.setUp(self)
        self.mysql = replace(self.php, component="mysql", variant="community", version="8.4.13",
                             entrypoint="bin/mysqld.exe")
        directory = self.installer.installed_path(self.mysql)
        (directory / "bin").mkdir(parents=True)
        for filename in ("mysqld.exe", "mysql.exe", "mysqladmin.exe"):
            (directory / "bin" / filename).write_bytes(b"test only")
        (directory / RECEIPT).write_text(json.dumps({"schema_version": 1, "runtime_verified": False,
                                                   "package": asdict(self.mysql)}))
        extensions = self.installer.installed_path(self.php) / "ext"
        extensions.mkdir()
        for filename in ("php_mysqli.dll", "php_pdo_mysql.dll"):
            (extensions / filename).write_bytes(b"test only")
        self.project = replace(self.project, mysql_enabled=True, mysql_package=self.mysql.key, mysql_port=3307)
        self.adapter_patch = patch("local_server.runtime.controller.MysqlAdapter")
        self.adapter = self.adapter_patch.start().return_value
        self.adapter.process.running = True
        self.addCleanup(self.adapter_patch.stop)

    def test_mysql_starts_before_php_and_is_leased_until_shutdown(self) -> None:
        self.controller.start(self.project)
        self.adapter.start.assert_called_once()
        self.assertIn(self.mysql.key, self.manager._leases)
        ini = (self.paths.project_config_dir(self.project.id) / "php.ini").read_text()
        self.assertIn("extension=mysqli", ini)
        self.assertIn("extension=pdo_mysql", ini)
        self.controller.stop(self.project.id)
        self.adapter.stop.assert_called_once()
        self.assertFalse(self.manager._leases)

    def test_enabled_legacy_profile_requires_explicit_mysql_selection(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact"):
            self.controller.start(replace(self.project, mysql_package=None))
        self.supervisor.start.assert_not_called()

    def test_wrong_mysql_variant_and_missing_php_extension_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.controller.start(replace(self.project, mysql_package=self.mysql.key.replace("community", "debug")))
        extension = self.installer.installed_path(self.php) / "ext" / "php_mysqli.dll"
        extension.unlink()
        with self.assertRaisesRegex(ValueError, "extensions"):
            self.controller.start(self.project)
        self.adapter.start.assert_not_called()
        self.assertFalse(self.manager._leases)

    def test_failed_database_rolls_back_and_never_starts_php(self) -> None:
        self.adapter.start.side_effect = RuntimeError("SQL not verified")
        with self.assertRaisesRegex(RuntimeError, "SQL not verified"):
            self.controller.start(self.project)
        self.supervisor.start.assert_not_called()
        self.adapter.stop.assert_called_once()
        self.assertFalse(self.manager._leases)

    def test_failed_http_php_sql_rolls_back_database_too(self) -> None:
        self.controller._probe_http.side_effect = RuntimeError("PHP SQL probe failed")
        with self.assertRaisesRegex(RuntimeError, "PHP SQL"):
            self.controller.start(self.project)
        self.adapter.stop.assert_called_once()
        self.assertFalse(self.controller.runs)

    def test_database_crash_stops_stack_and_releases_leases(self) -> None:
        self.controller.start(self.project)
        self.adapter.process.running = False
        self.assertEqual(self.controller.monitor()[0].state, "error")
        self.assertFalse(self.manager._leases)

    def test_authenticated_sql_failure_is_monitored(self) -> None:
        self.controller.start(self.project)
        self.adapter.probe.side_effect = OSError("wrong password")
        self.assertEqual(self.controller.monitor(), [])
        self.assertEqual(self.controller.monitor(), [])
        self.assertEqual(self.controller.monitor()[0].state, "error")

    def test_exact_selection_guard_allows_other_mysql_version_removal(self) -> None:
        self.store.save([self.project])
        other = replace(self.mysql, version="8.4.12")
        directory = self.installer.installed_path(other)
        (directory / "bin").mkdir(parents=True)
        (directory / other.entrypoint).write_bytes(b"not executed")
        (directory / RECEIPT).write_text(json.dumps({"schema_version": 1, "runtime_verified": False,
                                                   "package": asdict(other)}))
        self.manager.remove(other)
        with self.assertRaisesRegex(RuntimeError, "requested"):
            self.manager.remove(self.mysql)

    def test_connection_password_requires_explicit_reveal(self) -> None:
        self.controller.start(self.project)
        self.controller.connection(self.project.id)
        self.adapter.connection.assert_called_with(reveal=False)
        self.controller.connection(self.project.id, reveal=True)
        self.adapter.connection.assert_called_with(reveal=True)


class MysqlAdapterTests(unittest.TestCase):
    """Exercise real data/lease files, with OS secrets and MySQL execution mocked."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = AppPaths(self.root / "state", self.root)
        self.paths.ensure()
        self.project = ProjectProfile.create("SQL", self.root / "site", mysql_enabled=True)
        from local_server.components.catalog import PackageCatalog
        self.package = next(p for p in PackageCatalog.bundled().packages if p.component == "mysql")
        self.vault = MagicMock()
        self.vault.get.return_value = {"root": "A" * 48, "project": "B" * 48}
        self.supervisor = MagicMock()
        self.adapter = MysqlAdapter(self.paths, self.project, self.package, self.root / "packages" / "mysql",
                                    self.supervisor, threading.Event(), vault=self.vault)
        self.acl = patch("local_server.runtime.mysql.restrict_directory")
        self.acl.start()
        self.addCleanup(self.acl.stop)
        self.addCleanup(self.adapter.stop)
        self.server_uuid = str(uuid.uuid4())

    def _existing(self, **changes: object) -> None:
        self.adapter.directory.mkdir()
        data = self.adapter.directory / "datadir"
        data.mkdir()
        for filename in ("auto.cnf", "ibdata1", "mysql.ibd"):
            (data / filename).write_text("existing user database")
        identity = {"schema": 1, "project": self.project.id, "package": self.package.key,
                    "credential": str(uuid.uuid4()), "server_uuid": self.server_uuid, "state": "ready"}
        identity.update(changes)
        (self.adapter.directory / "identity.json").write_text(json.dumps(identity))

    def test_profile_defaults_are_backward_compatible_and_validate_port(self) -> None:
        record = self.project.to_dict()
        del record["mysql_package"], record["mysql_port"]
        self.assertIsNone(ProjectProfile.from_dict(record).mysql_package)
        self.assertTrue(ProjectProfile.from_dict(record).mysql_enabled)
        for port in (True, "3307", 80, 65536, self.project.http_port):
            with self.subTest(port=port), self.assertRaises(ValueError):
                replace(self.project, mysql_port=port).validate()

    def test_unknown_empty_directory_is_not_initialized_or_deleted(self) -> None:
        self.adapter.directory.mkdir()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            self.adapter.start()
        self.assertTrue(self.adapter.directory.is_dir())
        self.supervisor.start.assert_not_called()

    def test_incompatible_version_or_project_preserves_bytes(self) -> None:
        self._existing(package=self.package.key.replace("8.4.13", "8.4.12"))
        before = (self.adapter.directory / "datadir" / "mysql.ibd").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "original exact"):
            self.adapter.start()
        self.assertEqual((self.adapter.directory / "datadir" / "mysql.ibd").read_bytes(), before)
        self.supervisor.start.assert_not_called()

    def test_missing_secret_on_new_computer_never_reinitializes(self) -> None:
        self._existing()
        self.vault.get.side_effect = RuntimeError("credentials unavailable")
        with self.assertRaisesRegex(RuntimeError, "credentials unavailable"):
            self.adapter.start()
        self.assertTrue((self.adapter.directory / "datadir" / "mysql.ibd").exists())
        self.vault.put.assert_not_called()

    def test_same_datadir_is_locked_across_different_package_roots(self) -> None:
        filename = self.paths.databases / (self.project.id + ".lock")
        held = OwnershipLock(filename)
        try:
            with self.assertRaisesRegex(RuntimeError, "another"):
                self.adapter.start()
        finally:
            held.close()

    def test_port_conflict_does_not_initialize_or_signal_processes(self) -> None:
        held = PortReservation(self.project.mysql_port)
        try:
            with self.assertRaisesRegex(RuntimeError, "occupied"):
                self.adapter.start()
        finally:
            held.close()
        self.supervisor.start.assert_not_called()
        self.supervisor.stop.assert_not_called()
        self.vault.put.assert_not_called()

    def test_cancellation_discards_only_new_transaction(self) -> None:
        def cancel() -> None:
            self.adapter.cancelled.set()
            self.adapter._cancel()
        with patch.object(self.adapter, "_initialize", side_effect=cancel):
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.adapter.start()
        self.assertFalse(self.adapter.directory.exists())
        self.vault.delete.assert_called_once()
        self.assertIsNone(self.adapter.lock)

    def test_existing_database_is_preserved_on_startup_failure(self) -> None:
        self._existing()
        with patch.object(self.adapter, "_launch", side_effect=RuntimeError("loader")):
            with self.assertRaisesRegex(RuntimeError, "loader"):
                self.adapter.start()
        self.assertTrue((self.adapter.directory / "datadir" / "mysql.ibd").exists())
        self.vault.delete.assert_not_called()

    def test_sql_probe_checks_version_uuid_database_and_authentication(self) -> None:
        self.adapter.identity = {"server_uuid": self.server_uuid}
        good = f"1|{self.package.version}|{self.server_uuid}|{self.adapter.database}"
        for output in ("1", good.replace(self.package.version, "8.4.12"),
                       good.replace(self.server_uuid, str(uuid.uuid4())), good.replace(self.adapter.database, "other")):
            with patch.object(self.adapter, "_client", return_value=output), self.assertRaises(OSError):
                self.adapter.probe()
        with patch.object(self.adapter, "_client", return_value=good):
            self.adapter.probe()
        with patch.object(self.adapter, "_client", side_effect=OSError("wrong password")), self.assertRaises(OSError):
            self.adapter.probe()

    def test_shutdown_authenticates_before_admin_shutdown_and_force_cleanup(self) -> None:
        self.adapter.process = MagicMock()
        self.adapter.process.running = True
        with patch.object(self.adapter, "probe") as probe, patch.object(self.adapter, "_client") as client:
            self.adapter._shutdown()
        probe.assert_called_once_with(admin=True)
        client.assert_called_once_with(admin=True, shutdown=True)
        self.supervisor.stop.assert_called_once_with(self.adapter.name)

    def test_identity_mismatch_cannot_shutdown_another_server(self) -> None:
        self.adapter.process = MagicMock()
        self.adapter.process.running = True
        with patch.object(self.adapter, "probe", side_effect=OSError("wrong uuid")), \
             patch.object(self.adapter, "_client") as client:
            self.adapter._shutdown()
        client.assert_not_called()
        self.supervisor.stop.assert_called_once_with(self.adapter.name)

    def test_first_initialization_promotes_only_after_sql_and_graceful_stop(self) -> None:
        init = self.supervisor.start.return_value
        init.running = False
        init.handle.wait.return_value = 0
        calls = []
        def launch(data: Path, *, bootstrap: bool = False) -> None:
            calls.append(bootstrap)
            if bootstrap:
                data.mkdir()
                for filename in ("auto.cnf", "ibdata1", "mysql.ibd"):
                    (data / filename).write_text("new database")
                self.adapter.identity["server_uuid"] = self.server_uuid
        with patch.object(self.adapter, "_launch", side_effect=launch), patch.object(self.adapter, "_shutdown"):
            self.adapter.start()
        self.assertEqual(calls, [True, False])
        identity = json.loads((self.adapter.directory / "identity.json").read_text())
        self.assertEqual(identity["state"], "ready")
        self.assertTrue((self.adapter.directory / "datadir" / "mysql.ibd").exists())
        self.assertFalse(list(Path(self.adapter.private.name).iterdir()))
        self.assertNotIn("password", json.dumps(identity))
        self.adapter.stop()
        with patch.object(self.adapter, "_initialize") as initialize, patch.object(self.adapter, "_launch"):
            self.adapter.start()
        initialize.assert_not_called()

    def test_account_password_sql_is_input_file_and_never_argv_or_general_logs(self) -> None:
        self.adapter.config.mkdir(parents=True)
        self.adapter.private = tempfile.TemporaryDirectory(dir=self.adapter.config)
        self.adapter.passwords = {"root": "A" * 48, "project": "B" * 48}
        secret = "C" * 48
        def spawn(name: str, argv: list[str], **kwargs: object) -> MagicMock:
            self.assertNotIn(secret, " ".join(argv))
            self.assertNotIn("A" * 48, " ".join(argv))
            self.assertIn(secret, Path(kwargs["private_input"]).read_text())
            Path(kwargs["private_log"]).write_text("1\n")
            result = MagicMock()
            result.handle.wait.return_value = 0
            return result
        self.supervisor.start.side_effect = spawn
        self.assertEqual(self.adapter._client(admin=True, sql=f"CREATE USER 'test' IDENTIFIED BY '{secret}';"), "1")
        self.assertFalse(list(Path(self.adapter.private.name).iterdir()))

    def test_database_and_user_names_reject_sql_injection_and_system_schemas(self) -> None:
        for name in ("mysql", "root", "sys", "information_schema", "a'; DROP DATABASE x;", "../data", "a%", "a_b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.adapter.create_database(name)
        self.supervisor.start.assert_not_called()

    def test_created_account_gets_only_database_grants_and_random_vault_secret(self) -> None:
        self.adapter.directory.mkdir()
        inventory = {"databases": ["gallery"], "accounts": []}
        with patch.object(self.adapter, "databases", return_value=inventory), patch.object(self.adapter, "_client") as client:
            self.adapter.create_user("gallery", "galleryuser")
        sql = client.call_args.kwargs["sql"]
        self.assertIn("ON `gallery`.*", sql)
        self.assertNotIn("ON *.*", sql)
        self.assertNotIn("GRANT OPTION", sql)
        passwords = self.vault.put.call_args.args[1]
        self.assertGreaterEqual(len(passwords["password"]), 48)
        record = json.loads((self.adapter.directory / "accounts.json").read_text())[0]
        self.assertEqual(record["state"], "ready")
        self.assertNotIn(passwords["password"], (self.adapter.directory / "accounts.json").read_text())

    def test_partial_account_creation_keeps_secret_and_does_not_drop_data(self) -> None:
        self.adapter.directory.mkdir()
        with patch.object(self.adapter, "databases", return_value={"databases": ["gallery"], "accounts": []}), \
             patch.object(self.adapter, "_client", side_effect=OSError("SQL failed")):
            with self.assertRaisesRegex(RuntimeError, "preserved"):
                self.adapter.create_user("gallery", "galleryuser")
        record = json.loads((self.adapter.directory / "accounts.json").read_text())[0]
        self.assertEqual(record["state"], "creating")
        self.vault.delete.assert_not_called()

    def test_failed_client_cleanup_retains_data_lease_until_retry(self) -> None:
        filename = self.paths.databases / (self.project.id + ".lock")
        self.adapter.lock = OwnershipLock(filename)
        self.adapter.transients.add("mysql-client-" + self.project.id)
        self.supervisor.stop.side_effect = OSError("Client has not stopped")
        with self.assertRaisesRegex(OSError, "not stopped"):
            self.adapter.stop()
        with self.assertRaises(OSError):
            OwnershipLock(filename)
        self.supervisor.stop.side_effect = None
        self.adapter.stop()
        self.assertIsNone(self.adapter.lock)

    def test_config_is_loopback_only_and_disables_secondary_listeners(self) -> None:
        text = render_mysql_config(self.root / "package space", self.root / "data space", self.root, 3307)
        for option in ("bind-address=127.0.0.1", "mysqlx=0", "named-pipe=OFF", "shared-memory=OFF",
                       "persisted-globals-load=OFF", "upgrade=NONE", "skip-log-bin"):
            self.assertIn(option, text)
        self.assertNotIn("admin-address", text)
        self.assertNotIn("0.0.0.0", text)
        with patch.dict(os.environ, {"MYSQL_PWD": "secret", "MYSQL_HOME": "bad"}):
            self.assertNotIn("MYSQL_PWD", mysql_environment())


@unittest.skipUnless(os.name == "nt" and os.environ.get("LOCAL_SERVER_TEST_VAULT") == "1",
                     "Explicit Windows user-vault integration test")
class WindowsVaultTests(unittest.TestCase):
    """Use only a newly generated credential target and disposable ACL directory."""

    def test_vault_and_private_acl_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            restrict_directory(Path(directory))
            vault = WindowsCredentialStore()
            reference = str(uuid.uuid4())
            passwords = {"root": "A" * 48, "project": "B" * 48}
            try:
                vault.put(reference, passwords)
                self.assertEqual(vault.get(reference), passwords)
            finally:
                vault.delete(reference)
            with self.assertRaisesRegex(RuntimeError, "unavailable"):
                vault.get(reference)

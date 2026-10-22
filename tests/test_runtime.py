"""Runtime transaction, ownership, diagnostics and portable path regression tests."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from local_server.components.catalog import PackageSpec
from local_server.components.installer import RECEIPT, ComponentInstaller
from local_server.components.locking import rename_directory
from local_server.components.manager import PackageManager
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore
from local_server.runtime.controller import RuntimeController, RuntimeWorker
from local_server.runtime.nginx import render_nginx_config
from local_server.runtime.ownership import OwnershipLock
from local_server.runtime.php import php_environment, render_php_ini
from local_server.runtime.ports import PortReservation


class RuntimeTests(unittest.TestCase):
    """Exercise real filesystem/lease boundaries with mocked process execution."""

    def setUp(self) -> None:
        """Create isolated test resources."""
        self.temp = tempfile.TemporaryDirectory(prefix="runtime space ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paths = AppPaths(
            self.root / "application" / "state", self.root / "application"
        )
        self.paths.ensure()
        self.store = ProjectStore(self.paths.projects_file)
        self.installer = ComponentInstaller(
            self.paths, PlatformTarget("windows", "x86_64")
        )
        self.manager = PackageManager(self.installer, self.store)
        self.nginx = PackageSpec(
            "nginx",
            "1.0.0",
            "windows",
            "x86_64",
            "https://example.org/nginx.zip",
            "a" * 64,
            "zip",
            "nginx.exe",
        )
        self.php = replace(
            self.nginx,
            component="php",
            version="8.4.1",
            variant="nts-cgi",
            entrypoint="php-cgi.exe",
        )
        for package in (self.nginx, self.php):
            directory = self.installer.installed_path(package)
            directory.mkdir(parents=True)
            (directory / package.entrypoint).write_bytes(b"test only; never executed")
            (directory / RECEIPT).write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "runtime_verified": False,
                        "package": asdict(package),
                    }
                )
            )
        conf = self.installer.installed_path(self.nginx) / "conf"
        conf.mkdir()
        for name in ("mime.types", "fastcgi_params"):
            (conf / name).write_text("# test only")
        site = self.root / "user site"
        site.mkdir()
        (site / "index.php").write_text("<?php echo 'user source';")
        port = PortReservation()
        self.project = ProjectProfile.create(
            "Test",
            site,
            http_port=port.port,
            php_version=self.php.version,
            nginx_package=self.nginx.key,
            php_package=self.php.key,
        )
        port.close()
        self.supervisor = MagicMock()
        self.supervisor.status.return_value = "running"
        self.supervisor.start.return_value.handle.wait.return_value = 0
        self.controller = RuntimeController(
            self.paths, self.manager, self.installer.target, self.supervisor
        )
        self.addCleanup(self.controller.close)
        self.prerequisites = patch(
            "local_server.runtime.controller.prerequisite_issues", return_value=[]
        )
        self.prerequisites.start()
        self.addCleanup(self.prerequisites.stop)
        self.fcgi = patch("local_server.runtime.controller.probe_fastcgi")
        self.fcgi.start()
        self.addCleanup(self.fcgi.stop)
        self.http = patch.object(self.controller, "_probe_http")
        self.http.start()
        self.addCleanup(self.http.stop)
        self.listener = patch.object(self.controller, "_probe_listener")
        self.listener.start()
        self.addCleanup(self.listener.stop)

    def test_start_validates_and_probes_before_running_then_stops(self) -> None:
        """Verify start validates and probes before running then stops."""
        self.controller.start(self.project)
        run = self.controller.runs[self.project.id]
        self.assertTrue(run.healthy)
        calls = self.supervisor.start.call_args_list
        self.assertEqual(
            [call.args[0].split("-")[0] for call in calls], ["php", "validate", "nginx"]
        )
        self.assertIn("-t", calls[1].args[1])
        self.assertTrue(all(call.kwargs["contain"] for call in calls))
        self.assertIn("127.0.0.1:", " ".join(calls[0].args[1]))
        self.assertFalse(
            any(
                name.name.startswith("diagnostic")
                for name in Path(self.project.document_root).iterdir()
            )
        )
        self.controller.stop(self.project.id)
        self.assertFalse(self.controller.runs)
        self.assertFalse(self.manager._leases)
        self.assertFalse(
            list(self.paths.project_config_dir(self.project.id).glob("diagnostic-*"))
        )
        self.assertEqual(
            (Path(self.project.document_root) / "index.php").read_text(),
            "<?php echo 'user source';",
        )

    def test_failed_nginx_validation_rolls_back_php_and_leases(self) -> None:
        """Verify failed nginx validation rolls back php and leases."""
        self.supervisor.start.return_value.handle.wait.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "validation"):
            self.controller.start(self.project)
        self.assertFalse(self.controller.runs)
        self.assertFalse(self.manager._leases)
        self.supervisor.stop.assert_any_call("php-" + self.project.id)
        self.assertEqual(self.supervisor.start.call_count, 2)

    def test_failed_http_probe_rolls_back_both_children(self) -> None:
        """Verify failed http probe rolls back both children."""
        self.controller._probe_http.side_effect = RuntimeError("diagnostic failed")
        with self.assertRaisesRegex(RuntimeError, "diagnostic"):
            self.controller.start(self.project)
        self.supervisor.stop.assert_any_call("nginx-" + self.project.id)
        self.supervisor.stop.assert_any_call("php-" + self.project.id)
        self.assertFalse(self.controller.runs)

    def test_process_creation_failure_releases_all_reservations(self) -> None:
        """Verify process creation failure releases all reservations."""
        self.supervisor.start.side_effect = OSError("loader failed")
        with self.assertRaisesRegex(OSError, "loader failed"):
            self.controller.start(self.project)
        self.assertFalse(self.controller.runs)
        self.assertFalse(self.manager._leases)
        again = PortReservation(self.project.http_port)
        again.close()

    def test_nginx_creation_failure_rolls_back_prepared_php(self) -> None:
        """Verify nginx creation failure rolls back prepared php."""
        handle = MagicMock()
        handle.handle.wait.return_value = 0

        def start(name: str, *args: object, **kwargs: object) -> MagicMock:
            """Simulate creation of an owned runtime process.

            Args:
                name (str): Logical child-process name used for ownership and log
                    lookup.
                args (object): Literal child-process arguments accepted by the simulated
                    supervisor.
                kwargs (object): Keyword options forwarded to the underlying Tk button.

            Returns:
                MagicMock: Handle wrapper for the directly owned child process.
            """
            if name.startswith("nginx-"):
                raise OSError("Nginx spawn failed")
            return handle

        self.supervisor.start.side_effect = start
        with self.assertRaisesRegex(OSError, "spawn failed"):
            self.controller.start(self.project)
        self.supervisor.stop.assert_any_call("php-" + self.project.id)
        self.assertFalse(self.manager._leases)

    def test_closing_cancels_a_pending_health_check_and_rolls_back(self) -> None:
        """Verify closing cancels a pending health check and rolls back."""
        with patch("local_server.runtime.controller.probe_fastcgi") as probe:
            # Make the first probe fail after signalling cancellation.
            def cancel(*args: object) -> None:
                """Trigger cancellation at the selected worker checkpoint.

                Args:
                    args (object): Literal child-process arguments accepted by the
                        simulated supervisor.
                """
                self.controller.cancelled.set()
                raise OSError("not ready")

            probe.side_effect = cancel
            with self.assertRaisesRegex(RuntimeError, "cancelled"):
                self.controller.start(self.project)
        self.assertFalse(self.controller.runs)
        self.assertFalse(self.manager._leases)

    def test_unsupported_platform_never_spawns(self) -> None:
        """Verify unsupported platform never spawns."""
        self.controller.target = PlatformTarget("macos", "arm64")
        with self.assertRaisesRegex(ValueError, "Windows x64"):
            self.controller.start(self.project)
        self.supervisor.start.assert_not_called()

    def test_port_collision_does_not_spawn_or_kill_foreign_processes(self) -> None:
        """Verify port collision does not spawn or kill foreign processes."""
        held = PortReservation(self.project.http_port)
        self.addCleanup(held.close)
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            self.controller.start(self.project)
        self.supervisor.start.assert_not_called()
        self.supervisor.stop.assert_not_called()
        self.assertFalse(self.manager._leases)

    def test_duplicate_start_and_other_instance_are_rejected(self) -> None:
        """Verify duplicate start and other instance are rejected."""
        self.controller.start(self.project)
        with self.assertRaisesRegex(RuntimeError, "already"):
            self.controller.start(self.project)
        other = RuntimeController(
            self.paths, self.manager, self.installer.target, MagicMock()
        )
        with self.assertRaisesRegex(RuntimeError, "another"):
            other.start(self.project)

    def test_package_lease_blocks_removal_in_another_manager(self) -> None:
        """Verify package lease blocks removal in another manager."""
        self.controller.start(self.project)
        other = PackageManager(self.installer, self.store)
        with self.assertRaisesRegex(RuntimeError, "in use"):
            other.remove(self.php)
        self.controller.stop(self.project.id)
        other.remove(self.php)
        self.assertNotIn(self.php, other.inventory())

    def test_dead_usage_file_does_not_block_removal(self) -> None:
        """Verify dead usage file does not block removal."""
        self.manager.acquire_use(self.php)
        self.manager.release_use(self.php)
        other = PackageManager(self.installer, self.store)
        other.remove(self.php)

    def test_unexpected_exit_rolls_back_entire_stack(self) -> None:
        """Verify unexpected exit rolls back entire stack."""
        self.controller.start(self.project)
        self.supervisor.status.return_value = "stopped"
        events = self.controller.monitor()
        self.assertEqual(events[0].state, "error")
        self.assertFalse(self.controller.runs)
        self.assertFalse(self.manager._leases)

    def test_repeated_health_failure_stops_stack(self) -> None:
        """Verify repeated health failure stops stack."""
        self.controller.start(self.project)
        self.controller._probe_listener.side_effect = OSError("unreachable")
        self.assertEqual(self.controller.monitor(), [])
        self.assertEqual(self.controller.monitor(), [])
        self.assertEqual(self.controller.monitor()[0].state, "error")

    def test_stop_failure_retains_package_protection(self) -> None:
        """Verify stop failure retains package protection."""
        self.controller.start(self.project)
        self.supervisor.stop.side_effect = OSError("cannot stop")
        with self.assertRaises(OSError):
            self.controller.stop(self.project.id)
        self.assertTrue(self.manager._leases)
        self.supervisor.stop.side_effect = None

    def test_restart_rebuilds_paths_and_releases_previous_run(self) -> None:
        """Verify restart rebuilds paths and releases previous run."""
        self.controller.start(self.project)
        self.controller.restart(self.project)
        self.assertEqual(self.supervisor.start.call_count, 6)
        self.assertEqual(self.manager._leases[self.php.key], 1)
        generated = (
            self.paths.project_config_dir(self.project.id) / "nginx.conf"
        ).read_text()
        self.assertIn(Path(self.project.document_root).as_posix(), generated)
        self.assertIn("runtime space", generated)

    def test_requires_exact_local_host_selection_and_separate_roots(self) -> None:
        """Verify requires exact local host selection and separate roots."""
        for invalid in (
            replace(self.project, nginx_package=None),
            replace(self.project, server="apache"),
            replace(self.project, document_root=str(self.root)),
            replace(self.project, php_package=self.php.key.replace("windows", "macos")),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.controller.start(invalid)
        self.supervisor.start.assert_not_called()

    def test_legacy_profiles_and_exact_selection_roundtrip(self) -> None:
        """Verify legacy profiles and exact selection roundtrip."""
        record = self.project.to_dict()
        del record["nginx_package"], record["php_package"]
        legacy = ProjectProfile.from_dict(record)
        self.assertIsNone(legacy.nginx_package)
        self.store.save([self.project])
        self.assertEqual(self.store.load(), [self.project])
        with self.assertRaisesRegex(ValueError, "match"):
            replace(self.project, php_version="8.3").validate()

    def test_exact_profile_guards_only_selected_version(self) -> None:
        """Verify exact profile guards only selected version."""
        self.store.save([self.project])
        other = replace(self.nginx, version="2.0.0")
        directory = self.installer.installed_path(other)
        directory.mkdir(parents=True)
        (directory / other.entrypoint).write_bytes(b"not executable")
        (directory / RECEIPT).write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "runtime_verified": False,
                    "package": asdict(other),
                }
            )
        )
        self.manager.remove(other)
        with self.assertRaisesRegex(RuntimeError, "requested"):
            self.manager.remove(self.nginx)

    def test_worker_closes_owned_runtimes(self) -> None:
        """Verify worker closes owned runtimes."""
        worker = RuntimeWorker(self.controller)
        worker.close()
        worker.thread.join(3)
        self.assertFalse(worker.thread.is_alive())


class RuntimeBoundaryTests(unittest.TestCase):
    """Keep source routing, configuration quoting and reservation invariants explicit."""

    def test_php_path_suffixes_are_denied_before_static_fallback(self) -> None:
        """Verify php path suffixes are denied before static fallback."""
        project = ProjectProfile.create("Site", Path.cwd())
        for port in (None, 9081):
            rendered = render_nginx_config(project, Path.cwd(), php_upstream_port=port)
            self.assertIn("php[0-9]?|phtml|phar|phps", rendered)
            self.assertIn("(?:[^a-z0-9]|$)", rendered)
            self.assertIn("return 404", rendered)
            self.assertNotIn("0.0.0.0", rendered)

    def test_port_reservation_is_exclusive_and_released(self) -> None:
        """Verify port reservation is exclusive and released."""
        first = PortReservation()
        port = first.port
        with self.assertRaises(OSError):
            PortReservation(port)
        first.close()
        second = PortReservation(port)
        second.close()
        for value in (True, 80, -1, 65536):
            with self.assertRaises(ValueError):
                PortReservation(value)

    def test_php_configuration_rejects_ini_injection_and_cleans_environment(
        self,
    ) -> None:
        """Verify php configuration rejects ini injection and cleans environment."""
        with self.assertRaises(ValueError):
            render_php_ini(Path.cwd() / "${EVIL}", Path.cwd())
        with patch.dict(
            os.environ, {"PHPRC": "bad", "PHP_FCGI_CHILDREN": "8", "CGI_MODE": "bad"}
        ):
            env = php_environment()
        self.assertNotIn("PHPRC", env)
        self.assertNotIn("PHP_FCGI_CHILDREN", env)
        self.assertEqual(env["PHP_INI_SCAN_DIR"], "")
        self.assertEqual(env["PHP_FCGI_MAX_REQUESTS"], "0")

    def test_windows_transient_directory_rename_retries(self) -> None:
        """Verify windows transient directory rename retries."""
        with (
            patch(
                "local_server.components.locking.os.rename",
                side_effect=[PermissionError(), None],
            ) as rename,
            patch("local_server.components.locking.time.sleep"),
        ):
            if os.name == "nt":
                rename_directory(Path("source"), Path("absent-target"))
                self.assertEqual(rename.call_count, 2)

    def test_os_released_ownership_can_be_reacquired(self) -> None:
        """Verify os released ownership can be reacquired."""
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "project.lock"
            lock = OwnershipLock(filename)
            try:
                with self.assertRaises(OSError):
                    OwnershipLock(filename)
            finally:
                lock.close()
            again = OwnershipLock(filename)
            again.close()


if __name__ == "__main__":
    unittest.main()

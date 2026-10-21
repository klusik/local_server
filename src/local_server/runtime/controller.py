"""Transactional Windows Nginx + PHP lifecycle, independent of Tk."""

import http.client
import json
import queue
import shutil
import socket
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from local_server.components.catalog import PackageSpec
from local_server.components.manager import PackageManager
from local_server.components.prerequisites import prerequisite_issues
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths, reject_links
from local_server.core.platform import PlatformTarget

from .mysql import DatabaseInventory, MysqlAdapter
from .nginx import render_nginx_config
from .ownership import OwnershipLock
from .php import PhpFastCgiAdapter, probe_fastcgi, render_php_ini
from .ports import PortReservation
from .processes import ProcessSupervisor


@dataclass(frozen=True)
class RuntimeEvent:
    """Immutable status delivered to the main thread."""

    project_id: str
    state: str
    message: str = ""
    details: str = ""
    owned: bool = False
    database_state: str = "stopped"
    connection: dict[str, str | int] | None = field(default=None, repr=False)
    database_inventory: DatabaseInventory | None = field(default=None, repr=False)


@dataclass
class _Run:
    """Describe the Windows Run native structure layout."""

    project: ProjectProfile
    ownership: OwnershipLock
    packages: list[PackageSpec] = field(default_factory=list)
    reservations: list[PortReservation] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    diagnostic: tempfile.TemporaryDirectory[str] | None = None
    token: str = ""
    expected: bytes = b""
    healthy: bool = False
    failed_probes: int = 0
    mysql: MysqlAdapter | None = None


class RuntimeController:
    """Serialize lifecycle transactions in a worker, retaining exact ownership."""

    def __init__(
        self,
        paths: AppPaths,
        manager: PackageManager,
        target: PlatformTarget,
        supervisor: ProcessSupervisor | None = None,
    ) -> None:
        """Bind isolated runtime dependencies and lifecycle cancellation.

        Args:
            paths (AppPaths): Application-managed storage layout.
            manager (PackageManager): Receipt inventory and package usage coordinator.
            target (PlatformTarget): Requested target platform or destination path.
            supervisor (ProcessSupervisor | None): Owner of explicitly started child
                processes.
        """
        self.paths, self.manager, self.target = paths, manager, target
        self.supervisor = supervisor or ProcessSupervisor(paths)
        self.runs: dict[str, _Run] = {}
        self.cancelled = threading.Event()
        self.progress: Callable[[RuntimeEvent], None] = lambda _event: None

    def _mysql_selection(self, project: ProjectProfile) -> PackageSpec | None:
        """Resolve and validate the explicitly selected local MySQL package.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.

        Returns:
            PackageSpec | None: Validated selected MySQL package, or None when MySQL is
                disabled.
        """
        if not project.mysql_enabled:
            return None
        package = next(
            (p for p in self.manager.inventory() if p.key == project.mysql_package),
            None,
        )
        if package is None:
            raise ValueError(
                "Select an exact available local MySQL package in Edit project"
            )
        package.validate()
        if (
            package.component != "mysql"
            or (package.os, package.arch) != (self.target.os, self.target.arch)
            or package.binary_arch != "x86_64"
            or package.variant != "community"
            or package.entrypoint != "bin/mysqld.exe"
        ):
            raise ValueError(
                "Select a Windows x64 MySQL Community package matching this host"
            )
        issues = prerequisite_issues(package, app_local=bool(package.runtime_bundle))
        if issues:
            raise ValueError(" ".join(issues))
        directory = self.manager.installer.installed_path(package)
        for filename in ("mysql.exe", "mysqladmin.exe"):
            path = directory / "bin" / filename
            reject_links(self.paths.components, path)
            if not path.is_file():
                raise ValueError(
                    "Selected MySQL package is missing its official client binaries"
                )
        return package

    def _selection(self, project: ProjectProfile) -> tuple[PackageSpec, PackageSpec]:
        """Resolve exact compatible local Nginx and PHP packages.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.

        Returns:
            tuple[PackageSpec, PackageSpec]: Selected compatible Nginx and PHP package
                pair.
        """
        if self.target != PlatformTarget("windows", "x86_64"):
            raise ValueError("Runtime startup currently requires Windows x64")
        if project.server != "nginx":
            raise ValueError("Only Nginx with PHP NTS FastCGI is implemented")
        local = {p.key: p for p in self.manager.inventory()}
        nginx = local.get(project.nginx_package or "")
        php = local.get(project.php_package or "")
        if not nginx or not php:
            raise ValueError(
                "Select exact local Nginx and PHP packages in Edit project"
            )
        for package, component in ((nginx, "nginx"), (php, "php")):
            package.validate()
            if package.component != component or (package.os, package.arch) != (
                self.target.os,
                self.target.arch,
            ):
                raise ValueError("Selected package does not match this OS/architecture")
            issues = prerequisite_issues(
                package, app_local=bool(package.runtime_bundle)
            )
            if issues:
                raise ValueError(" ".join(issues))
        if (
            php.variant != "nts-cgi"
            or php.binary_arch != "x86_64"
            or Path(php.entrypoint).name.lower() != "php-cgi.exe"
        ):
            raise ValueError("Select a Windows PHP NTS php-cgi.exe package")
        if Path(nginx.entrypoint).name.lower() != "nginx.exe":
            raise ValueError("Selected Nginx entrypoint is invalid")
        return nginx, php

    def _validate_roots(self, project: ProjectProfile) -> None:
        """Require an existing document root separate from private storage.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.
        """
        root = Path(project.document_root).resolve()
        if not root.is_dir():
            raise ValueError(
                "Document root is unavailable; choose its current location"
            )
        for private in (self.paths.root.resolve(), self.paths.components.resolve()):
            if private.is_relative_to(root) or root.is_relative_to(private):
                raise ValueError(
                    "Document root must be separate from application state and packages"
                )

    def start(self, project: ProjectProfile) -> None:
        """Start selected workers; advertise running only after an executed PHP probe.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.
        """
        project.validate()
        if self.cancelled.is_set():
            raise RuntimeError("Runtime startup cancelled while the application closes")
        if project.id in self.runs:
            raise RuntimeError("Project is already started or awaiting cleanup")
        self._validate_roots(project)
        nginx, php = self._selection(project)
        mysql = self._mysql_selection(project)
        self.paths.ensure()
        lock_path = self.paths.components / ".runtime-projects" / (project.id + ".lock")
        reject_links(self.paths.components, lock_path)
        try:
            ownership = OwnershipLock(lock_path)
        except OSError as exc:
            raise RuntimeError(
                "Project is owned by another Local Server instance"
            ) from exc
        run = _Run(project, ownership)
        self.runs[project.id] = run
        try:
            for package in (nginx, php, *((mysql,) if mysql else ())):
                self.manager.acquire_use(package)
                run.packages.append(package)
            try:
                http = PortReservation(project.http_port)
            except OSError as exc:
                raise RuntimeError(
                    f"HTTP port {project.http_port} is occupied. Choose another port."
                ) from exc
            run.reservations.append(http)
            fcgi = PortReservation()
            run.reservations.append(fcgi)
            config = self.paths.project_config_dir(project.id)
            reject_links(self.paths.root, config)
            config.mkdir(parents=True, exist_ok=True)
            for name in (
                "logs",
                "client_temp",
                "proxy_temp",
                "fastcgi_temp",
                "uwsgi_temp",
                "scgi_temp",
                "php-temp",
                "sessions",
            ):
                reject_links(self.paths.root, config / name)
                (config / name).mkdir(exist_ok=True)
            for name in ("error.log", "access.log", "php-error.log", "nginx.pid"):
                reject_links(self.paths.root, config / name)
            nginx_dir = self.manager.installer.installed_path(nginx)
            php_dir = self.manager.installer.installed_path(php)
            if mysql:
                for extension in ("php_mysqli.dll", "php_pdo_mysql.dll"):
                    path = php_dir / "ext" / extension
                    reject_links(self.paths.components, path)
                    if not path.is_file():
                        raise ValueError(
                            "Selected PHP package lacks mysqli/PDO MySQL extensions"
                        )
                run.mysql = MysqlAdapter(
                    self.paths,
                    project,
                    mysql,
                    self.manager.installer.installed_path(mysql),
                    self.supervisor,
                    self.cancelled,
                    progress=lambda state: self.progress(
                        RuntimeEvent(
                            project.id,
                            state,
                            "MySQL initialization"
                            if state == "initializing"
                            else "Starting MySQL",
                            owned=True,
                            database_state=state,
                        )
                    ),
                )
                run.mysql.start()
                self.progress(
                    RuntimeEvent(
                        project.id,
                        "starting",
                        "MySQL SQL verified; starting PHP/Nginx",
                        owned=True,
                        database_state="verified",
                    )
                )
            for name in ("mime.types", "fastcgi_params"):
                source = nginx_dir / "conf" / name
                reject_links(self.paths.components, source)
                reject_links(self.paths.root, config / name)
                shutil.copyfile(source, config / name)
            run.diagnostic = tempfile.TemporaryDirectory(
                prefix="diagnostic-", dir=config
            )
            script = Path(run.diagnostic.name) / "probe.php"
            run.token = uuid.uuid4().hex
            run.expected = f"{run.token}|{php.version}|cgi-fcgi".encode("ascii")
            probe = "<?php echo '" + run.token + "|' . PHP_VERSION . '|' . PHP_SAPI;"
            if run.mysql:
                # Password arrives only in a private loopback POST, never in a script,
                # URL, argv, Nginx access log or the user's website configuration.
                probe = (
                    """<?php
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  try {
    if (!extension_loaded('mysqli') || !extension_loaded('pdo_mysql')) { throw new Exception(); }
    $c = json_decode(file_get_contents('php://input'), true, 8, JSON_THROW_ON_ERROR);
    mysqli_report(MYSQLI_REPORT_ERROR | MYSQLI_REPORT_STRICT);
    $db = new mysqli('127.0.0.1', $c['user'], $c['password'], $c['database'], $c['port']);
    $row = $db->query('SELECT 1, @@server_uuid')->fetch_row();
    if ($row[0] != 1 || $row[1] !== $c['server_uuid']) { throw new Exception(); }
    $db->close();
  } catch (Throwable $e) { http_response_code(503); exit('Database probe failed'); }
}
"""
                    + "echo '"
                    + run.token
                    + "|' . PHP_VERSION . '|' . PHP_SAPI;"
                )
            script.write_text(probe, encoding="utf-8")
            for filename, content in (
                ("php.ini", render_php_ini(config, php_dir, mysql=bool(mysql))),
                (
                    "nginx.conf",
                    render_nginx_config(
                        project,
                        config,
                        php_upstream_port=fcgi.port,
                        diagnostic=(run.token, script),
                    ),
                ),
            ):
                reject_links(self.paths.root, config / filename)
                (config / filename).write_text(content, encoding="utf-8")
            php_name = "php-" + project.id
            fcgi.close()
            PhpFastCgiAdapter().start(
                self.supervisor, php_dir / php.entrypoint, config, fcgi.port, php_name
            )
            run.names.append(php_name)
            self._wait(run, lambda: probe_fastcgi(fcgi.port, script, run.expected))
            nginx_args = [
                str(nginx_dir / nginx.entrypoint),
                "-p",
                config.as_posix() + "/",
                "-c",
                str(config / "nginx.conf"),
                "-e",
                str(config / "error.log"),
            ]
            test_name = "validate-" + project.id
            # The Windows nginx -t path also opens listening sockets.
            http.close()
            test = self.supervisor.start(
                test_name, [*nginx_args, "-t"], cwd=config, contain=True
            )
            run.names.append(test_name)
            try:
                code = test.handle.wait(timeout=10)
                if code != 0:
                    raise RuntimeError(
                        f"Nginx configuration validation failed ({code}). See logs."
                    )
            finally:
                self.supervisor.stop(test_name)
                run.names.remove(test_name)
            http = PortReservation(project.http_port)
            run.reservations.append(http)
            http.close()
            nginx_name = "nginx-" + project.id
            self.supervisor.start(nginx_name, nginx_args, cwd=config, contain=True)
            run.names.append(nginx_name)
            self._wait(run, lambda: self._probe_http(run))
            # Give early process exits a chance to surface after successful probe.
            self._check_processes(run)
            run.healthy = True
        except BaseException:
            self.stop(project.id)
            raise
        finally:
            for reservation in run.reservations:
                reservation.close()
            run.reservations.clear()

    def _check_processes(self, run: _Run) -> None:
        """Detect an exited owned process before accepting a health probe.

        Args:
            run (_Run): Owned runtime transaction whose processes and health probes are
                checked.
        """
        if run.mysql and (run.mysql.process is None or not run.mysql.process.running):
            raise RuntimeError("Owned MySQL process exited. See MySQL logs.")
        if any(self.supervisor.status(name) != "running" for name in run.names):
            raise RuntimeError("An owned runtime process exited. See logs.")

    def _wait(self, run: _Run, probe: Callable[[], None]) -> None:
        """Wait for a bounded startup probe while honoring cancellation.

        Args:
            run (_Run): Owned runtime transaction whose processes and health probes are
                checked.
            probe (Callable[[], None]): Health check retried until readiness,
                cancellation or timeout.
        """
        deadline = time.monotonic() + 10
        while True:
            if self.cancelled.is_set():
                raise RuntimeError(
                    "Runtime startup cancelled while the application closes"
                )
            self._check_processes(run)
            try:
                probe()
                return
            except (OSError, http.client.HTTPException) as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Runtime health check timed out. See logs."
                    ) from exc
                time.sleep(0.1)

    @staticmethod
    def _probe_http(run: _Run) -> None:
        """Compare executed PHP output with the expected private probe bytes.

        Args:
            run (_Run): Owned runtime transaction whose processes and health probes are
                checked.
        """
        connection = http.client.HTTPConnection(
            "127.0.0.1", run.project.http_port, timeout=0.5
        )
        try:
            if run.mysql:
                fields = run.mysql.connection(reveal=True)
                fields["server_uuid"] = run.mysql.identity["server_uuid"]
                connection.request(
                    "POST",
                    f"/__local_server_{run.token}.php",
                    json.dumps(fields),
                    {"Content-Type": "application/json"},
                )
            else:
                connection.request("GET", f"/__local_server_{run.token}.php")
            response = connection.getresponse()
            if response.status != 200 or response.read(65537) != run.expected:
                raise OSError("HTTP/PHP diagnostic output/version mismatch")
        finally:
            connection.close()

    def stop(self, project_id: str) -> None:
        """Stop only owned children before releasing package and project locks.

        Args:
            project_id (str): Stable UUID of the saved project.
        """
        run = self.runs.get(project_id)
        if run is None:
            return
        # Retain the run and leases if stopping fails; removal must stay blocked.
        for name in reversed(run.names.copy()):
            self.supervisor.stop(name)
            run.names.remove(name)
        if run.mysql:
            run.mysql.stop()
            run.mysql = None
        for reservation in run.reservations:
            reservation.close()
        if run.diagnostic:
            run.diagnostic.cleanup()
            run.diagnostic = None
        for package in run.packages:
            self.manager.release_use(package)
        run.packages.clear()
        run.ownership.close()
        del self.runs[project_id]

    def restart(self, project: ProjectProfile) -> None:
        """Perform an explicit stop/start; no live PHP version switching.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.
        """
        self.stop(project.id)
        self.start(project)

    def monitor(self) -> list[RuntimeEvent]:
        """Detect child exits or repeated failed diagnostics and roll the stack back.

        Returns:
            list[RuntimeEvent]: Lifecycle events describing detected failures and
                completed rollback.
        """
        events = []
        for project_id, run in list(self.runs.items()):
            if not run.healthy:
                continue
            try:
                self._check_processes(run)
                try:
                    # A single Windows php-cgi worker can be busy with a long
                    # user request. Do not enqueue diagnostic PHP or kill valid
                    # requests merely because they take longer than a probe.
                    self._probe_listener(run)
                    if run.mysql:
                        run.mysql.probe()
                    run.failed_probes = 0
                except (OSError, http.client.HTTPException):
                    run.failed_probes += 1
                    if run.failed_probes < 3:
                        continue
                    raise RuntimeError(
                        "HTTP/PHP runtime health check failed repeatedly"
                    )
            except Exception as exc:
                details = traceback.format_exc()
                try:
                    self.stop(project_id)
                except Exception:
                    details += (
                        "\nCleanup failed; reservations retained:\n"
                        + traceback.format_exc()
                    )
                events.append(
                    RuntimeEvent(
                        project_id,
                        "error",
                        str(exc),
                        details,
                        project_id in self.runs,
                        database_state="error"
                        if run.project.mysql_enabled
                        else "disabled",
                    )
                )
        return events

    @staticmethod
    def _probe_listener(run: _Run) -> None:
        """Check the owned HTTP listener without executing application PHP.

        Args:
            run (_Run): Owned runtime transaction whose processes and health probes are
                checked.
        """
        with socket.create_connection(
            ("127.0.0.1", run.project.http_port), timeout=0.2
        ):
            pass

    def close(self) -> None:
        """Finish all owned runtime transactions before the application exits."""
        errors = []
        for project_id in list(self.runs):
            try:
                self.stop(project_id)
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))

    def connection(
        self, project_id: str, *, reveal: bool = False
    ) -> dict[str, str | int]:
        """Read credentials only from a verified run on the runtime worker.

        Args:
            project_id (str): Stable UUID of the saved project.
            reveal (bool): Whether the user explicitly requested secret values.

        Returns:
            dict[str, str | int]: Project connection fields; passwords appear only when
                reveal is requested.
        """
        run = self.runs.get(project_id)
        if run is None or not run.healthy or run.mysql is None:
            raise RuntimeError("Start and verify this project's MySQL stack first")
        return run.mysql.connection(reveal=reveal)


class RuntimeWorker:
    """A single lifecycle/monitor worker; it never calls Tk or browser APIs."""

    def __init__(self, controller: RuntimeController) -> None:
        """Create the lifecycle worker and main-thread event queue.

        Args:
            controller (RuntimeController): Owner of the disposable runtime under test.
        """
        self.controller = controller
        self.commands: queue.Queue[tuple[str, ProjectProfile, dict[str, str]]] = (
            queue.Queue()
        )
        self.events: queue.SimpleQueue[RuntimeEvent] = queue.SimpleQueue()
        self.controller.progress = self.events.put
        self.closing = threading.Event()
        self.thread = threading.Thread(
            target=self._run, name="project-runtimes", daemon=False
        )
        self.thread.start()

    def submit(
        self,
        action: str,
        project: ProjectProfile,
        arguments: dict[str, str] | None = None,
    ) -> None:
        """Queue an explicit lifecycle action, without doing IO on the caller.

        Args:
            action (str): Requested worker operation.
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.
            arguments (dict[str, str] | None): Literal process arguments, without shell
                expansion.
        """
        if self.closing.is_set() or action not in {
            "start",
            "stop",
            "restart",
            "connection",
            "password",
            "databases",
            "create-database",
            "create-user",
            "account-password",
        }:
            raise RuntimeError("Runtime worker is closing or action is invalid")
        self.commands.put((action, project, dict(arguments or {})))

    def close(self) -> None:
        """Request bounded startup completion followed by owned-process cleanup."""
        self.closing.set()
        self.controller.cancelled.set()

    def _run(self) -> None:
        """Process queued operations and report results through the event queue."""
        next_monitor = time.monotonic() + 1
        while not self.closing.is_set():
            try:
                action, project, arguments = self.commands.get(timeout=0.2)
            except queue.Empty:
                pass
            else:
                assert project is not None
                if action in {
                    "connection",
                    "password",
                    "databases",
                    "create-database",
                    "create-user",
                    "account-password",
                }:
                    try:
                        fields = self.controller.connection(
                            project.id, reveal=action == "password"
                        )
                        run = self.controller.runs[project.id]
                        assert run.mysql is not None
                        if action == "account-password":
                            fields = run.mysql.account_connection(
                                arguments.get("user", "")
                            )
                        if action in {"databases", "create-database", "create-user"}:
                            if action == "create-database":
                                inventory = run.mysql.create_database(
                                    arguments.get("database", "")
                                )
                            elif action == "create-user":
                                inventory = run.mysql.create_user(
                                    arguments.get("database", ""),
                                    arguments.get("user", ""),
                                )
                            else:
                                inventory = run.mysql.databases()
                            self.events.put(
                                RuntimeEvent(
                                    project.id,
                                    "databases",
                                    database_inventory=inventory,
                                )
                            )
                        else:
                            self.events.put(
                                RuntimeEvent(
                                    project.id,
                                    "password"
                                    if action == "account-password"
                                    else action,
                                    connection=fields,
                                )
                            )
                    except Exception as exc:
                        self.events.put(
                            RuntimeEvent(project.id, "connection-error", str(exc))
                        )
                    continue
                self.events.put(
                    RuntimeEvent(
                        project.id,
                        "stopping" if action == "stop" else "starting",
                        database_state=("stopping" if action == "stop" else "starting")
                        if project.mysql_enabled
                        else "disabled",
                    )
                )
                try:
                    if action == "stop":
                        self.controller.stop(project.id)
                    elif action == "restart":
                        self.controller.restart(project)
                    else:
                        self.controller.start(project)
                except Exception as exc:
                    self.events.put(
                        RuntimeEvent(
                            project.id,
                            "error",
                            str(exc).splitlines()[0],
                            traceback.format_exc(),
                            project.id in self.controller.runs,
                            database_state="error"
                            if project.mysql_enabled
                            else "disabled",
                        )
                    )
                else:
                    self.events.put(
                        RuntimeEvent(
                            project.id,
                            "stopped" if action == "stop" else "running",
                            database_state=(
                                "verified" if action != "stop" else "stopped"
                            )
                            if project.mysql_enabled
                            else "disabled",
                        )
                    )
            if time.monotonic() >= next_monitor:
                for event in self.controller.monitor():
                    self.events.put(event)
                next_monitor = time.monotonic() + 1
        try:
            self.controller.close()
        except Exception as exc:
            self.events.put(
                RuntimeEvent("", "error", "Runtime cleanup failed", str(exc))
            )

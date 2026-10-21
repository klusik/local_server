"""Explicit Windows x64 MySQL/PHP/Nginx smoke test in disposable directories.

Requires the exact receipt-backed reviewed packages, never a system MySQL/PHP.
No user document root/datadir is opened. Test vault entries are removed on exit.
"""

from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import uuid
from dataclasses import replace
from pathlib import Path

from local_server.components.catalog import PackageCatalog
from local_server.components.installer import ComponentInstaller
from local_server.components.manager import PackageManager
from local_server.components.locking import rename_directory
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths, application_root
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore
from local_server.runtime.controller import RuntimeController
from local_server.runtime.mysql import MysqlAdapter
from local_server.runtime.ports import PortReservation
from local_server.runtime.secrets import WindowsCredentialStore


def free_port() -> int:
    """Release a diagnostic port; the controller reserves it again before startup."""
    reservation = PortReservation()
    try:
        return reservation.port
    finally:
        reservation.close()


def request(port: int, path: str) -> tuple[int, bytes]:
    """Read bounded HTTP/PHP output directly from loopback."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read(65536)
    finally:
        connection.close()


def verify_no_secrets(controller: RuntimeController, mysql: MysqlAdapter) -> None:
    """Check ordinary logs/configuration/profiles/argv without printing passwords."""
    passwords = list(mysql.passwords.values())
    for record in mysql._accounts():
        passwords.extend(mysql.vault.get(record["credential"]).values())
    files = [*controller.paths.logs.rglob("*.log"), *controller.paths.generated.rglob("*")]
    if controller.paths.projects_file.exists():
        files.append(controller.paths.projects_file)
    for path in files:
        if path.is_file() and "sensitive-" not in str(path):
            data = path.read_bytes()
            assert all(password.encode() not in data for password in passwords), "Secret in ordinary file"
    for child in controller.supervisor._children.values():
        assert all(password not in " ".join(child.handle.args) for password in passwords), "Secret in argv"


def main() -> None:
    """Verify actual initialization, isolation, SQL, relocation, shutdown and rollback."""
    target = PlatformTarget.detect()
    if target != PlatformTarget("windows", "x86_64"):
        raise RuntimeError("This smoke test requires Windows x64")
    repository = application_root()
    catalog = {p.key: p for p in PackageCatalog.bundled().packages}
    packages = [catalog[key] for key in ("nginx/1.30.6/windows-x86_64/win32-wow64",
                "php/8.4.26/windows-x86_64/nts-cgi", "mysql/8.4.13/windows-x86_64/community")]
    source = ComponentInstaller(AppPaths(repository / ".test-tmp" / "acquisition-state", repository), target)
    available = PackageManager(source, ProjectStore(source.paths.projects_file)).inventory()
    if any(package not in available for package in packages):
        raise RuntimeError("Acquire the three exact reviewed packages before this explicit smoke test")
    temporary = repository / ".test-tmp"
    temporary.mkdir(exist_ok=True)
    credentials: set[str] = set()
    with tempfile.TemporaryDirectory(prefix="mysql smoke ", dir=temporary) as folder:
        workspace = Path(folder)
        application = workspace / "original application"
        paths = AppPaths(application / ".local-server", application)
        print("Copying verified packages to disposable app", flush=True)
        for package in packages:
            shutil.copytree(source.installed_path(package), paths.components / package.key)
        site = application / "sites" / "disposable site"
        site.mkdir(parents=True)
        php_source = b"<?php echo 'mysql smoke';"
        (site / "index.php").write_bytes(php_source)
        (site / "index.php.bak").write_bytes(php_source)
        nginx, php, mysql = packages
        project = ProjectProfile.create("MySQL smoke", site, nginx_package=nginx.key,
            php_version=php.version, php_package=php.key, mysql_enabled=True, mysql_package=mysql.key,
            mysql_port=free_port(), http_port=free_port())
        store = ProjectStore(paths.projects_file, portable_root=application)
        store.save([project])
        controller: RuntimeController | None = None
        try:
            for moved in (False, True):
                if moved:
                    destination = workspace / "relocated application with spaces"
                    rename_directory(application, destination)
                    application = destination
                    paths = AppPaths(application / ".local-server", application)
                    store = ProjectStore(paths.projects_file, portable_root=application)
                    project = store.load()[0]
                manager = PackageManager(ComponentInstaller(paths, target), store)
                controller = RuntimeController(paths, manager, target)
                print("Starting verified SQL + PHP/HTTP stack; relocated =", moved, flush=True)
                controller.start(project)
                adapter = controller.runs[project.id].mysql
                assert adapter is not None
                credentials.add(str(adapter.identity["credential"]))
                assert controller.runs[project.id].healthy
                policy = adapter._client(admin=True, sql="SELECT CONCAT(@@bind_address,'|',@@named_pipe,'|',"
                    "@@shared_memory,'|',IFNULL(@@admin_address,''),'|',@@persisted_globals_load);")
                assert policy == "127.0.0.1|0|0||0", "Unexpected MySQL listener/global policy: " + repr(policy)
                assert adapter._client(admin=True, sql="SELECT COUNT(*) FROM INFORMATION_SCHEMA.PLUGINS "
                    "WHERE PLUGIN_NAME='mysqlx' AND PLUGIN_STATUS='ACTIVE';") == "0"
                assert request(project.http_port, "/index.php") == (200, b"mysql smoke")
                # Controller.start already executed SELECT 1 through HTTP/mysqli.
                if not moved:
                    adapter._client(sql="CREATE TABLE persistence (value INT); INSERT INTO persistence VALUES (42);")
                    adapter.create_database("gallery")
                    adapter.create_database("privateother")
                    adapter.create_user("gallery", "galleryuser")
                    inventory = adapter.databases()
                    assert "gallery" in inventory["databases"]
                    credentials.update(record["credential"] for record in inventory["accounts"])
                    connection = adapter.account_connection("galleryuser")
                    old = adapter.user, adapter.database, adapter.passwords["project"]
                    try:
                        adapter.user, adapter.database = str(connection["user"]), "gallery"
                        adapter.passwords["project"] = str(connection["password"])
                        # Exercise uncached caching_sha2 authentication from PHP first.
                        controller._probe_http(controller.runs[project.id])
                        assert adapter._client(sql="SELECT 1;") == "1"
                        try:
                            adapter._client(sql="SELECT COUNT(*) FROM privateother.noaccess;")
                        except OSError:
                            pass
                        else:
                            raise AssertionError("Account accessed an ungranted database")
                        visible = adapter._client(sql="SHOW DATABASES;").splitlines()
                        assert "privateother" not in visible and old[1] not in visible
                    finally:
                        adapter.user, adapter.database, adapter.passwords["project"] = old
                    # Wrong password must fail an authenticated SQL probe.
                    real_password = adapter.passwords["project"]
                    try:
                        adapter.passwords["project"] = "wrong" * 12
                        try:
                            adapter.probe()
                        except OSError:
                            pass
                        else:
                            raise AssertionError("Wrong password accepted")
                    finally:
                        adapter.passwords["project"] = real_password
                    duplicate = RuntimeController(paths, manager, target)
                    try:
                        duplicate.start(project)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Duplicate project start accepted")
                    other_manager = PackageManager(ComponentInstaller(paths, target), ProjectStore(paths.root / "empty.json"))
                    try:
                        other_manager.remove(mysql)
                    except RuntimeError:
                        pass
                    else:
                        raise AssertionError("Active MySQL package removal accepted")
                    # A second instance has distinct server identity/data/passwords.
                    second = replace(project, id=str(uuid.uuid4()), name="Other project",
                                     http_port=free_port(), mysql_port=free_port())
                    controller.start(second)
                    other = controller.runs[second.id].mysql
                    assert other is not None and other.identity["server_uuid"] != adapter.identity["server_uuid"]
                    credentials.add(str(other.identity["credential"]))
                    assert "gallery" not in other.databases()["databases"]
                    # The first project's credentials cannot log into the second instance.
                    old_project = adapter.project
                    try:
                        adapter.project = replace(adapter.project, mysql_port=second.mysql_port)
                        try:
                            adapter.probe()
                        except OSError:
                            pass
                        else:
                            raise AssertionError("Another project's credentials were accepted")
                    finally:
                        adapter.project = old_project
                    controller.stop(second.id)
                    # Cancel an actual first initialization, without touching an existing DB.
                    cancel_project = replace(second, id=str(uuid.uuid4()), name="Cancel initialization")
                    cancelled = RuntimeController(paths, manager, target)
                    cancelled.progress = lambda event: cancelled.cancelled.set() if event.state == "initializing" else None
                    try:
                        try:
                            cancelled.start(cancel_project)
                        except RuntimeError as exc:
                            assert "cancelled" in str(exc)
                        else:
                            raise AssertionError("Initialization was not cancelled")
                        assert not (paths.databases / cancel_project.id).exists()
                    finally:
                        cancelled.close()
                    # A foreign port reservation must not cause initialization or a kill.
                    conflict = replace(cancel_project, id=str(uuid.uuid4()), name="Port conflict")
                    held = PortReservation(conflict.mysql_port)
                    try:
                        try:
                            controller.start(conflict)
                        except RuntimeError as exc:
                            assert "occupied" in str(exc)
                        else:
                            raise AssertionError("SQL port collision accepted")
                        assert not (paths.databases / conflict.id).exists()
                    finally:
                        held.close()
                assert adapter._client(sql="SELECT value FROM persistence;") == "42"
                verify_no_secrets(controller, adapter)
                controller.restart(project)
                adapter = controller.runs[project.id].mysql
                assert adapter is not None and adapter._client(sql="SELECT value FROM persistence;") == "42"
                # Missing PHP never turns a script or backup into static source.
                controller.supervisor.stop("php-" + project.id)
                for path in ("/index.php", "/index.php.bak", "/index.php/anything", "/index.php.", "/index.php%20"):
                    status, body = request(project.http_port, path)
                    assert status != 200 and b"<?php" not in body
                assert controller.monitor()[0].state == "error"
                controller.start(project)
                # Unexpected MySQL exit rolls back Nginx/PHP, preserving data.
                controller.supervisor.stop("mysql-" + project.id)
                assert controller.monitor()[0].state == "error"
                controller.start(project)
                adapter = controller.runs[project.id].mysql
                assert adapter is not None and adapter._client(sql="SELECT value FROM persistence;") == "42"
                controller.close()
                if not moved:
                    before = (adapter.directory / "datadir" / "mysql.ibd").stat().st_size
                    incompatible = MysqlAdapter(paths, project, replace(mysql, version="8.4.12"),
                        manager.installer.installed_path(mysql), controller.supervisor, threading.Event())
                    try:
                        incompatible.start()
                    except RuntimeError as exc:
                        assert "original exact" in str(exc)
                    else:
                        raise AssertionError("Incompatible data version accepted")
                    assert (adapter.directory / "datadir" / "mysql.ibd").stat().st_size == before
                    identity_file = adapter.directory / "identity.json"
                    identity = json.loads(identity_file.read_text())
                    missing = dict(identity, credential=str(uuid.uuid4()))
                    identity_file.write_text(json.dumps(missing))
                    try:
                        try:
                            controller.start(project)
                        except RuntimeError as exc:
                            assert "credentials are unavailable" in str(exc)
                        else:
                            raise AssertionError("Missing vault credentials accepted")
                    finally:
                        identity_file.write_text(json.dumps(identity))
                assert not manager._leases
                print("SQL, PHP/HTTP, isolation, persistence, restart, crash, secrecy passed", flush=True)
            assert (Path(project.document_root) / "index.php").read_bytes() == php_source
        finally:
            if controller:
                controller.close()
            # Discover only test-owned credential references, including failed init.
            for identity in paths.databases.glob("*/identity.json"):
                credentials.add(json.loads(identity.read_text())["credential"])
            for accounts in paths.databases.glob("*/accounts.json"):
                credentials.update(record["credential"] for record in json.loads(accounts.read_text()))
            for reference in credentials:
                WindowsCredentialStore().delete(reference)
    print("MySQL smoke passed; disposable data and test vault entries removed", flush=True)


if __name__ == "__main__":
    main()

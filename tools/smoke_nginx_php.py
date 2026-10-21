"""Explicit real-binary Windows smoke test using disposable projects only.

Run with PYTHONPATH=src. --acquire downloads only the two selected, pinned catalog
entries into the application's packages folder. It never starts Apache/MySQL.
"""

from __future__ import annotations

import argparse
import http.client
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from local_server.components.catalog import PackageCatalog
from local_server.components.installer import ComponentInstaller
from local_server.components.manager import PackageManager
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths, application_root
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore
from local_server.runtime.controller import RuntimeController
from local_server.runtime.ports import PortReservation


def request(port: int, path: str) -> tuple[int, bytes]:
    """Read one bounded loopback response without proxies or redirects."""
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read(65536)
    finally:
        connection.close()


def free_port() -> int:
    """Find a diagnostic port; runtime startup reserves and checks it again."""
    reservation = PortReservation()
    port = reservation.port
    reservation.close()
    return port


def main() -> None:
    """Acquire on request, test a relocated stack and verify failure boundaries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acquire", action="store_true")
    parser.add_argument("--nginx", default="nginx/1.30.6/windows-x86_64/win32-wow64")
    parser.add_argument("--php", default="php/8.4.26/windows-x86_64/nts-cgi")
    args = parser.parse_args()
    target = PlatformTarget.detect()
    if target != PlatformTarget("windows", "x86_64"):
        parser.error("This smoke test requires Windows x64")
    catalog = PackageCatalog.bundled()
    selected = {p.key: p for p in catalog.packages}
    nginx, php = selected[args.nginx], selected[args.php]
    if nginx.component != "nginx" or php.component != "php":
        parser.error("Select Nginx and PHP catalog identities")
    repository = application_root()
    temporary = repository / ".test-tmp"
    temporary.mkdir(exist_ok=True)
    source_paths = AppPaths(temporary / "acquisition-state", repository)
    installer = ComponentInstaller(source_paths, target, runtime_bundles=catalog.runtime_bundles)
    for package in (nginx, php):
        if not installer.installed_path(package).is_dir():
            if not args.acquire:
                parser.error("Package missing; use --acquire for the selected verified archives")
            print("Acquiring", package.key, flush=True)
            installer.install(package)
    with tempfile.TemporaryDirectory(prefix="real runtime ", dir=temporary) as folder:
        workspace = Path(folder)
        application = workspace / "original application"
        paths = AppPaths(application / ".local-server", application)
        for package in (nginx, php):
            shutil.copytree(installer.installed_path(package), paths.components / package.key)
        site = application / "sites" / "temporary PHP site"
        site.mkdir(parents=True)
        source = b"<?php echo 'smoke:' . PHP_VERSION;"
        (site / "index.php").write_bytes(source)
        (site / "index.php.bak").write_bytes(source)
        (site / "example.phtml").write_bytes(source)
        (site / "plain.txt").write_text("static smoke", encoding="utf-8")
        project = ProjectProfile.create("Smoke", site, php_version=php.version,
            nginx_package=nginx.key, php_package=php.key, http_port=free_port())
        store = ProjectStore(paths.projects_file, portable_root=application)
        store.save([project])
        results = []
        for relocation in (False, True):
            if relocation:
                moved = workspace / "relocated application with spaces"
                application.rename(moved)
                application = moved
                paths = AppPaths(application / ".local-server", application)
                store = ProjectStore(paths.projects_file, portable_root=application)
                project = store.load()[0]
            manager = PackageManager(ComponentInstaller(paths, target), store)
            controller = RuntimeController(paths, manager, target)
            try:
                controller.start(project)
                assert request(project.http_port, "/index.php") == (200, ("smoke:" + php.version).encode())
                assert request(project.http_port, "/plain.txt") == (200, b"static smoke")
                for path in ("/index.php.bak", "/example.phtml", "/index.php/anything", "/index.php.", "/index.php%20"):
                    status, body = request(project.http_port, path)
                    assert b"<?php" not in body and (status != 200 or body == ("smoke:" + php.version).encode()), (path, status, body)
                # Another state directory must still respect the same package lease.
                other_paths = AppPaths(application / "other-state", application)
                other = PackageManager(ComponentInstaller(other_paths, target), ProjectStore(other_paths.projects_file))
                try:
                    other.remove(php)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Cross-instance package removal was allowed")
                duplicate = RuntimeController(paths, manager, target)
                try:
                    duplicate.start(project)
                except RuntimeError:
                    pass
                else:
                    duplicate.close()
                    raise AssertionError("Duplicate project was allowed")
                second = replace(project, id=ProjectProfile.create("Other", site).id,
                                 name="Other", http_port=free_port())
                controller.start(second)
                assert request(second.http_port, "/index.php")[0] == 200
                controller.stop(second.id)
                controller.restart(project)
                assert request(project.http_port, "/index.php")[0] == 200
                # Leave Nginx up briefly while its PHP worker is down: never serve source.
                controller.supervisor.stop("php-" + project.id)
                status, body = request(project.http_port, "/index.php")
                assert status == 502 and b"<?php" not in body, (status, body)
                for path in ("/index.php.", "/index.php%20", "/index.php.bak", "/index.php/anything", "/example.phtml"):
                    status, body = request(project.http_port, path)
                    assert status != 200 and b"<?php" not in body, (path, status, body)
                assert controller.monitor()[0].state == "error"
                assert not controller.runs and not manager._leases
                assert (Path(project.document_root) / "index.php").read_bytes() == source
                assert {p.name for p in Path(project.document_root).iterdir()} == {
                    "index.php", "index.php.bak", "example.phtml", "plain.txt"}
                results.append({"relocated": relocation, "php": php.key, "nginx": nginx.key,
                                "start_restart_stop": "passed", "source_disclosure": "blocked",
                                "cross_instance_removal": "blocked", "parallel_projects": "passed"})
            except BaseException:
                for log in [*paths.logs.glob("*.log"), *paths.project_config_dir(project.id).glob("*.log")]:
                    print(log.name, log.read_text(encoding="utf-8", errors="replace")[-8000:], flush=True)
                raise
            finally:
                controller.close()
        print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()

"""Portable inventory, conservative removal guards and a Tk-free worker bridge."""

from __future__ import annotations

import json
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path

from local_server.core.paths import reject_links
from local_server.core.store import ProjectStore

from .catalog import PackageSpec
from .installer import ComponentInstaller, DownloadCancelled, RECEIPT, remove_tree
from .locking import package_lock, rename_directory
from .prerequisites import prerequisite_issues
from .runtime_bundle import RuntimeBundle
from .app_local import verify_runtime_files
from local_server.runtime.ownership import OwnershipLock


@dataclass(frozen=True)
class PackageEvent:
    """Worker output consumed exclusively by the UI's main-thread poller."""

    state: str
    package: PackageSpec | None = None
    done: int = 0
    total: int = 0
    local: tuple[PackageSpec, ...] = ()
    issues: tuple[tuple[str, tuple[str, ...]], ...] = ()
    message: str = ""
    details: str = ""


class PackageManager:
    """Manage receipt-backed packages without claiming runtime health."""

    def __init__(self, installer: ComponentInstaller, store: ProjectStore) -> None:
        self.installer = installer
        self.store = store
        self._leases: dict[str, int] = {}
        self._lease_lock = threading.RLock()
        self._usage_locks: dict[str, OwnershipLock] = {}

    def _usage_dir(self, package: PackageSpec) -> Path:
        directory = self.installer.paths.components / ".usage" / package.key
        reject_links(self.installer.paths.components, directory)
        return directory

    def acquire_use(self, package: PackageSpec) -> None:
        """Reserve a package before a future runtime starts using its files."""
        with self._lease_lock, package_lock(self.installer.paths.components):
            if package not in self.inventory():
                raise RuntimeError("Package is not locally available")
            if package.key not in self._leases:
                filename = self._usage_dir(package) / (uuid.uuid4().hex + ".lock")
                self._usage_locks[package.key] = OwnershipLock(filename)
            self._leases[package.key] = self._leases.get(package.key, 0) + 1

    def release_use(self, package: PackageSpec) -> None:
        """Release a future runtime reservation after the process has stopped."""
        with self._lease_lock:
            count = self._leases.get(package.key, 0)
            if count <= 1:
                self._leases.pop(package.key, None)
                lock = self._usage_locks.pop(package.key, None)
                if lock:
                    lock.close()
            else:
                self._leases[package.key] = count - 1

    def inventory(self) -> tuple[PackageSpec, ...]:
        """Discover committed receipts, including versions removed from the catalog."""
        root = self.installer.paths.components
        found: list[PackageSpec] = []
        reject_links(root, root)
        for receipt in root.glob("*/*/*/*/" + RECEIPT):
            if receipt.relative_to(root).parts[0].startswith("."):
                continue
            reject_links(root, receipt)
            if receipt.stat().st_size > 64 * 1024:
                raise ValueError(f"Oversized package receipt: {receipt}")
            raw = json.loads(receipt.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != 1 or raw.get("runtime_verified") is not False:
                raise ValueError(f"Invalid package receipt: {receipt}")
            package = PackageSpec.from_dict(raw.get("package"))
            target = self.installer.installed_path(package)
            if receipt.parent != target:
                raise ValueError(f"Package receipt does not match its location: {receipt}")
            executable = target / package.entrypoint
            reject_links(root, executable)
            if not executable.is_file():
                raise ValueError(f"Local package is incomplete: {package.key}")
            if package.runtime_bundle:
                bundle = RuntimeBundle.from_dict(raw.get("app_local_runtime"))
                if bundle.id != package.runtime_bundle or (bundle.os, bundle.arch) != (package.os, package.binary_arch):
                    raise ValueError("Local runtime receipt does not match the server package")
                verify_runtime_files(bundle, executable.parent, deployed=True)
            found.append(package)
        return tuple(found)

    def remove(self, package: PackageSpec) -> None:
        """Remove one binary version, never project sources or database data."""
        root = self.installer.paths.components
        with self._lease_lock, package_lock(root):
            target = self.installer.installed_path(package)
            if package.key in self._leases:
                raise RuntimeError("This version is in use. Stop its runtime before removing it.")
            for filename in self._usage_dir(package).glob("*.lock"):
                reject_links(root, filename)
                try:
                    lock = OwnershipLock(filename)
                except OSError as exc:
                    raise RuntimeError("This version is in use by another Local Server instance.") from exc
                else:
                    lock.close()
                    filename.unlink()  # stale, OS-released lease; never a PID kill
            # Exact selections protect only their chosen identity; legacy
            # profiles retain their conservative server/PHP-minor guards.
            for project in self.store.load():
                document_root = Path(project.document_root).resolve()
                if document_root.is_relative_to(target.resolve()):
                    raise RuntimeError(f"Package contains the document root of project '{project.name}'. Reassign it before removing the package.")
                selected = project.php_version
                server_requested = (package.key == project.nginx_package if project.nginx_package and project.server == "nginx"
                                    else package.component == project.server)
                php_requested = (package.key == project.php_package if project.php_package else
                                 package.component == "php" and selected and
                                 (package.version == selected or package.version.startswith(selected + ".")))
                if (server_requested or php_requested or
                    package.component == "mysql" and project.mysql_enabled):
                    raise RuntimeError(f"Package is requested by project '{project.name}'. Change the profile before removing it.")
            if package not in self.inventory():
                raise ValueError("No matching local package receipt")
            # Detach availability first. A failed deletion is retried by staging
            # recovery, never mistaken for a complete package.
            detached = self.installer.paths.downloads / (".remove-" + uuid.uuid4().hex)
            reject_links(root, detached)
            rename_directory(target, detached)
            remove_tree(root, detached)


class PackageWorker:
    """One bounded operation at a time; no worker ever calls Tk, including after()."""

    def __init__(self, manager: PackageManager, packages: tuple[PackageSpec, ...]) -> None:
        self.manager = manager
        self.packages = packages
        self.events: queue.SimpleQueue[PackageEvent] = queue.SimpleQueue()
        self.cancelled = threading.Event()
        self.thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """Report whether closing the UI must wait for temporary-file cleanup."""
        return self.thread is not None and self.thread.is_alive()

    def start(self, action: str, package: PackageSpec | None = None) -> None:
        """Start inventory, download/retry or removal without blocking the caller."""
        if self.busy:
            raise RuntimeError("A package operation is already in progress")
        if action not in {"refresh", "download", "remove"}:
            raise ValueError("Unknown package operation")
        self.cancelled.clear()
        self.thread = threading.Thread(target=self._run, args=(action, package), name="portable-packages", daemon=False)
        self.thread.start()

    def cancel(self) -> None:
        """Request cancellation; network reads are bounded by the HTTPS timeout."""
        self.cancelled.set()

    def _run(self, action: str, package: PackageSpec | None) -> None:
        last_time = 0.0
        last_state = ""

        def progress(state: str, done: int, total: int) -> None:
            nonlocal last_time, last_state
            now = time.monotonic()
            if state != last_state or now - last_time >= 0.1 or done == total:
                self.events.put(PackageEvent(state, package, done, total))
                last_time, last_state = now, state

        try:
            installer = self.manager.installer
            installer.paths.ensure()
            if action == "download":
                if package not in self.packages:
                    raise ValueError("Only reviewed catalog packages may be downloaded")
                installer.install(package, cancel=self.cancelled, progress=progress)
            elif action == "remove":
                if package is None:
                    raise ValueError("Select a local package")
                self.manager.remove(package)
            else:
                with package_lock(installer.paths.components):
                    installer.cleanup_incomplete()
            local = self.manager.inventory()
            # Catalog references are validated at startup; local references were
            # verified from receipts/DLL hashes by inventory(). No SDK is probed.
            local_keys = {p.key for p in local}
            visible = {p.key: p for p in self.packages}
            visible.update({p.key: p for p in local})
            issues = tuple((p.key, tuple(prerequisite_issues(p, app_local=bool(p.runtime_bundle) and (
                p.key in local_keys or installer.runtime_for(p) is not None))))
                for p in visible.values())
            self.events.put(PackageEvent("ready", package, local=local, issues=issues))
        except DownloadCancelled as exc:
            self.events.put(PackageEvent("cancelled", package, message=str(exc)))
        except Exception as exc:
            self.events.put(PackageEvent("error", package, message=str(exc).splitlines()[0], details=traceback.format_exc()))

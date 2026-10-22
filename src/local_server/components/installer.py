"""Verified downloads and transactional private binary installations."""

import hashlib
import json
import os
import shutil
import struct
import tempfile
import threading
import urllib.request
from dataclasses import asdict
from http.client import HTTPMessage
from pathlib import Path
from typing import IO, Callable, Mapping
from urllib.parse import urlsplit

from local_server.core.paths import AppPaths, reject_links
from local_server.core.platform import PlatformTarget

from .app_local import deploy_runtime, prepare_runtime
from .archive import safe_extract
from .catalog import PackageSpec
from .locking import package_lock, rename_directory
from .prerequisites import prerequisite_issues
from .runtime_bundle import RuntimeBundle

MAX_DOWNLOAD_BYTES = 2 * 1024**3
RECEIPT = ".local-server-package.json"
Progress = Callable[[str, int, int], None]


class DownloadCancelled(RuntimeError):
    """A user cancelled acquisition before the atomic availability commit."""


class IntegrityError(RuntimeError):
    """A downloaded binary package does not match its pinned SHA-256."""


class HTTPSOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject TLS downgrade and credential-bearing redirects before following."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        """Refuse redirects outside HTTPS before sending the next request.

        Args:
            req (urllib.request.Request): Original urllib request that received the
                redirect.
            fp (IO[bytes]): Response stream associated with the redirect.
            code (int): HTTP status code returned by the redirecting server.
            msg (str): HTTP status message supplied by urllib.
            headers (HTTPMessage): HTTP response headers supplied by urllib.
            newurl (str): Redirect destination checked before another request is sent.

        Returns:
            urllib.request.Request | None: Validated HTTPS redirect request, or None
                when urllib declines it.
        """
        target = urlsplit(newurl)
        if (
            target.scheme.lower() != "https"
            or not target.hostname
            or target.username is not None
            or target.password is not None
        ):
            raise ValueError("Package redirect must remain an HTTPS URL")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ComponentInstaller:
    """Install archive-based components without touching system directories."""

    def __init__(
        self,
        paths: AppPaths,
        target: PlatformTarget | None = None,
        *,
        runtime_bundles: Mapping[str, RuntimeBundle] | None = None,
    ) -> None:
        """Bind private storage, the target platform and reviewed dependencies.

        Args:
            paths (AppPaths): Application-managed storage layout.
            target (PlatformTarget | None): Requested target platform or destination
                path.
            runtime_bundles (Mapping[str, RuntimeBundle] | None): Reviewed app-local
                runtime dependencies indexed by identity.
        """
        self.paths = paths
        self.target = target or PlatformTarget.detect()
        self._open = urllib.request.build_opener(HTTPSOnlyRedirectHandler()).open
        self.runtime_bundles = dict(runtime_bundles or {})

    def runtime_for(self, package: PackageSpec) -> RuntimeBundle | None:
        """Resolve a reviewed app-local dependency without consulting the host SDK.

        Args:
            package (PackageSpec): Reviewed component archive, platform and version
                metadata.

        Returns:
            RuntimeBundle | None: Reviewed runtime dependency, or None when the package
                requires the host runtime.
        """
        if not package.runtime_bundle:
            return None
        bundle = self.runtime_bundles.get(package.runtime_bundle)
        if bundle is None:
            raise ValueError("The required app-local runtime has not been curated")
        bundle.validate()
        if (bundle.os, bundle.arch) != (package.os, package.binary_arch):
            raise ValueError("App-local runtime architecture mismatch")
        if tuple(map(int, bundle.version.split("."))) < tuple(
            map(int, package.vc_minimum.split("."))
        ):
            raise ValueError("App-local runtime is older than the server requirement")
        return bundle

    def installed_path(self, package: PackageSpec) -> Path:
        """Return the platform-specific side-by-side binary installation path.

        Args:
            package (PackageSpec): Reviewed component archive, platform and version
                metadata.

        Returns:
            Path: Private side-by-side installation directory for the exact package.
        """
        package.validate()
        path = self.paths.components / package.key
        reject_links(self.paths.components, path)
        return path

    def install(
        self,
        package: PackageSpec,
        *,
        cancel: threading.Event | None = None,
        progress: Progress = lambda _state, _done, _total: None,
    ) -> Path:
        """Download, verify and atomically activate a package in user storage.

        No external scripts are executed and no machine-wide installers run.
        A curated catalog must supply a verified SHA-256 and exact entrypoint.

        Args:
            package (PackageSpec): Reviewed component archive, platform and version
                metadata.
            cancel (threading.Event | None): Event indicating that the operation should
                stop.
            progress (Progress): Worker callback reporting completed work without
                updating Tk.

        Returns:
            Path: Activated receipt-backed package directory.
        """
        package.validate()
        if (package.os, package.arch) != (self.target.os, self.target.arch):
            raise ValueError("Package architecture does not match this computer")
        runtime = self.runtime_for(package)
        issues = (
            prerequisite_issues(package, app_local=runtime is not None)
            if package.source
            else []
        )
        if issues:
            raise RuntimeError("\n".join(issues))
        self.paths.ensure()
        with package_lock(self.paths.components):
            self.cleanup_incomplete()
            return self._install_locked(package, cancel or threading.Event(), progress)

    def _install_locked(
        self, package: PackageSpec, cancel: threading.Event, progress: Progress
    ) -> Path:
        """Stage and activate one verified package while holding its lock.

        Args:
            package (PackageSpec): Reviewed component archive, platform and version
                metadata.
            cancel (threading.Event): Event indicating that the operation should stop.
            progress (Progress): Worker callback reporting completed work without
                updating Tk.

        Returns:
            Path: Activated package directory containing the verified receipt.
        """

        def check() -> None:
            """Abort acquisition promptly after cancellation is requested."""
            if cancel.is_set():
                raise DownloadCancelled("Download cancelled; temporary files removed.")

        target = self.installed_path(package)
        if target.exists():
            raise FileExistsError(f"Already installed: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        archive_name: str | None = None
        staging: str | None = None
        try:
            runtime = self.runtime_for(package)
            runtime_cache = None
            if runtime:
                runtime_cache = prepare_runtime(
                    runtime,
                    self.paths,
                    download=self._download_and_verify,
                    check=check,
                    progress=lambda state, done, total: progress(
                        "runtime-" + state, done, total
                    ),
                    remove=lambda path: remove_tree(self.paths.components, path),
                )
            with tempfile.NamedTemporaryFile(
                dir=self.paths.downloads, prefix=".package-", delete=False
            ) as file:
                archive_name = file.name
                self._download_and_verify(package, file, check, progress)
            check()
            staging = tempfile.mkdtemp(prefix=".install-", dir=self.paths.downloads)
            progress("extracting", 0, 0)
            safe_extract(
                Path(archive_name),
                Path(staging),
                package.archive,
                strip_components=package.strip_components,
                check=check,
                progress=lambda done, total: progress("extracting", done, total),
            )
            entrypoint = Path(staging) / package.entrypoint.replace("\\", "/")
            if not entrypoint.is_file():
                raise ValueError(
                    f"Package is missing expected executable: {package.entrypoint}"
                )
            if package.source and package.os == "windows":
                with entrypoint.open("rb") as executable:
                    header = executable.read(64)
                    if len(header) != 64 or header[:2] != b"MZ":
                        raise IntegrityError("Expected a Windows PE executable")
                    offset = struct.unpack_from("<I", header, 60)[0]
                    if offset > 1024 * 1024:
                        raise IntegrityError("Invalid PE header offset")
                    executable.seek(offset)
                    pe = executable.read(6)
                expected = {"x86": 0x14C, "x86_64": 0x8664, "arm64": 0xAA64}[
                    package.binary_arch
                ]
                if (
                    len(pe) != 6
                    or pe[:4] != b"PE\0\0"
                    or struct.unpack_from("<H", pe, 4)[0] != expected
                ):
                    raise IntegrityError(
                        "Executable architecture differs from the reviewed package"
                    )
            check()
            if runtime and runtime_cache:
                progress("runtime-copying", 0, len(runtime.files))
                deploy_runtime(runtime, runtime_cache, entrypoint.parent, check=check)
            receipt = Path(staging) / RECEIPT
            with receipt.open("x", encoding="utf-8") as stream:
                json.dump(
                    {
                        "schema_version": 1,
                        "package": asdict(package),
                        "runtime_verified": False,
                        "app_local_runtime": asdict(runtime) if runtime else None,
                    },
                    stream,
                    indent=2,
                )
                stream.flush()
                os.fsync(stream.fileno())
            check()
            # The extracted staging directory and target are on the same filesystem.
            rename_directory(Path(staging), target)
            staging = None
            progress("local", 1, 1)
            return target
        finally:
            try:
                if archive_name:
                    Path(archive_name).unlink(missing_ok=True)
            finally:
                if staging:
                    remove_tree(self.paths.components, Path(staging))

    def _download_and_verify(
        self,
        package: PackageSpec | RuntimeBundle,
        stream: IO[bytes],
        check: Callable[[], None] = lambda: None,
        progress: Progress = lambda _state, _done, _total: None,
    ) -> None:
        """Stream a bounded HTTPS response and require an exact SHA-256 match.

        Args:
            package (PackageSpec | RuntimeBundle): Reviewed component archive, platform
                and version metadata.
            stream (IO[bytes]): Binary stream receiving the verified download.
            check (Callable[[], None]): Callback that raises when cancellation is
                requested.
            progress (Progress): Worker callback reporting completed work without
                updating Tk.
        """
        size = 0
        request = urllib.request.Request(
            package.url,
            headers={
                "User-Agent": "LocalServer/0.1",
                "Referer": package.source or package.url,
            },
        )
        check()
        progress("downloading", 0, package.size_bytes)
        check()
        with self._open(request, timeout=10) as response:
            final_url = response.geturl()
            if urlsplit(final_url).scheme != "https":
                raise ValueError("Download redirected away from HTTPS")
            while True:
                check()
                block = response.read(256 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Download exceeds the maximum allowed size")
                if package.size_bytes and size > package.size_bytes:
                    raise IntegrityError("Download exceeds the reviewed archive size")
                stream.write(block)
                progress("downloading", size, package.size_bytes)
        if package.size_bytes and size != package.size_bytes:
            raise IntegrityError("Archive size differs from the reviewed package")
        stream.flush()
        progress("verifying", 0, size)
        check()
        digest = hashlib.sha256()
        verified = 0
        with open(stream.name, "rb") as downloaded:
            while block := downloaded.read(1024 * 1024):
                check()
                digest.update(block)
                verified += len(block)
                progress("verifying", verified, size)
        if digest.hexdigest().lower() != package.sha256.lower():
            raise IntegrityError(
                f"SHA-256 mismatch for {package.component} {package.version}"
            )

    def cleanup_incomplete(self) -> None:
        """Remove only abandoned private staging artifacts while holding the lock."""
        for path in self.paths.downloads.iterdir():
            if path.name.startswith((".package-", ".install-", ".remove-")):
                reject_links(self.paths.components, path)
                if path.is_dir():
                    remove_tree(self.paths.components, path)
                else:
                    path.unlink()


def remove_tree(root: Path, target: Path) -> None:
    """Delete a strictly contained tree only after rejecting every reparse point.

    Args:
        root (Path): Private root directory containing the managed resource.
        target (Path): Requested target platform or destination path.
    """
    absolute_root, absolute_target = root.absolute(), target.absolute()
    if absolute_target == absolute_root:
        raise ValueError("Refusing to remove the package root")
    reject_links(absolute_root, absolute_target)
    for directory, subdirs, files in os.walk(absolute_target, followlinks=False):
        for name in (*subdirs, *files):
            reject_links(absolute_root, Path(directory) / name)
    shutil.rmtree(absolute_target)

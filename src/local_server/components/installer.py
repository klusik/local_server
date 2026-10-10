"""Verified downloads and transactional private binary installations."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget

from .archive import safe_extract
from .catalog import PackageSpec

MAX_DOWNLOAD_BYTES = 2 * 1024**3


class IntegrityError(RuntimeError):
    """A downloaded binary package does not match its pinned SHA-256."""


class ComponentInstaller:
    """Install archive-based components without touching system directories."""

    def __init__(self, paths: AppPaths, target: PlatformTarget | None = None):
        self.paths = paths
        self.target = target or PlatformTarget.detect()

    def installed_path(self, package: PackageSpec) -> Path:
        """Return the platform-specific side-by-side binary installation path."""
        package.validate()
        return (
            self.paths.components
            / package.component
            / package.version
            / f"{package.os}-{package.arch}"
        )

    def install(self, package: PackageSpec) -> Path:
        """Download, verify and atomically activate a package in user storage.

        No external scripts are executed and no machine-wide installers run.
        A curated catalog must supply a verified SHA-256 and exact entrypoint.
        """
        package.validate()
        if (package.os, package.arch) != (self.target.os, self.target.arch):
            raise ValueError("Package architecture does not match this computer")

        target = self.installed_path(package)
        if target.exists():
            raise FileExistsError(f"Already installed: {target}")
        self.paths.ensure()
        target.parent.mkdir(parents=True, exist_ok=True)
        archive_name: str | None = None
        staging: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.paths.downloads, prefix=".package-", delete=False
            ) as file:
                archive_name = file.name
                self._download_and_verify(package, file)
            staging = tempfile.mkdtemp(prefix=".install-", dir=target.parent)
            safe_extract(
                Path(archive_name),
                Path(staging),
                package.archive,
                strip_components=package.strip_components,
            )
            entrypoint = Path(staging) / package.entrypoint.replace("\\", "/")
            if not entrypoint.is_file():
                raise ValueError(
                    f"Package is missing expected executable: {package.entrypoint}"
                )
            # The extracted staging directory and target are on the same filesystem.
            os.replace(staging, target)
            staging = None
            return target
        finally:
            if archive_name:
                Path(archive_name).unlink(missing_ok=True)
            if staging:
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _download_and_verify(package: PackageSpec, stream) -> None:
        """Stream a bounded HTTPS response and require an exact SHA-256 match."""
        digest = hashlib.sha256()
        size = 0
        request = urllib.request.Request(
            package.url, headers={"User-Agent": "LocalServer/0.1"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            if urlsplit(final_url).scheme != "https":
                raise ValueError("Download redirected away from HTTPS")
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_DOWNLOAD_BYTES:
                    raise ValueError("Download exceeds the maximum allowed size")
                digest.update(block)
                stream.write(block)
        if digest.hexdigest().lower() != package.sha256.lower():
            raise IntegrityError(
                f"SHA-256 mismatch for {package.component} {package.version}"
            )

"""All application-managed state stays inside a per-user directory."""

from __future__ import annotations

import os
import sys
import uuid
import tempfile
from dataclasses import dataclass
from pathlib import Path


def application_root() -> Path:
    """Locate the portable folder independently of the working directory."""
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).resolve()
        for parent in executable.parents:
            if parent.suffix.lower() == ".app":
                return parent.parent
        return executable.parent
    source_root = Path(__file__).resolve().parents[3]
    if (source_root / "pyproject.toml").is_file():
        return source_root
    # An installed launcher must be absolute; never resolve a relative argv[0]
    # against the caller's working directory.
    launcher = Path(sys.argv[0])
    return launcher.parent.resolve() if launcher.is_absolute() else Path(sys.executable).resolve().parent


def reject_links(root: Path, target: Path) -> None:
    """Refuse symlink/junction redirection anywhere below a managed root."""
    root, target = Path(root).absolute(), Path(target).absolute()
    target.relative_to(root)
    for path in (root, *reversed(target.relative_to(root).parents), target):
        candidate = path if path.is_absolute() else root / path
        if candidate.is_symlink() or (
            candidate.exists()
            and getattr(candidate.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise ValueError(f"Managed storage cannot contain links or junctions: {candidate}")


def default_app_data_dir() -> Path:
    """Resolve a writable, non-system application home for this OS."""
    override = os.environ.get("LOCAL_SERVER_HOME")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("LOCAL_SERVER_HOME must be an absolute path")
        return path

    return application_root() / ".local-server"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Central layout for downloaded archives, managed binaries and settings."""

    root: Path
    portable_root: Path | None = None

    @property
    def projects_file(self) -> Path:
        """Return the project profile JSON location."""
        return self.root / "projects.json"

    @property
    def downloads(self) -> Path:
        """Return the temporary package download directory."""
        return self.components / ".staging"

    @property
    def components(self) -> Path:
        """Return the private versioned binary installation directory."""
        return (self.portable_root or self.root) / "packages"

    @property
    def runtime_cache(self) -> Path:
        """Keep reviewed app-local runtime archives separate from server versions."""
        return self.components / ".runtime-cache"

    @property
    def databases(self) -> Path:
        """Reserve separate storage for future database data, never binaries."""
        return self.root / "data"

    @property
    def logs(self) -> Path:
        """Return the private managed process log directory."""
        return self.root / "logs"

    @property
    def generated(self) -> Path:
        """Return generated web-server configuration directories."""
        return self.root / "generated"

    def project_config_dir(self, project_id: str) -> Path:
        """Return a validated project's configuration directory."""
        try:
            name = str(uuid.UUID(project_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid project UUID") from exc
        return self.generated / name

    def ensure(self) -> None:
        """Create the private application directories on first launch."""
        for path in (
            self.root,
            self.downloads,
            self.components,
            self.logs,
            self.generated,
            self.databases,
            self.runtime_cache,
        ):
            base = self.components if path.is_relative_to(self.components) else self.root
            reject_links(base, path)
            try:
                path.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    path.chmod(0o700)
                with tempfile.TemporaryFile(dir=path):
                    pass
            except OSError as exc:
                raise OSError(f"Cannot write to portable storage: {path}. Move the application to a writable folder or select --data-dir for state.") from exc

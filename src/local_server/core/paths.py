"""All application-managed state stays inside a per-user directory."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


def default_app_data_dir() -> Path:
    """Resolve a writable, non-system application home for this OS."""
    override = os.environ.get("LOCAL_SERVER_HOME")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("LOCAL_SERVER_HOME must be an absolute path")
        return path

    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "LocalServer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LocalServer"
    xdg = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return xdg / "local-server"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Central layout for downloaded archives, managed binaries and settings."""

    root: Path

    @property
    def projects_file(self) -> Path:
        """Return the project profile JSON location."""
        return self.root / "projects.json"

    @property
    def downloads(self) -> Path:
        """Return the temporary package download directory."""
        return self.root / "downloads"

    @property
    def components(self) -> Path:
        """Return the private versioned binary installation directory."""
        return self.root / "components"

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
        ):
            path.mkdir(parents=True, exist_ok=True)
            if os.name != "nt":
                path.chmod(0o700)

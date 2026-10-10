"""Create, update, list and remove localhost project profiles."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from local_server.core.models import ProjectProfile
from local_server.core.store import ProjectStore


class ProjectService:
    """Coordinate project CRUD while preserving validated workspace state."""

    def __init__(self, store: ProjectStore):
        self.store = store

    def list_projects(self) -> list[ProjectProfile]:
        """Return all saved projects in display order."""
        return self.store.load()

    def create_project(
        self,
        name: str,
        document_root: str | Path,
        *,
        server: str = "nginx",
        php_version: str | None = None,
        http_port: int = 8080,
        mysql_enabled: bool = False,
    ) -> ProjectProfile:
        """Create a project pointing at an existing local directory."""
        root = Path(document_root).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("Choose an existing document root directory")
        candidate = ProjectProfile.create(
            name=name,
            document_root=root,
            server=server,
            php_version=php_version,
            http_port=http_port,
            mysql_enabled=mysql_enabled,
        )
        projects = self.store.load()
        self.store.save([*projects, candidate])
        return candidate

    def update_project(self, project: ProjectProfile) -> None:
        """Replace an existing profile without changing its identity."""
        project.validate()
        if not Path(project.document_root).is_dir():
            raise ValueError("Choose an existing document root directory")
        projects = self.store.load()
        if not any(current.id == project.id for current in projects):
            raise KeyError(f"Unknown project: {project.id}")
        self.store.save([
            project if current.id == project.id else current
            for current in projects
        ])

    def select_php_version(self, project_id: str, version: str | None) -> None:
        """Save a project's desired PHP version, without restarting processes."""
        project = self.get_project(project_id)
        self.update_project(replace(project, php_version=version))

    def get_project(self, project_id: str) -> ProjectProfile:
        """Return a profile by stable identifier."""
        for project in self.store.load():
            if project.id == project_id:
                return project
        raise KeyError(f"Unknown project: {project_id}")

    def delete_project(self, project_id: str) -> None:
        """Delete only the profile, never its document root or installed binaries."""
        projects = self.store.load()
        remaining = [project for project in projects if project.id != project_id]
        if len(remaining) == len(projects):
            raise KeyError(f"Unknown project: {project_id}")
        self.store.save(remaining)

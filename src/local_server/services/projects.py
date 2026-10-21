"""Create, update, list and remove localhost project profiles."""

from dataclasses import replace
from pathlib import Path

from local_server.core.models import ProjectProfile
from local_server.core.store import ProjectStore


class ProjectService:
    """Coordinate project CRUD while preserving validated workspace state."""

    def __init__(self, store: ProjectStore) -> None:
        """Bind profile lifecycle operations to the supplied store.

        Args:
            store (ProjectStore): Project profile persistence service.
        """
        self.store = store

    def list_projects(self) -> list[ProjectProfile]:
        """Return all saved projects in display order.

        Returns:
            list[ProjectProfile]: All validated saved profiles in display order.
        """
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
        nginx_package: str | None = None,
        php_package: str | None = None,
        mysql_package: str | None = None,
        mysql_port: int = 3307,
    ) -> ProjectProfile:
        """Create a project pointing at an existing local directory.

        Args:
            name (str): Human-readable project display name.
            document_root (str | Path): Existing project source directory; its files
                remain user owned.
            server (str): Requested web server identifier: nginx or apache.
            php_version (str | None): Requested PHP release, or None when unselected.
            http_port (int): Unprivileged IPv4 loopback HTTP port.
            mysql_enabled (bool): Whether this project explicitly requests a private
                MySQL instance.
            nginx_package (str | None): Exact selected local Nginx package identity, or
                None.
            php_package (str | None): Exact selected local PHP package identity, or
                None.
            mysql_package (str | None): Exact selected local MySQL package identity, or
                None.
            mysql_port (int): Unprivileged loopback port for the private MySQL instance.

        Returns:
            ProjectProfile: New validated profile after successful atomic persistence.
        """
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
            nginx_package=nginx_package,
            php_package=php_package,
            mysql_package=mysql_package,
            mysql_port=mysql_port,
        )
        projects = self.store.load()
        self.store.save([*projects, candidate])
        return candidate

    def update_project(self, project: ProjectProfile) -> None:
        """Replace an existing profile without changing its identity.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.
        """
        project.validate()
        if not Path(project.document_root).is_dir():
            raise ValueError("Choose an existing document root directory")
        projects = self.store.load()
        if not any(current.id == project.id for current in projects):
            raise KeyError(f"Unknown project: {project.id}")
        self.store.save(
            [project if current.id == project.id else current for current in projects]
        )

    def select_php_version(self, project_id: str, version: str | None) -> None:
        """Save a project's desired PHP version, without restarting processes.

        Args:
            project_id (str): Stable UUID of the saved project.
            version (str | None): Explicit component release identifier.
        """
        project = self.get_project(project_id)
        self.update_project(replace(project, php_version=version, php_package=None))

    def get_project(self, project_id: str) -> ProjectProfile:
        """Return a profile by stable identifier.

        Args:
            project_id (str): Stable UUID of the saved project.

        Returns:
            ProjectProfile: Saved profile matching the stable UUID.
        """
        for project in self.store.load():
            if project.id == project_id:
                return project
        raise KeyError(f"Unknown project: {project_id}")

    def delete_project(self, project_id: str) -> None:
        """Delete only the profile, never its document root or installed binaries.

        Args:
            project_id (str): Stable UUID of the saved project.
        """
        projects = self.store.load()
        remaining = [project for project in projects if project.id != project_id]
        if len(remaining) == len(projects):
            raise KeyError(f"Unknown project: {project_id}")
        self.store.save(remaining)

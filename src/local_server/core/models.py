"""Validated, serializable per-project web development profiles."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

SERVERS = frozenset({"nginx", "apache"})
_PHP_VERSION = re.compile(r"^[0-9]+\.[0-9]+(?:\.[0-9]+)?$")


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    """One localhost site and its desired, not necessarily installed, runtime."""

    id: str
    name: str
    document_root: str
    server: str = "nginx"
    php_version: str | None = None
    http_port: int = 8080
    mysql_enabled: bool = False

    def validate(self) -> None:
        """Reject invalid profiles before any disk or process operation."""
        try:
            uuid.UUID(self.id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Project id must be a UUID") from exc
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Project name must not be empty")
        if self.name != self.name.strip() or len(self.name) > 120:
            raise ValueError("Project name has invalid whitespace or length")
        if not isinstance(self.document_root, str) or not self.document_root:
            raise ValueError("Document root is required")
        if not Path(self.document_root).expanduser().is_absolute():
            raise ValueError("Document root must be an absolute path")
        if not isinstance(self.server, str) or self.server not in SERVERS:
            raise ValueError("Server must be nginx or apache")
        if self.php_version is not None and (
            not isinstance(self.php_version, str)
            or not _PHP_VERSION.fullmatch(self.php_version)
        ):
            raise ValueError("PHP version must look like 8.4 or 8.4.12")
        if (
            isinstance(self.http_port, bool)
            or not isinstance(self.http_port, int)
            or not 1024 <= self.http_port <= 65535
        ):
            raise ValueError("HTTP port must be between 1024 and 65535")
        if not isinstance(self.mysql_enabled, bool):
            raise ValueError("mysql_enabled must be a boolean")

    @classmethod
    def create(
        cls,
        name: str,
        document_root: str | Path,
        *,
        server: str = "nginx",
        php_version: str | None = None,
        http_port: int = 8080,
        mysql_enabled: bool = False,
    ) -> ProjectProfile:
        """Create a new project profile with a stable UUID."""
        result = cls(
            id=str(uuid.uuid4()),
            name=name.strip(),
            document_root=str(Path(document_root).expanduser().resolve()),
            server=server,
            php_version=php_version,
            http_port=http_port,
            mysql_enabled=mysql_enabled,
        )
        result.validate()
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ProjectProfile:
        """Deserialize a project without silently coercing field types."""
        if not isinstance(data, Mapping):
            raise ValueError("Project record must be a JSON object")
        try:
            profile = cls(
                id=data["id"],
                name=data["name"],
                document_root=data["document_root"],
                server=data.get("server", "nginx"),
                php_version=data.get("php_version"),
                http_port=data.get("http_port", 8080),
                mysql_enabled=data.get("mysql_enabled", False),
            )
        except KeyError as exc:
            raise ValueError(f"Missing project field: {exc.args[0]}") from exc
        profile.validate()
        return profile

    def to_dict(self) -> dict[str, Any]:
        """Convert this profile to a JSON-compatible record."""
        return asdict(self)

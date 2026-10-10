"""Versioned JSON project persistence with atomic writes."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable

from .models import ProjectProfile

SCHEMA_VERSION = 1


class ConfigurationError(RuntimeError):
    """The on-disk project settings cannot be safely loaded."""


class ProjectStore:
    """Read and atomically replace one user's project configuration."""

    def __init__(self, filename: Path):
        self.filename = Path(filename)

    def load(self) -> list[ProjectProfile]:
        """Load validated profiles or return an empty first-run workspace."""
        if not self.filename.exists():
            return []
        try:
            raw = json.loads(self.filename.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"Unsupported projects schema (expected {SCHEMA_VERSION})")
            records = raw.get("projects")
            if not isinstance(records, list):
                raise ValueError("projects must be a list")
            projects = [ProjectProfile.from_dict(record) for record in records]
            self._check_uniqueness(projects)
            return projects
        except (ValueError, TypeError, OSError) as exc:
            raise ConfigurationError(
                f"Invalid settings at {self.filename}: {exc}"
            ) from exc

    def save(self, projects: Iterable[ProjectProfile]) -> None:
        """Atomically persist validated profiles without partially written JSON."""
        items = list(projects)
        for project in items:
            project.validate()
        self._check_uniqueness(items)
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=f".{self.filename.name}.",
                suffix=".tmp",
                dir=self.filename.parent,
                delete=False,
            ) as stream:
                temp_name = stream.name
                if os.name != "nt":
                    os.chmod(temp_name, 0o600)
                json.dump(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "projects": [item.to_dict() for item in items],
                    },
                    stream,
                    indent=2,
                    ensure_ascii=False,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.filename)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

    @staticmethod
    def _check_uniqueness(items: list[ProjectProfile]) -> None:
        ids = [item.id for item in items]
        names = [item.name.casefold() for item in items]
        ports = [item.http_port for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate project UUIDs")
        if len(names) != len(set(names)):
            raise ValueError("Duplicate project names")
        if len(ports) != len(set(ports)):
            raise ValueError("Duplicate HTTP ports")

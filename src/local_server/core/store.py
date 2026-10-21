"""Versioned JSON project persistence with atomic writes."""

import json
import os
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from .models import ProjectProfile

SCHEMA_VERSION = 2


class ConfigurationError(RuntimeError):
    """The on-disk project settings cannot be safely loaded."""


class ProjectStore:
    """Read and atomically replace one user's project configuration."""

    def __init__(self, filename: Path, *, portable_root: Path | None = None) -> None:
        """Bind atomic profile persistence to an explicit portable root.

        Args:
            filename (Path): Private file path for persistence or ownership locking.
            portable_root (Path | None): Application folder used to resolve portable
                relative paths.
        """
        self.filename = Path(filename)
        self.portable_root = Path(portable_root).resolve() if portable_root else None

    def load(self) -> list[ProjectProfile]:
        """Load validated profiles or return an empty first-run workspace.

        Returns:
            list[ProjectProfile]: Validated profiles in stored order, or an empty list
                for a first run.
        """
        if not self.filename.exists():
            return []
        try:
            raw = json.loads(self.filename.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema_version") not in {
                1,
                SCHEMA_VERSION,
            }:
                raise ValueError(
                    f"Unsupported projects schema (expected {SCHEMA_VERSION})"
                )
            records = raw.get("projects")
            if not isinstance(records, list):
                raise ValueError("projects must be a list")
            projects = [
                ProjectProfile.from_dict(self._decode(record)) for record in records
            ]
            self._check_uniqueness(projects)
            return projects
        except (ValueError, TypeError, OSError) as exc:
            raise ConfigurationError(
                f"Invalid settings at {self.filename}: {exc}"
            ) from exc

    def save(self, projects: Iterable[ProjectProfile]) -> None:
        """Atomically persist validated profiles without partially written JSON.

        Args:
            projects (Iterable[ProjectProfile]): Profiles to validate and persist
                atomically.
        """
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
                        "projects": [self._encode(item) for item in items],
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
        """Reject duplicate project UUIDs, names and HTTP ports.

        Args:
            items (list[ProjectProfile]): Validated records to process in order.
        """
        ids = [item.id for item in items]
        names = [item.name.casefold() for item in items]
        ports = [item.http_port for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate project UUIDs")
        if len(names) != len(set(names)):
            raise ValueError("Duplicate project names")
        if len(ports) != len(set(ports)):
            raise ValueError("Duplicate HTTP ports")

    def _encode(self, project: ProjectProfile) -> dict[str, Any]:
        """Represent document roots relative to the portable folder where possible.

        Args:
            project (ProjectProfile): Validated profile whose resources remain isolated
                by project UUID.

        Returns:
            dict[str, Any]: Serializable profile with portable document-root
                representation where possible.
        """
        record = project.to_dict()
        if PureWindowsPath(project.document_root).is_absolute() and os.name != "nt":
            return record
        root = Path(project.document_root).resolve()
        if self.portable_root and root.is_relative_to(self.portable_root):
            record["document_root"] = {
                "portable": root.relative_to(self.portable_root).as_posix()
            }
        return record

    def _decode(self, record: dict[str, Any]) -> dict[str, Any]:
        """Resolve portable roots while rejecting paths outside application storage.

        Args:
            record (dict[str, Any]): Serialized input record to validate before use.

        Returns:
            dict[str, Any]: Profile record whose portable document root resolves inside
                application storage.
        """
        if not isinstance(record, dict):
            raise ValueError("Project record must be an object")
        result = dict(record)
        root = result.get("document_root")
        if isinstance(root, dict):
            if self.portable_root is None or set(root) != {"portable"}:
                raise ValueError("Portable document root needs an application root")
            relative = root["portable"]
            if (
                not isinstance(relative, str)
                or not relative
                or PurePosixPath(relative).is_absolute()
                or PureWindowsPath(relative).is_absolute()
                or ":" in relative
                or "\\" in relative
                or ".." in relative.split("/")
            ):
                raise ValueError("Unsafe portable document root")
            resolved = (self.portable_root / relative).resolve()
            if not resolved.is_relative_to(self.portable_root):
                raise ValueError("Document root escapes portable storage")
            result["document_root"] = str(resolved)
        return result

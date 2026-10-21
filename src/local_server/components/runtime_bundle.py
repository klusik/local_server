"""Explicitly reviewed app-local MSVC DLL archives; no installer execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit

from .archive import _relative_path

_DLLS = frozenset({
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
    "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll", "concrt140.dll",
})
_SHA256 = re.compile(r"[a-fA-F0-9]{64}")


def _safe_path(value: str) -> None:
    if (not isinstance(value, str) or not value or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise ValueError("Runtime paths must be canonical relative paths")
    _relative_path(value, 0)


@dataclass(frozen=True, slots=True)
class RuntimeDLL:
    """One permitted DLL mapped from a reviewed archive to an executable folder."""

    source: str
    name: str
    sha256: str

    def validate(self) -> None:
        """Reject system DLL replacement, ambiguous names and unpinned files."""
        _safe_path(self.source)
        if not isinstance(self.name, str) or self.name not in _DLLS:
            raise ValueError("Only approved app-local MSVC runtime DLL names are allowed")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("Each runtime DLL needs an exact SHA-256")


@dataclass(frozen=True, slots=True)
class RuntimeBundle:
    """A licensed binary ZIP reviewed by the maintainer, never an end-user SDK."""

    id: str
    version: str
    os: str
    arch: str
    url: str
    sha256: str
    size_bytes: int
    source: str
    license: str
    license_source: str
    files: tuple[RuntimeDLL, ...]
    notices: tuple[str, ...]
    archive: str = "zip"

    @property
    def component(self) -> str:
        """Label dependency download errors without treating it as a server."""
        return "vc-runtime"

    def validate(self) -> None:
        """Require version/architecture pins, per-DLL hashes and license notices."""
        if not isinstance(self.id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.id):
            raise ValueError("Invalid runtime bundle identifier")
        _safe_path(self.id)
        if not isinstance(self.version, str) or not re.fullmatch(r"14\.\d+\.\d+\.\d+", self.version):
            raise ValueError("Runtime version must pin all four version fields")
        if (self.os, self.arch, self.archive) != ("windows", "x86_64", "zip"):
            raise ValueError("Only reviewed Windows x64 app-local ZIP bundles are supported")
        for value in (self.url, self.source, self.license_source):
            if not isinstance(value, str):
                raise ValueError("Runtime sources must be HTTPS URLs")
            parsed = urlsplit(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
                raise ValueError("Runtime sources must be HTTPS URLs without credentials")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("Runtime archive needs an exact SHA-256")
        if not isinstance(self.size_bytes, int) or isinstance(self.size_bytes, bool) or not 0 < self.size_bytes <= 100 * 1024**2:
            raise ValueError("Runtime ZIP size must be pinned and bounded to 100 MiB")
        if not isinstance(self.license, str) or not self.license.strip() or not self.notices:
            raise ValueError("Runtime redistribution license and notices are required")
        names: set[str] = set()
        for dll in self.files:
            dll.validate()
            if dll.name in names:
                raise ValueError("Duplicate runtime DLL target")
            names.add(dll.name)
        if not {"vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"} <= names:
            raise ValueError("Runtime bundle must include the reviewed core MSVC DLL set")
        for notice in self.notices:
            _safe_path(notice)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RuntimeBundle:
        """Strictly deserialize a maintainer-curated archive and DLL mapping."""
        if not isinstance(data, Mapping):
            raise ValueError("Runtime bundle must be an object")
        try:
            record = dict(data)
            if not isinstance(record.get("files"), (list, tuple)) or not isinstance(record.get("notices"), (list, tuple)):
                raise ValueError("Runtime DLLs and notices must be lists")
            record["files"] = tuple(RuntimeDLL(**item) for item in record["files"])
            record["notices"] = tuple(record["notices"])
            bundle = cls(**record)
            bundle.validate()
            return bundle
        except (TypeError, KeyError) as exc:
            raise ValueError(f"Invalid runtime bundle: {exc}") from exc

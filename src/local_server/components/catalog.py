"""Explicit, SHA-256-pinned binary package metadata; no guessed download URLs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Mapping
from urllib.parse import urlsplit

from local_server.core.platform import PlatformTarget

_COMPONENTS = frozenset({"nginx", "apache", "php", "mysql"})
_ARCHIVES = frozenset({"zip", "tar.gz"})
_VERSIONS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


@dataclass(frozen=True, slots=True)
class PackageSpec:
    """One exact upstream artifact pinned to a digest and target architecture."""

    component: str
    version: str
    os: str
    arch: str
    url: str
    sha256: str
    archive: str
    entrypoint: str
    strip_components: int = 0

    def validate(self) -> None:
        """Validate metadata before touching the network or file system."""
        if self.component not in _COMPONENTS:
            raise ValueError(f"Unknown component: {self.component}")
        if not isinstance(self.version, str) or not _VERSIONS.fullmatch(self.version):
            raise ValueError("Invalid version identifier")
        if self.os not in {"windows", "macos"} or self.arch not in {"x86_64", "arm64"}:
            raise ValueError("Unsupported platform identifier")
        url = urlsplit(self.url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.fragment
        ):
            raise ValueError("Package URL must be an HTTPS URL without credentials")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("SHA-256 must contain 64 hexadecimal characters")
        if self.archive not in _ARCHIVES:
            raise ValueError("Only ZIP and tar.gz archives are supported")
        if not isinstance(self.strip_components, int) or isinstance(self.strip_components, bool):
            raise ValueError("strip_components must be an integer")
        if not 0 <= self.strip_components <= 5:
            raise ValueError("strip_components must be between 0 and 5")
        if not isinstance(self.entrypoint, str):
            raise ValueError("Invalid entrypoint")
        segments = self.entrypoint.replace("\\", "/").split("/")
        if not segments or any(
            part in {"", ".", ".."} or ":" in part for part in segments
        ):
            raise ValueError("Entrypoint must be a safe relative path")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PackageSpec:
        """Parse a package record without silently accepting unknown keys."""
        if not isinstance(data, Mapping):
            raise ValueError("Package metadata must be a JSON object")
        try:
            spec = cls(**data)
        except TypeError as exc:
            raise ValueError(f"Invalid package metadata: {exc}") from exc
        spec.validate()
        return spec


class PackageCatalog:
    """Resolve explicitly reviewed platform-specific component packages."""

    def __init__(self, packages: list[PackageSpec]):
        signatures: set[tuple[str, str, str, str]] = set()
        for package in packages:
            package.validate()
            key = (package.component, package.version, package.os, package.arch)
            if key in signatures:
                raise ValueError(f"Duplicate package entry: {key}")
            signatures.add(key)
        self.packages = tuple(packages)

    @classmethod
    def from_json(cls, content: str) -> PackageCatalog:
        """Read a versioned package catalog."""
        raw = json.loads(content)
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ValueError("Unsupported package catalog schema")
        if not isinstance(raw.get("packages"), list):
            raise ValueError("Catalog packages must be a list")
        return cls([PackageSpec.from_dict(row) for row in raw["packages"]])

    @classmethod
    def bundled(cls) -> PackageCatalog:
        """Read the curated package manifest shipped with this application."""
        content = (
            files("local_server.components")
            .joinpath("package_catalog.json")
            .read_text(encoding="utf-8")
        )
        return cls.from_json(content)

    def find(
        self, component: str, version: str, target: PlatformTarget
    ) -> PackageSpec:
        """Return a pinned package or explicitly report that it is unavailable."""
        for package in self.packages:
            if (
                package.component == component
                and package.version == version
                and package.os == target.os
                and package.arch == target.arch
            ):
                return package
        raise LookupError(
            f"No verified {component} {version} package for {target.os}/{target.arch}"
        )

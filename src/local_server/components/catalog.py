"""Explicit, SHA-256-pinned binary package metadata; no guessed download URLs."""

import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Mapping
from urllib.parse import urlsplit

from local_server.core.platform import PlatformTarget

from .archive import _relative_path
from .runtime_bundle import RuntimeBundle

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
    variant: str = "default"
    binary_arch: str = "x86_64"
    source: str = ""
    checksum_source: str = ""
    license: str = ""
    requirements: tuple[str, ...] | list[str] = ()
    notes: str = ""
    size_bytes: int = 0
    vc_minimum: str = ""
    runtime_bundle: str = ""

    def __post_init__(self) -> None:
        """Normalize runtime package requirements to an immutable tuple."""
        if isinstance(self.requirements, list):
            object.__setattr__(self, "requirements", tuple(self.requirements))

    def validate(self) -> None:
        """Validate metadata before touching the network or file system."""
        if self.component not in _COMPONENTS:
            raise ValueError(f"Unknown component: {self.component}")
        if not isinstance(self.version, str) or not _VERSIONS.fullmatch(self.version):
            raise ValueError("Invalid version identifier")
        for identifier in (self.version, self.variant):
            if not isinstance(identifier, str) or not _VERSIONS.fullmatch(identifier):
                raise ValueError("Invalid package identifier")
            _relative_path(identifier, 0)
        if self.os not in {"windows", "macos"} or self.arch not in {"x86_64", "arm64"}:
            raise ValueError("Unsupported platform identifier")
        if self.binary_arch not in {"x86", "x86_64", "arm64"}:
            raise ValueError("Unsupported binary architecture")
        if self.binary_arch != self.arch and not (
            self.os == "windows" and self.arch == "x86_64" and self.binary_arch == "x86"
        ):
            raise ValueError("Incompatible binary architecture")
        if (
            self.component == "php"
            and self.os == "windows"
            and self.variant != "nts-cgi"
        ):
            raise ValueError(
                "Windows PHP acquisition supports NTS CGI/FastCGI only; "
                "TS/mod_php and FPM are unavailable"
            )
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes < 0
        ):
            raise ValueError("Invalid archive size")
        if self.vc_minimum and not re.fullmatch(r"14\.\d+\.\d+\.\d+", self.vc_minimum):
            raise ValueError("Invalid Visual C++ minimum version")
        if not isinstance(self.runtime_bundle, str):
            raise ValueError("Invalid runtime bundle reference")
        if self.runtime_bundle:
            if not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", self.runtime_bundle
            ):
                raise ValueError("Invalid runtime bundle reference")
            _relative_path(self.runtime_bundle, 0)
            if (
                self.os != "windows"
                or self.binary_arch != "x86_64"
                or not self.vc_minimum
            ):
                raise ValueError(
                    "App-local runtime requires an explicit Windows x64 runtime floor"
                )
        if not isinstance(self.requirements, (tuple, list)) or not all(
            isinstance(r, str) for r in self.requirements
        ):
            raise ValueError("Invalid requirements")
        for field in (self.source, self.checksum_source, self.license, self.notes):
            if not isinstance(field, str) or "\r" in field or "\n" in field:
                raise ValueError(
                    "Package source and display fields must be single-line strings"
                )
        if self.source:
            source = urlsplit(self.source)
            if (
                source.scheme != "https"
                or not source.hostname
                or source.username is not None
                or source.password is not None
                or source.fragment
            ):
                raise ValueError("Package source must be HTTPS without credentials")
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
        if not isinstance(self.strip_components, int) or isinstance(
            self.strip_components, bool
        ):
            raise ValueError("strip_components must be an integer")
        if not 0 <= self.strip_components <= 5:
            raise ValueError("strip_components must be between 0 and 5")
        if not isinstance(self.entrypoint, str):
            raise ValueError("Invalid entrypoint")
        _relative_path(self.entrypoint, 0)
        segments = self.entrypoint.replace("\\", "/").split("/")
        if not segments or any(
            part in {"", ".", ".."} or ":" in part for part in segments
        ):
            raise ValueError("Entrypoint must be a safe relative path")

    @classmethod
    def from_dict(cls, data: object) -> "PackageSpec":
        """Parse a package record without silently accepting unknown keys.

        Args:
            data (object): Serialized input record validated before constructing an
                instance.

        Returns:
            PackageSpec: Validated instance constructed from the serialized input
                record.
        """
        if not isinstance(data, Mapping):
            raise ValueError("Package metadata must be a JSON object")
        try:
            spec = cls(**data)
        except TypeError as exc:
            raise ValueError(f"Invalid package metadata: {exc}") from exc
        spec.validate()
        return spec

    @property
    def key(self) -> str:
        """Stable relative identity; never includes a drive or application path.

        Returns:
            str: Stable component/version/platform/variant package identity.
        """
        return f"{self.component}/{self.version}/{self.os}-{self.arch}/{self.variant}"


class PackageCatalog:
    """Resolve explicitly reviewed platform-specific component packages."""

    def __init__(
        self, packages: list[PackageSpec], runtimes: list[RuntimeBundle] | None = None
    ) -> None:
        """Validate package identities and their reviewed runtime dependencies.

        Args:
            packages (list[PackageSpec]): Reviewed package specifications available to
                the manager.
            runtimes (list[RuntimeBundle] | None): Reviewed runtime bundle
                specifications.
        """
        self.runtime_bundles: dict[str, RuntimeBundle] = {}
        for bundle in runtimes or []:
            bundle.validate()
            if bundle.id.casefold() in {key.casefold() for key in self.runtime_bundles}:
                raise ValueError("Duplicate runtime bundle identifier")
            self.runtime_bundles[bundle.id] = bundle
        signatures: set[str] = set()
        for package in packages:
            package.validate()
            if package.runtime_bundle:
                selected_bundle = self.runtime_bundles.get(package.runtime_bundle)
                if selected_bundle is None or (
                    selected_bundle.os,
                    selected_bundle.arch,
                ) != (package.os, package.binary_arch):
                    raise ValueError("Missing or incompatible app-local runtime bundle")
                if tuple(map(int, selected_bundle.version.split("."))) < tuple(
                    map(int, package.vc_minimum.split("."))
                ):
                    raise ValueError(
                        "App-local runtime is older than the package requirement"
                    )
            key = package.key.casefold()
            if key in signatures:
                raise ValueError(f"Duplicate package entry: {key}")
            signatures.add(key)
        self.packages = tuple(packages)

    @classmethod
    def from_json(cls, content: str) -> "PackageCatalog":
        """Read a versioned package catalog.

        Args:
            content (str): Serialized catalog content to validate and decode.

        Returns:
            PackageCatalog: Validated package catalog including reviewed runtime
                dependencies.
        """
        raw = json.loads(content)
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ValueError("Unsupported package catalog schema")
        if not isinstance(raw.get("packages"), list):
            raise ValueError("Catalog packages must be a list")
        if not isinstance(raw.get("runtime_bundles", []), list):
            raise ValueError("Runtime bundles must be a list")
        return cls(
            [PackageSpec.from_dict(row) for row in raw["packages"]],
            [RuntimeBundle.from_dict(row) for row in raw.get("runtime_bundles", [])],
        )

    @classmethod
    def bundled(cls) -> "PackageCatalog":
        """Read the curated package manifest shipped with this application.

        Returns:
            PackageCatalog: Validated catalog loaded from the application package
                resources.
        """
        content = (
            files("local_server.components")
            .joinpath("package_catalog.json")
            .read_text(encoding="utf-8")
        )
        return cls.from_json(content)

    def find(
        self,
        component: str,
        version: str,
        target: PlatformTarget,
        *,
        variant: str = "default",
    ) -> PackageSpec:
        """Return a pinned package or explicitly report that it is unavailable.

        Args:
            component (str): Component identifier used to filter available packages.
            version (str): Explicit component release identifier.
            target (PlatformTarget): Requested target platform or destination path.
            variant (str): Reviewed binary variant identifier.

        Returns:
            PackageSpec: Exact reviewed package matching the requested component and
                platform.
        """
        for package in self.packages:
            if (
                package.component == component
                and package.version == version
                and package.os == target.os
                and package.arch == target.arch
                and package.variant == variant
            ):
                return package
        raise LookupError(
            f"No verified {component} {version} package for {target.os}/{target.arch}"
        )

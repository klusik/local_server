"""Normalize supported operating systems and CPU architectures."""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlatformTarget:
    """Portable identifiers used by the component download catalog."""

    os: str
    arch: str

    @classmethod
    def detect(cls) -> PlatformTarget:
        """Detect a supported Windows or macOS platform."""
        if sys.platform == "win32":
            os_name = "windows"
        elif sys.platform == "darwin":
            os_name = "macos"
        else:
            raise NotImplementedError("The managed runtime targets Windows and macOS")

        arch = platform.machine().lower()
        if arch in {"amd64", "x86_64", "x64"}:
            arch = "x86_64"
        elif arch in {"arm64", "aarch64"}:
            arch = "arm64"
        else:
            raise NotImplementedError(f"Unsupported CPU architecture: {arch}")
        return cls(os=os_name, arch=arch)

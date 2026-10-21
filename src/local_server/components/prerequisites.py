"""Read-only Windows prerequisite checks; never install or execute anything."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .catalog import PackageSpec


def prerequisite_issues(package: PackageSpec, *, app_local: bool = False) -> list[str]:
    """Report missing host prerequisites without loading package executables."""
    issues: list[str] = []
    if package.os != "windows":
        return ["No reviewed binary dependency checks exist for this platform."]
    if sys.platform != "win32":
        return ["This package requires Windows x64."]
    if sys.getwindowsversion().major < 10:
        issues.append("The curated packages require Windows 10 or newer.")
    if package.binary_arch == "x86":
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        if not (system_root / "SysWOW64" / "ntdll.dll").is_file():
            issues.append("The official 32-bit Nginx archive requires Windows x64 with WoW64 enabled.")
    if package.vc_minimum and not app_local:
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
            ) as key:
                installed = winreg.QueryValueEx(key, "Installed")[0]
                version = str(winreg.QueryValueEx(key, "Version")[0]).lstrip("v")
            actual = tuple(int(part) for part in version.split("."))
            required = tuple(int(part) for part in package.vc_minimum.split("."))
            if installed != 1 or actual < required:
                raise ValueError("older runtime")
            system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
            for dll in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
                if not (system / dll).is_file():
                    raise ValueError(f"missing {dll}")
        except (OSError, ValueError, TypeError):
            issues.append(f"Microsoft Visual C++ x64 {package.vc_minimum} or newer is required. Local Server does not install it.")
    return issues

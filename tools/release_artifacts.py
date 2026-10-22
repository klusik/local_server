"""Bind the two Windows distribution files to the exact release build plan."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from tools.release import ReleasePlan, validate_version


def asset_names(version: str) -> tuple[str, str]:
    """Name the portable and installer executables unambiguously.

    Args:
        version (str): Validated release tag including its v_ prefix.

    Returns:
        tuple[str, str]: Versioned portable EXE name followed by installer EXE name.
    """
    validate_version(version)
    return (
        f"LocalServer-{version}-windows-x64-portable.exe",
        f"LocalServer-{version}-windows-x64-installer.exe",
    )


def file_record(path: Path) -> dict[str, Any]:
    """Measure one regular, nonempty executable without loading or executing it.

    Args:
        path (Path): Expected distribution file inside the artifact directory.

    Returns:
        dict[str, Any]: Byte length and SHA-256 digest of the exact distribution bytes.
    """
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing or invalid distribution file: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"size": path.stat().st_size, "sha256": digest}


def write_manifest(directory: Path, plan: ReleasePlan) -> None:
    """Record completed build outputs only after executable and installer smoke checks.

    Args:
        directory (Path): Build output directory containing both final EXEs.
        plan (ReleasePlan): Immutable source/tooling/version inputs for this build.
    """
    content = {
        "schema": 1,
        "plan": asdict(plan),
        "files": {
            name: file_record(directory / name) for name in asset_names(plan.version)
        },
    }
    (directory / "manifest.json").write_text(
        json.dumps(content, indent=2) + "\n", encoding="utf-8"
    )


def verify_artifacts(directory: Path, plan: ReleasePlan) -> dict[str, Any]:
    """Reject missing, modified or differently sourced artifacts before merging main.

    Args:
        directory (Path): Artifact downloaded from the successful build in this run.
        plan (ReleasePlan): Selection job's original immutable release inputs.

    Returns:
        dict[str, Any]: Verified filename-to-size/hash records for draft release uploads.
    """
    names = asset_names(plan.version)
    if {path.name for path in directory.iterdir()} != {*names, "manifest.json"}:
        raise ValueError(
            "Release artifact must contain exactly two EXEs and its manifest."
        )
    manifest_path = directory / "manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Artifact manifest must not be a link.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {name: file_record(directory / name) for name in names}
    if manifest != {"schema": 1, "plan": asdict(plan), "files": records}:
        raise ValueError("Build artifact contents or pinned release plan do not match.")
    return records

"""Build and smoke-check the two Windows assets before release can modify main."""

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from tools.integrate_develop import ROOT, git
from tools.release import ReleasePlan
from tools.release_artifacts import asset_names, file_record, write_manifest


def run(arguments: Sequence[str], cwd: Path, clean_python: bool = False) -> None:
    """Run a bounded packaging command without a shell or elevation.

    Args:
        arguments (Sequence[str]): Literal executable path and process arguments.
        cwd (Path): Explicit working directory for the process.
        clean_python (bool): Remove developer Python/Tk paths for standalone probes.
    """
    environment = dict(os.environ)
    if clean_python:
        for name in tuple(environment):
            if name.startswith("PYTHON") or name in {
                "TCL_LIBRARY",
                "TK_LIBRARY",
                "LOCAL_SERVER_HOME",
            }:
                environment.pop(name)
        environment["PATH"] = str(Path(environment["SystemRoot"]) / "System32")
    subprocess.run(list(arguments), cwd=cwd, env=environment, check=True, timeout=300)


def require_user_manifest(executable: Path) -> None:
    """Require an asInvoker execution manifest on the actual generated PE file.

    Args:
        executable (Path): Built portable executable or Inno installer.
    """
    pefile = importlib.import_module("pefile")
    pe = pefile.PE(str(executable))
    try:
        manifests: list[bytes] = []
        for resource in pe.DIRECTORY_ENTRY_RESOURCE.entries:
            if resource.id == 24:
                for entry in resource.directory.entries:
                    for language in entry.directory.entries:
                        data = language.data.struct
                        manifests.append(pe.get_data(data.OffsetToData, data.Size))
        if len(manifests) != 1:
            raise ValueError("Expected one execution manifest in the generated EXE.")
        from xml.etree import ElementTree

        root = ElementTree.fromstring(manifests[0])
        levels = [
            node.get("level")
            for node in root.iter()
            if node.tag.endswith("requestedExecutionLevel")
        ]
        if levels != ["asInvoker"]:
            raise ValueError(
                "Generated EXE must run asInvoker without requesting elevation."
            )
    finally:
        pe.close()


def smoke(executable: Path, directory: Path, version: str) -> None:
    """Execute the real bundled Tk/catalog/storage probe without Python on PATH.

    Args:
        executable (Path): Standalone EXE to launch without developer dependencies.
        directory (Path): Working directory outside the executable's own directory.
        version (str): Expected display version without the v_ tag prefix.
    """
    result = directory / "bundle-smoke.json"
    result.unlink(missing_ok=True)
    run(
        [str(executable), "--bundle-smoke-output", str(result)],
        directory,
        clean_python=True,
    )
    data = json.loads(result.read_text(encoding="utf-8"))
    root = executable.parent.resolve()
    expected = {
        "version": version,
        "root": str(root),
        "state": str(root / ".local-server"),
        "packages": str(root / "packages"),
    }
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "Frozen version or portable storage follows an incorrect directory."
        )
    if not data.get("tk") or data.get("catalog_entries", 0) < 1:
        raise ValueError("Tk or bundled component catalog is missing.")


def version_resource(version: str) -> str:
    """Generate numeric Windows version information from a validated release tag.

    Args:
        version (str): Release tag in v_X.Y or v_X.Y.Z format.

    Returns:
        str: PyInstaller version resource expression with four numeric components.
    """
    from tools.release import validate_version

    validate_version(version)
    parts = [int(part) for part in version[2:].split(".")]
    if any(part > 65535 for part in parts):
        raise ValueError("Windows version components must be at most 65535.")
    numbers = tuple(parts + [0] * (4 - len(parts)))
    label = version[2:]
    return (
        "VSVersionInfo(ffi=FixedFileInfo("
        f"filevers={numbers!r},prodvers={numbers!r},mask=0x3f,flags=0,"
        "OS=0x40004,fileType=1,subtype=0,date=(0,0)),kids=["
        "StringFileInfo([StringTable('040904B0',["
        "StringStruct('ProductName','Local Server'),"
        "StringStruct('FileDescription','Local Server portable'),"
        f"StringStruct('FileVersion','{label}'),StringStruct('ProductVersion','{label}')"
        "])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])\n"
    )


def build(plan: ReleasePlan, source: Path, output: Path, compiler: Path) -> None:
    """Build one-file Python/Tk distribution and a per-user Inno Setup 7 installer.

    Args:
        plan (ReleasePlan): Immutable qualified develop and workflow selected by CI.
        source (Path): Separate checkout of the exact qualified develop commit.
        output (Path): Empty output directory reserved for the two assets and manifest.
        compiler (Path): Pinned Inno Setup 7 compiler installed per-user on the CI runner.
    """
    if sys.platform != "win32" or sys.version_info < (3, 14):
        raise ValueError("Windows release builds require Windows and Python 3.14+.")
    if git(["rev-parse", "HEAD"], source) != plan.develop:
        raise ValueError("Build source differs from selected develop.")
    if git(["rev-parse", "HEAD"], ROOT) != plan.workflow:
        raise ValueError("Build tooling differs from the selected workflow commit.")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Build output directory must be empty.")
    portable_name, installer_name = asset_names(plan.version)
    with tempfile.TemporaryDirectory(prefix="local-server-build-") as temporary:
        scratch = Path(temporary).resolve()
        version_file = scratch / "release-version.txt"
        version_file.write_text(plan.version[2:], encoding="utf-8")
        resource = scratch / "version.txt"
        resource.write_text(version_resource(plan.version), encoding="utf-8")
        run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--noupx",
                "--name",
                Path(portable_name).stem,
                "--distpath",
                str(output),
                "--workpath",
                str(scratch / "work"),
                "--specpath",
                str(scratch),
                "--paths",
                str(source / "src"),
                "--add-data",
                f"{version_file}:.",
                "--add-data",
                (
                    f"{source / 'src/local_server/components/package_catalog.json'}:"
                    "local_server/components"
                ),
                "--version-file",
                str(resource),
                str(ROOT / "tools/frozen_entry.py"),
            ],
            ROOT,
        )
        portable = output / portable_name
        require_user_manifest(portable)
        for folder in ("portable", "relocated portable"):
            location = scratch / folder
            location.mkdir()
            executable = location / portable_name
            shutil.copy2(portable, executable)
            smoke(executable, scratch, plan.version[2:])
        run(
            [
                str(compiler),
                f"/DAppVersion={plan.version[2:]}",
                f"/DSourceExe={portable}",
                f"/DOutputDir={output}",
                f"/DOutputName={Path(installer_name).stem}",
                str(ROOT / "packaging/windows.iss"),
            ],
            ROOT,
        )
        installer = output / installer_name
        require_user_manifest(installer)
        installed = scratch / "installed"
        run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/SP-",
                f"/DIR={installed}",
                f"/LOG={scratch / 'install.log'}",
            ],
            scratch,
        )
        try:
            executable = installed / "LocalServer.exe"
            if file_record(executable) != file_record(portable):
                raise ValueError("Installer did not contain the exact portable EXE.")
            smoke(executable, scratch, plan.version[2:])
            marker = installed / ".local-server/keep.txt"
            marker.write_text("retain user data", encoding="utf-8")
        finally:
            run(
                [
                    str(installed / "unins000.exe"),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                ],
                scratch,
            )
        if marker.read_text(encoding="utf-8") != "retain user data":
            raise ValueError("Uninstall removed user data.")
        if executable.exists():
            raise ValueError("Uninstall did not remove the application executable.")
    write_manifest(output, plan)


def main() -> int:
    """Build verified Windows release artifacts from the CI selection plan.

    Returns:
        int: Zero when both final EXEs and their content manifest are ready.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--inno", required=True, type=Path)
    args = parser.parse_args()
    build(
        ReleasePlan.from_json(args.plan_json),
        args.source.resolve(),
        args.output.resolve(),
        args.inno.resolve(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

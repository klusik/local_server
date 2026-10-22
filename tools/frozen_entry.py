"""Launch the bundled application and provide an offline packaging smoke probe."""

import json
import sys
from pathlib import Path

import local_server


def bundle_smoke(output: Path) -> None:
    """Check bundled Python, Tk, catalog resources and writable portable storage.

    Args:
        output (Path): Absolute JSON result path supplied by the CI packaging probe.
    """
    import tkinter as tk

    from local_server.components.catalog import PackageCatalog
    from local_server.core.paths import AppPaths, application_root, default_app_data_dir

    if not output.is_absolute() or not getattr(sys, "frozen", False):
        raise ValueError(
            "Bundle smoke requires a frozen app and an absolute result path."
        )
    root = application_root()
    if root != Path(sys.executable).resolve().parent:
        raise ValueError(
            "Frozen storage must follow the executable, not its extraction directory."
        )
    paths = AppPaths(default_app_data_dir(), root)
    paths.ensure()
    catalog = PackageCatalog.bundled()
    window = tk.Tk()
    try:
        window.withdraw()
        window.update()
        result = {
            "version": local_server.__version__,
            "root": str(root),
            "state": str(paths.root),
            "packages": str(paths.components),
            "catalog_entries": len(catalog.packages),
            "tk": str(window.tk.call("info", "patchlevel")),
        }
        output.write_text(json.dumps(result), encoding="utf-8")
    finally:
        window.destroy()


def main() -> int:
    """Load build-time version metadata and launch the application or bundle probe.

    Returns:
        int: Application exit status; zero after a successful offline smoke probe.
    """
    local_server.__version__ = (
        Path(__file__)
        .with_name("release-version.txt")
        .read_text(encoding="utf-8")
        .strip()
    )
    if len(sys.argv) == 3 and sys.argv[1] == "--bundle-smoke-output":
        bundle_smoke(Path(sys.argv[2]))
        return 0
    from local_server.app import main as run

    return run()


if __name__ == "__main__":
    raise SystemExit(main())

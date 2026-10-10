"""Application composition root and command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from local_server import __version__
from local_server.core.paths import AppPaths, default_app_data_dir
from local_server.core.store import ProjectStore
from local_server.services.projects import ProjectService


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the Tk desktop app using per-user application data."""
    parser = argparse.ArgumentParser(description="Local Server desktop manager")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override the per-user application data directory",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    root = (args.data_dir or default_app_data_dir()).expanduser().resolve()
    paths = AppPaths(root)
    paths.ensure()
    service = ProjectService(ProjectStore(paths.projects_file))

    # Tk is imported only on GUI launch, so headless tests work without a display.
    try:
        from local_server.ui.main_window import MainWindow

        window = MainWindow(service=service, paths=paths)
    except Exception as exc:
        import tkinter

        if isinstance(exc, tkinter.TclError):
            print(f"Unable to launch Tkinter: {exc}", file=sys.stderr)
            return 1
        raise
    window.mainloop()
    return 0

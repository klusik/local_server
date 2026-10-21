"""Application composition root and command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from local_server import __version__
from local_server.core.paths import AppPaths, application_root, default_app_data_dir
from local_server.core.store import ProjectStore
from local_server.services.projects import ProjectService


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the Tk desktop app using per-user application data."""
    parser = argparse.ArgumentParser(description="Local Server desktop manager")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override portable state storage (packages stay beside the application)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    try:
        root = (args.data_dir or default_app_data_dir()).expanduser().resolve()
        paths = AppPaths(root, application_root())
        paths.ensure()
    except (ValueError, OSError) as exc:
        print(f"Cannot open portable storage: {exc}", file=sys.stderr)
        try:
            from tkinter import messagebox
            messagebox.showerror("Portable storage unavailable", str(exc))
        except Exception:
            pass  # stderr remains available if Tk/display is unavailable.
        return 1
    service = ProjectService(ProjectStore(paths.projects_file, portable_root=paths.portable_root))

    # Tk is imported only on GUI launch, so headless tests work without a display.
    try:
        import tkinter as tk
        from local_server.ui.main_window import MainWindow
    except ImportError as exc:
        print(f"Tkinter is missing from this Python distribution: {exc}", file=sys.stderr)
        return 1

    try:
        window = MainWindow(service=service, paths=paths)
    except tk.TclError as exc:
        print(f"Unable to launch Tkinter: {exc}", file=sys.stderr)
        return 1
    window.mainloop()
    return 0

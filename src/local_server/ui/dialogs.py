"""Project profile editor using only the Python standard library."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from local_server.core.models import ProjectProfile


class ProjectDialog(tk.Toplevel):
    """Modal editor for one project's directory and desired runtime versions."""

    def __init__(
        self, parent: tk.Misc, existing: ProjectProfile | None = None
    ) -> None:
        super().__init__(parent)
        self.existing = existing
        self.result: ProjectProfile | None = None
        self.title("Edit project" if existing else "Add project")
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.name_var = tk.StringVar(value=existing.name if existing else "")
        self.root_var = tk.StringVar(
            value=existing.document_root if existing else str(Path.home())
        )
        self.server_var = tk.StringVar(
            value=existing.server if existing else "nginx"
        )
        self.php_var = tk.StringVar(
            value=existing.php_version or "" if existing else ""
        )
        self.port_var = tk.StringVar(
            value=str(existing.http_port) if existing else "8080"
        )
        self.mysql_var = tk.BooleanVar(
            value=existing.mysql_enabled if existing else False
        )

        content = ttk.Frame(self, padding=16)
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(1, weight=1)

        fields = [
            ("Project name", self.name_var),
            ("Document root", self.root_var),
            ("PHP version", self.php_var),
            ("HTTP port", self.port_var),
        ]
        for row, (title, variable) in enumerate(fields):
            ttk.Label(content, text=title).grid(
                row=row, column=0, sticky="w", pady=5, padx=(0, 12)
            )
            entry = ttk.Entry(content, textvariable=variable, width=42)
            entry.grid(row=row, column=1, sticky="ew", pady=5)
            if row == 1:
                ttk.Button(content, text="Browse…", command=self._browse).grid(
                    row=row, column=2, padx=(8, 0)
                )

        ttk.Label(content, text="Web server").grid(
            row=4, column=0, sticky="w", pady=5, padx=(0, 12)
        )
        server_picker = ttk.Combobox(
            content,
            textvariable=self.server_var,
            values=("nginx", "apache"),
            state="readonly",
            width=18,
        )
        server_picker.grid(row=4, column=1, sticky="w", pady=5)

        ttk.Checkbutton(
            content, text="Use MySQL (planned)", variable=self.mysql_var
        ).grid(row=5, column=1, sticky="w", pady=(6, 0))
        ttk.Label(
            content,
            text="PHP is a desired version, not an installed runtime yet.",
            foreground="#656565",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 0))

        buttons = ttk.Frame(content)
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(buttons, text="Save", command=self._save).pack(side="right")

        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self._save())
        self.grab_set()
        self.wait_window(self)

    def _browse(self) -> None:
        """Let the user explicitly choose an existing project directory."""
        selected = filedialog.askdirectory(
            parent=self, title="Choose document root", initialdir=self.root_var.get()
        )
        if selected:
            self.root_var.set(selected)

    def _save(self) -> None:
        """Validate the edited fields and close with a complete profile."""
        try:
            port = int(self.port_var.get().strip())
            root = Path(self.root_var.get().strip()).expanduser().resolve()
            if not root.is_dir():
                raise ValueError("Document root must be an existing directory")
            kwargs = {
                "name": self.name_var.get().strip(),
                "document_root": str(root),
                "server": self.server_var.get(),
                "php_version": self.php_var.get().strip() or None,
                "http_port": port,
                "mysql_enabled": self.mysql_var.get(),
            }
            if self.existing is None:
                candidate = ProjectProfile.create(**kwargs)
            else:
                candidate = replace(self.existing, **kwargs)
            candidate.validate()
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid project", str(exc), parent=self)
            return
        self.result = candidate
        self.destroy()

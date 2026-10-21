"""Project profile editor using only the Python standard library."""

import queue
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TypedDict, cast

from local_server.components.catalog import PackageSpec
from local_server.core.models import ProjectProfile
from local_server.services.background import BackgroundIO

from .theme import BACKGROUND, ToggleSwitch, icon_button


class _FormValues(TypedDict):
    """Snapshot of editor values captured on the Tk thread."""

    name: str
    document_root: str
    server: str
    php_version: str | None
    port: str
    mysql_enabled: bool
    nginx_package: str | None
    php_package: str | None
    mysql_package: str | None
    mysql_port: str


class _ProfileValues(TypedDict):
    """Validated fields passed to profile construction or replacement."""

    name: str
    document_root: str
    server: str
    php_version: str | None
    http_port: int
    mysql_enabled: bool
    nginx_package: str | None
    php_package: str | None
    mysql_package: str | None
    mysql_port: int


class ProjectDialog(tk.Toplevel):
    """Modal editor for one project's directory and desired runtime versions."""

    def __init__(
        self,
        parent: tk.Misc,
        existing: ProjectProfile | None = None,
        *,
        suggested_port: int = 8080,
        local_packages: tuple[PackageSpec, ...] = (),
    ) -> None:
        """Build a modal editor and capture an optional existing profile.

        Args:
            parent (tk.Misc): Tk parent that owns this widget or dialog.
            existing (ProjectProfile | None): Profile being edited, or None when
                creating a profile.
            suggested_port (int): Initial HTTP port suggested for a new profile.
            local_packages (tuple[PackageSpec, ...]): Receipt-backed local versions
                available for explicit selection.
        """
        super().__init__(parent)
        self.configure(background=BACKGROUND)
        self.existing = existing
        self.result: ProjectProfile | None = None
        self._io = BackgroundIO()
        self._closing = False
        self.title("Edit project" if existing else "Add project")
        self.resizable(False, False)
        self.transient(cast(tk.Wm, parent))
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.name_var = tk.StringVar(value=existing.name if existing else "")
        self.root_var = tk.StringVar(
            value=existing.document_root if existing else str(Path.home())
        )
        self.server_var = tk.StringVar(value=existing.server if existing else "nginx")
        self.php_var = tk.StringVar(
            value=existing.php_version or "" if existing else ""
        )
        self.port_var = tk.StringVar(
            value=str(existing.http_port) if existing else str(suggested_port)
        )
        self.mysql_var = tk.BooleanVar(
            value=existing.mysql_enabled if existing else False
        )
        self.nginx_package_var = tk.StringVar(
            value=existing.nginx_package or "" if existing else ""
        )
        self.php_package_var = tk.StringVar(
            value=existing.php_package or "" if existing else ""
        )
        self.mysql_package_var = tk.StringVar(
            value=existing.mysql_package or "" if existing else ""
        )
        self.mysql_port_var = tk.StringVar(
            value=str(existing.mysql_port) if existing else "3307"
        )

        content = ttk.Frame(self, padding=24)
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
            if row == 0:
                entry.focus_set()
                entry.selection_range(0, "end")
            if row == 1:
                icon_button(
                    content, "…", "Choose document root", command=self._browse
                ).grid(row=row, column=2, padx=(8, 0))

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

        ToggleSwitch(content, label="MySQL", variable=self.mysql_var).grid(
            row=5, column=1, sticky="w", pady=(6, 0)
        )
        ttk.Label(
            content,
            text="Download packages in Components, then select exact versions below.",
            style="Muted.TLabel",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 0))

        for row, component, variable in (
            (7, "nginx", self.nginx_package_var),
            (8, "php", self.php_package_var),
            (9, "mysql", self.mysql_package_var),
        ):
            ttk.Label(content, text=f"Local {component.title()}").grid(
                row=row, column=0, sticky="w", pady=5
            )
            choices = ["", *(p.key for p in local_packages if p.component == component)]
            if variable.get() not in choices:
                choices.append(
                    variable.get()
                )  # preserve an unavailable selection after relocation
            picker = ttk.Combobox(
                content,
                textvariable=variable,
                values=choices,
                state="readonly",
                width=57,
            )
            picker.grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)
            if component == "php":
                picker.bind(
                    "<<ComboboxSelected>>",
                    lambda _event: self.php_var.set(
                        self.php_package_var.get().split("/")[1]
                        if self.php_package_var.get()
                        else ""
                    ),
                )
        ttk.Label(content, text="MySQL port").grid(row=10, column=0, sticky="w", pady=5)
        ttk.Entry(content, textvariable=self.mysql_port_var, width=12).grid(
            row=10, column=1, sticky="w", pady=5
        )
        buttons = ttk.Frame(content)
        buttons.grid(row=11, column=0, columnspan=3, sticky="e", pady=(18, 0))
        ttk.Button(buttons, text="Cancel", command=self._close).pack(
            side="right", padx=(8, 0)
        )
        self.save_button = ttk.Button(
            buttons, text="Save", style="Primary.TButton", command=self._save
        )
        self.save_button.pack(side="right")

        self.bind("<Escape>", lambda _event: self._close())
        self.bind("<Return>", lambda _event: self._save())
        self.update_idletasks()
        x = parent.winfo_rootx() + max(
            0, (parent.winfo_width() - self.winfo_reqwidth()) // 2
        )
        y = parent.winfo_rooty() + max(
            0, (parent.winfo_height() - self.winfo_reqheight()) // 2
        )
        self.geometry(f"+{x}+{y}")
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
        if self._io.busy or self._closing:
            return
        values: _FormValues = dict(
            name=self.name_var.get().strip(),
            document_root=self.root_var.get().strip(),
            server=self.server_var.get(),
            php_version=self.php_var.get().strip() or None,
            port=self.port_var.get().strip(),
            mysql_enabled=self.mysql_var.get(),
            nginx_package=self.nginx_package_var.get() or None,
            php_package=self.php_package_var.get() or None,
            mysql_package=self.mysql_package_var.get() or None,
            mysql_port=self.mysql_port_var.get().strip(),
        )

        def validate() -> ProjectProfile:
            """Validate the captured editor fields off the Tk event loop.

            Returns:
                ProjectProfile: Validated complete profile captured from the editor
                    fields.
            """
            port = int(values["port"])
            root = Path(values["document_root"]).expanduser().resolve()
            if not root.is_dir():
                raise ValueError("Document root must be an existing directory")
            kwargs: _ProfileValues = {
                "name": values["name"],
                "document_root": str(root),
                "server": values["server"],
                "php_version": values["php_version"],
                "http_port": port,
                "mysql_enabled": values["mysql_enabled"],
                "nginx_package": values["nginx_package"],
                "php_package": values["php_package"],
                "mysql_package": values["mysql_package"],
                "mysql_port": int(values["mysql_port"]),
            }
            if self.existing is None:
                candidate = ProjectProfile.create(**kwargs)
            else:
                candidate = replace(self.existing, **kwargs)
            candidate.validate()
            return candidate

        self.save_button.configure(state="disabled")
        self._io.submit(validate, self._validated)
        self.after(100, self._poll)

    def _validated(self, candidate: ProjectProfile) -> None:
        """Accept the validated profile and close the editor.

        Args:
            candidate (ProjectProfile): Complete validated profile returned by the IO
                worker.
        """
        if not self._closing:
            self.result = candidate
        self.destroy()

    def _poll(self) -> None:
        """Deliver queued worker results on the Tk thread."""
        try:
            success, result, error = self._io.results.get_nowait()
        except queue.Empty:
            self.after(100, self._poll)
            return
        self._io.thread = None
        if self._closing:
            self.destroy()
        elif error:
            self.save_button.configure(state="normal")
            messagebox.showerror("Invalid project", str(error), parent=self)
        else:
            success(result)

    def _close(self) -> None:
        """Close the view after pending worker cleanup completes."""
        self._closing = True
        if not self._io.busy:
            self.destroy()

"""Tk desktop workspace for project profiles and component inventory."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from local_server import __version__
from local_server.components.catalog import PackageCatalog
from local_server.core.paths import AppPaths
from local_server.runtime.nginx import render_nginx_config
from local_server.services.projects import ProjectService

from .dialogs import ProjectDialog


class MainWindow(tk.Tk):
    """Initial cross-platform UI, without falsely advertising server startup."""

    def __init__(self, *, service: ProjectService, paths: AppPaths):
        super().__init__()
        self.service = service
        self.paths = paths
        self.title(f"Local Server {__version__}")
        self.geometry("1040x610")
        self.minsize(760, 470)

        self._create_menu()
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        projects_page = ttk.Frame(notebook, padding=12)
        components_page = ttk.Frame(notebook, padding=12)
        notebook.add(projects_page, text="Projects")
        notebook.add(components_page, text="Components")

        self._create_projects_tab(projects_page)
        self._create_components_tab(components_page)

        self.status_var = tk.StringVar(
            value="Profile manager ready. Service startup will be added in a later milestone."
        )
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(
            fill="x", padx=18, pady=(0, 12)
        )
        self.refresh()

    def _create_menu(self) -> None:
        """Build a minimal native Tk menu."""
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Refresh", command=self.refresh)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _create_projects_tab(self, parent: ttk.Frame) -> None:
        """Create a table of web roots, web servers and selected PHP versions."""
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header, text="Web projects", font=("TkDefaultFont", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Profiles are saved locally. Start/stop and live PHP switching are planned.",
        ).pack(anchor="w", pady=(5, 0))

        columns = ("name", "root", "server", "php", "port", "mysql")
        self.project_tree = ttk.Treeview(
            parent,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=14,
        )
        headings = {
            "name": ("Name", 170),
            "root": ("Document root", 310),
            "server": ("Web server", 110),
            "php": ("PHP", 70),
            "port": ("Port", 70),
            "mysql": ("MySQL", 75),
        }
        for field, (title, width) in headings.items():
            self.project_tree.heading(field, text=title)
            self.project_tree.column(field, width=width, minwidth=55, stretch=field == "root")
        self.project_tree.pack(fill="both", expand=True)
        self.project_tree.bind("<<TreeviewSelect>>", lambda _event: self._select())
        self.project_tree.bind("<Double-1>", lambda _event: self._edit())

        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Add project", command=self._add).pack(
            side="left", padx=(0, 8)
        )
        self.edit_button = ttk.Button(
            actions, text="Edit", command=self._edit, state="disabled"
        )
        self.edit_button.pack(side="left", padx=(0, 8))
        self.remove_button = ttk.Button(
            actions, text="Remove", command=self._remove, state="disabled"
        )
        self.remove_button.pack(side="left", padx=(0, 8))
        self.config_button = ttk.Button(
            actions, text="Preview Nginx config", command=self._preview, state="disabled"
        )
        self.config_button.pack(side="right")

    def _create_components_tab(self, parent: ttk.Frame) -> None:
        """Expose honest component-installation status and the future boundary."""
        ttk.Label(
            parent, text="Managed components", font=("TkDefaultFont", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(
            parent,
            text=(
                "Downloads and installations will be enabled after approved, "
                "platform-specific packages and SHA-256 hashes are added."
            ),
            wraplength=800,
        ).pack(anchor="w", pady=(8, 20))

        columns = ("component", "status")
        table = ttk.Treeview(parent, columns=columns, show="headings", height=6)
        table.heading("component", text="Component")
        table.heading("status", text="Availability")
        table.column("component", width=160, stretch=False)
        table.column("status", width=610)
        table.pack(fill="x")
        catalog = PackageCatalog.bundled()
        for component in ("nginx", "apache", "php", "mysql"):
            count = sum(p.component == component for p in catalog.packages)
            message = f"{count} reviewed package(s) in catalog" if count else "Not curated yet"
            table.insert("", "end", values=(component.title(), message))
        ttk.Label(
            parent,
            text=f"Future private binary directory: {self.paths.components}",
            wraplength=850,
        ).pack(anchor="w", pady=(20, 0))

    def refresh(self) -> None:
        """Reload the UI from validated on-disk project settings."""
        previous = self._selected_id()
        self.project_tree.delete(*self.project_tree.get_children())
        try:
            projects = self.service.list_projects()
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Cannot load projects", str(exc), parent=self)
            self._select()
            return
        for project in projects:
            self.project_tree.insert(
                "",
                "end",
                iid=project.id,
                values=(
                    project.name,
                    project.document_root,
                    project.server,
                    project.php_version or "None",
                    project.http_port,
                    "Yes" if project.mysql_enabled else "No",
                ),
            )
        if previous is not None and self.project_tree.exists(previous):
            self.project_tree.selection_set(previous)
        self._select()
        self.status_var.set(f"{len(projects)} project profile(s) loaded")

    def _selected_id(self) -> str | None:
        """Read the selected project's stable UUID."""
        chosen = self.project_tree.selection()
        return chosen[0] if chosen else None

    def _select(self) -> None:
        """Enable actions only for an existing selection."""
        selected = self._selected_id() is not None
        state = "normal" if selected else "disabled"
        self.edit_button.configure(state=state)
        self.remove_button.configure(state=state)
        self.config_button.configure(state=state)

    def _add(self) -> None:
        """Open the new project dialog and atomically persist its result."""
        dialog = ProjectDialog(self)
        if dialog.result is None:
            return
        try:
            project = dialog.result
            self.service.create_project(
                project.name,
                project.document_root,
                server=project.server,
                php_version=project.php_version,
                http_port=project.http_port,
                mysql_enabled=project.mysql_enabled,
            )
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Cannot add project", str(exc), parent=self)
            return
        self.refresh()

    def _edit(self) -> None:
        """Update a saved project while keeping its identifier stable."""
        selected = self._selected_id()
        if selected is None:
            return
        try:
            current = self.service.get_project(selected)
        except (KeyError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Cannot edit project", str(exc), parent=self)
            return
        dialog = ProjectDialog(self, existing=current)
        if dialog.result is None:
            return
        try:
            self.service.update_project(dialog.result)
        except (ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Cannot save project", str(exc), parent=self)
            return
        self.refresh()

    def _remove(self) -> None:
        """Remove the saved profile only, leaving project files untouched."""
        selected = self._selected_id()
        if selected is None:
            return
        if not messagebox.askyesno(
            "Remove project",
            "Remove this profile?\nThe project's source files will not be deleted.",
            parent=self,
        ):
            return
        try:
            self.service.delete_project(selected)
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            messagebox.showerror("Cannot remove project", str(exc), parent=self)
            return
        self.refresh()

    def _preview(self) -> None:
        """Display a rendered Nginx template without launching any service."""
        selected = self._selected_id()
        if selected is None:
            return
        try:
            project = self.service.get_project(selected)
            if project.server != "nginx":
                messagebox.showinfo(
                    "Nginx preview",
                    "This project uses Apache. An Apache adapter is planned.",
                    parent=self,
                )
                return
            rendered = render_nginx_config(
                project, self.paths.project_config_dir(project.id)
            )
        except (KeyError, ValueError, RuntimeError) as exc:
            messagebox.showerror("Config preview failed", str(exc), parent=self)
            return

        popup = tk.Toplevel(self)
        popup.title(f"Nginx preview: {project.name}")
        popup.geometry("820x570")
        ttk.Label(
            popup,
            text="Preview only. PHP requests are denied until a FastCGI process is configured.",
            padding=10,
        ).pack(anchor="w")
        source = tk.Text(popup, wrap="none", font=("TkFixedFont", 11))
        source.insert("1.0", rendered)
        source.configure(state="disabled")
        source.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _about(self) -> None:
        """Show the project version and current implementation scope."""
        messagebox.showinfo(
            "About Local Server",
            f"Local Server {__version__}\n"
            "Windows and macOS local development manager.\n"
            "Initial scaffold: project profiles, installers and runtime primitives.",
            parent=self,
        )

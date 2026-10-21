"""Tk desktop workspace for project profiles and component inventory."""

from __future__ import annotations

import tkinter as tk
import queue
import webbrowser
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable
from tkinter import filedialog, messagebox, ttk

from local_server import __version__
from local_server.components.catalog import PackageSpec
from local_server.core.paths import AppPaths
from local_server.core.models import ProjectProfile
from local_server.runtime.nginx import render_nginx_config
from local_server.runtime.controller import RuntimeController, RuntimeWorker, RuntimeEvent
from local_server.services.projects import ProjectService
from local_server.services.background import BackgroundIO

from .dialogs import ProjectDialog
from .components import ComponentsPage
from .theme import apply_theme, icon_button, BACKGROUND, SURFACE, INK


class MainWindow(tk.Tk):
    """Initial cross-platform UI, without falsely advertising server startup."""

    def __init__(self, *, service: ProjectService, paths: AppPaths) -> None:
        super().__init__()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        apply_theme(self)
        self.service = service
        self.paths = paths
        self._io = BackgroundIO()
        self._missing_roots: set[str] = set()
        self._closing = False
        self._projects: list[ProjectProfile] = []
        self._runtime_states: dict[str, RuntimeEvent] = {}
        self._runtime_worker: RuntimeWorker | None = None
        self.search_var = tk.StringVar()
        self.server_filter = tk.StringVar(value="All servers")
        self.summary_var = tk.StringVar(value="Your local workspace")
        self.detail_var = tk.StringVar(value="Select a project to see its settings.")
        self.empty_var = tk.StringVar()
        self.title(f"Local Server {__version__}")
        self.geometry("1120x760")
        self.minsize(860, 650)

        banner = ttk.Frame(self, padding=(24, 18, 24, 0))
        banner.grid(row=0, column=0, sticky="ew")
        icon_button(banner, "↻", "Refresh · F5", command=self.refresh).pack(side="right")
        icon_button(banner, "?", "About Local Server", command=self._about).pack(side="right", padx=8)
        ttk.Label(banner, text="Local Server", font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
        ttk.Label(banner, textvariable=self.summary_var).pack(anchor="w", pady=(4, 0))
        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=12, pady=12)

        projects_page = ttk.Frame(notebook, padding=12)
        components_page = ttk.Frame(notebook, padding=12)
        notebook.add(projects_page, text="Projects")
        notebook.add(components_page, text="Components")

        self._create_projects_tab(projects_page)
        self._create_components_tab(components_page)
        if self.components_page.worker and self.components_page.target:
            self._runtime_worker = RuntimeWorker(RuntimeController(paths,
                self.components_page.worker.manager, self.components_page.target))
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.status_var = tk.StringVar(
            value="Workspace ready"
        )
        ttk.Label(self, textvariable=self.status_var, anchor="w").grid(
            row=2, column=0, sticky="ew", padx=18, pady=(0, 12)
        )
        self.refresh()
        self.after(100, self._poll_io)

    def _create_menu(self) -> None:
        """Build a minimal native Tk menu."""
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Refresh", command=self.refresh)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._close)
        menu.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="About", command=self._about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menu)

    def _create_projects_tab(self, parent: ttk.Frame) -> None:
        """Create a table of web roots, web servers and selected PHP versions."""
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        header = ttk.Frame(parent)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(
            header, text="Workspace", font=("TkDefaultFont", 14, "bold")
        ).pack(anchor="w")
        ttk.Label(
            header,
            text="Nginx + PHP · isolated local projects", style="Muted.TLabel",
        ).pack(anchor="w", pady=(5, 0))

        filters = ttk.Frame(parent)
        filters.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(filters, text="⌕").pack(side="left", padx=(0, 8))
        search = ttk.Entry(filters, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True)
        picker = ttk.Combobox(
            filters, textvariable=self.server_filter,
            values=("All servers", "nginx", "apache"), state="readonly", width=16,
        )
        picker.pack(side="left", padx=(12, 0))
        self.search_var.trace_add("write", lambda *_args: self._render_projects())
        self.server_filter.trace_add("write", lambda *_args: self._render_projects())
        self.bind("<Control-f>", lambda _event: search.focus_set())
        self.bind("<Control-n>", lambda _event: self._add())
        self.bind("<F5>", lambda _event: self.refresh())

        columns = ("name", "root", "server", "php", "port", "mysql", "runtime")
        table_frame = ttk.Frame(parent)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.project_tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=4,
        )
        headings = {
            "name": ("Name", 170),
            "root": ("Document root", 310),
            "server": ("Web server", 110),
            "php": ("PHP", 70),
            "port": ("Port", 70),
            "mysql": ("MySQL", 75),
            "runtime": ("Runtime", 95),
        }
        for field, (title, width) in headings.items():
            self.project_tree.heading(field, text=title)
            self.project_tree.column(field, width=width, minwidth=55, stretch=field == "root")
        self.project_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.project_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.project_tree.configure(yscrollcommand=scrollbar.set)
        self.project_tree.bind("<<TreeviewSelect>>", lambda _event: self._select())
        self.project_tree.bind("<Double-1>", lambda _event: self._edit())
        ttk.Label(parent, textvariable=self.empty_var).grid(row=3, column=0, sticky="w", pady=(6, 0))
        detail = ttk.Frame(parent, style="Card.TFrame", padding=16)
        detail.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.detail_label = ttk.Label(detail, textvariable=self.detail_var, wraplength=850, justify="left", style="Card.TLabel")
        self.detail_label.pack(fill="x")
        detail.bind("<Configure>", lambda event: self.detail_label.configure(wraplength=max(200, event.width - 30)))
        self.copy_button = icon_button(detail, "⧉", "Copy local URL", command=self._copy_url, state="disabled")
        self.copy_button.pack(anchor="w", pady=(8, 0))
        self.relink_button = ttk.Button(detail, text="Choose document root…", command=self._relink)

        actions = ttk.Frame(parent)
        actions.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="＋ Project", command=self._add).pack(
            side="left", padx=(0, 8)
        )
        self.edit_button = icon_button(
            actions, "✎", "Edit project", command=self._edit, state="disabled"
        )
        self.edit_button.pack(side="left", padx=(0, 8))
        self.remove_button = icon_button(
            actions, "−", "Remove profile", command=self._remove, state="disabled"
        )
        self.remove_button.pack(side="left", padx=(0, 8))
        self.config_button = icon_button(
            actions, "‹/›", "Preview Nginx configuration", command=self._preview, state="disabled"
        )
        self.config_button.pack(side="right")
        self.start_button = ttk.Button(actions, text="Start", style="Primary.TButton", command=lambda: self._runtime_action("start"), state="disabled")
        self.start_button.pack(side="left", padx=(4, 8))
        self.stop_button = ttk.Button(actions, text="Stop", command=lambda: self._runtime_action("stop"), state="disabled")
        self.stop_button.pack(side="left", padx=(0, 8))
        self.restart_button = icon_button(actions, "↻", "Restart project", command=lambda: self._runtime_action("restart"), state="disabled")
        self.restart_button.pack(side="left", padx=(0, 8))
        self.open_button = icon_button(actions, "↗", "Open local website", command=self._open_site, state="disabled")
        self.open_button.pack(side="left", padx=(0, 8))
        self.logs_button = icon_button(actions, "≡", "Runtime logs and error details", command=self._logs, state="disabled")
        self.logs_button.pack(side="left")

    def _create_components_tab(self, parent: ttk.Frame) -> None:
        """Expose honest component-installation status and the future boundary."""
        self.components_page = ComponentsPage(parent, self.paths, self.service.store)
        self.components_page.pack(fill="both", expand=True)

    def _close(self) -> None:
        """Keep the event loop alive until package cancellation has cleaned staging."""
        self._closing = True
        if self._runtime_worker:
            self._runtime_worker.close()
        packages_busy = self.components_page.cancel_and_wait()
        runtime_busy = bool(self._runtime_worker and self._runtime_worker.thread.is_alive())
        if packages_busy or self._io.busy or runtime_busy:
            self.status_var.set("Stopping owned runtimes and cleaning up…")
            self.after(100, self._close)
        else:
            self.destroy()

    def refresh(self) -> None:
        """Reload the UI from validated on-disk project settings."""
        def load() -> tuple[list[ProjectProfile], set[str]]:
            projects = self.service.list_projects()
            return projects, {p.id for p in projects if not Path(p.document_root).is_dir()}
        self._submit_io(load, self._loaded)

    def finish_shutdown(self) -> None:
        """Join cleanup workers after mainloop ends, including external Tk destruction."""
        if self._runtime_worker:
            self._runtime_worker.close()
            self._runtime_worker.thread.join()
        if self.components_page.worker:
            self.components_page.worker.cancel()
            if self.components_page.worker.thread:
                self.components_page.worker.thread.join()
        if self._io.thread:
            self._io.thread.join()

    def _loaded(self, result: tuple[list[ProjectProfile], set[str]]) -> None:
        projects, self._missing_roots = result
        self._projects = projects
        self.summary_var.set(
            f"{len(projects)} projects  ·  "
            f"{sum(p.php_version is not None for p in projects)} with PHP selected  ·  "
            f"{sum(p.mysql_enabled for p in projects)} requesting MySQL"
        )
        self._render_projects()
        self.status_var.set(f"{len(projects)} project profile(s) loaded")

    def _submit_io(self, operation: Callable[[], Any], success: Callable[[Any], None]) -> None:
        if self._closing or self._io.busy:
            return
        self._io.submit(operation, success)
        self.status_var.set("Updating workspace…")

    def _poll_io(self) -> None:
        if self._runtime_worker:
            changed = False
            while not self._runtime_worker.events.empty():
                event = self._runtime_worker.events.get_nowait()
                self._runtime_states[event.project_id] = event
                changed = True
                if event.message:
                    self.status_var.set(event.message + " · open runtime logs for details")
            if changed:
                self._render_projects()
        while True:
            try:
                success, result, error = self._io.results.get_nowait()
            except queue.Empty:
                break
            self._io.thread = None
            if error:
                if not self._closing:
                    messagebox.showerror("Workspace operation failed", str(error), parent=self)
                self.status_var.set("Workspace operation failed. Previous profiles are kept.")
            elif not self._closing:
                success(result)
        self.after(100, self._poll_io)

    def _render_projects(self) -> None:
        """Filter cached profiles without rereading storage on each keystroke."""
        previous = self._selected_id()
        existing_rows = self.project_tree.get_children()
        if existing_rows:
            self.project_tree.delete(*existing_rows)
        query = self.search_var.get().strip().casefold()
        server = self.server_filter.get()
        projects = [
            p for p in self._projects
            if (server == "All servers" or p.server == server)
            and query in f"{p.name} {p.document_root} {p.php_version or ''} {p.http_port}".casefold()
        ]
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
                    self._runtime_states.get(project.id, RuntimeEvent(project.id, "stopped")).state.title(),
                ),
            )
        if previous is not None and self.project_tree.exists(previous):
            self.project_tree.selection_set(previous)
        elif projects:
            self.project_tree.selection_set(projects[0].id)
        self.empty_var.set(
            "" if projects else (
                "No matching projects. Change the search or server filter."
                if self._projects else "Your workspace is empty. Add your first project to get started."
            )
        )
        self._select()

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
        self.copy_button.configure(state=state)
        self.logs_button.configure(state=state)
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        runtime_state = self._runtime_states.get(project.id, RuntimeEvent(project.id, "stopped")).state if project else "stopped"
        runtime_event = self._runtime_states.get(project.id) if project else None
        active = runtime_state in {"starting", "stopping", "running"} or bool(runtime_event and runtime_event.owned)
        self.edit_button.configure(state="disabled" if active else state)
        self.remove_button.configure(state="disabled" if active else state)
        self.start_button.configure(state="normal" if project and project.server == "nginx" and project.nginx_package and project.php_package and self._runtime_worker and not active and not self._closing else "disabled")
        self.stop_button.configure(state="normal" if project and runtime_state in {"running", "error"} and not self._closing else "disabled")
        self.restart_button.configure(state="normal" if runtime_state == "running" and not self._closing else "disabled")
        self.open_button.configure(state="normal" if runtime_state == "running" and not self._closing else "disabled")
        if project is None:
            self.detail_var.set("Select a project to see its settings.")
            self.relink_button.pack_forget()
            return
        self.config_button.configure(state="normal" if project.server == "nginx" else "disabled")
        self.detail_var.set(
            f"{project.name}\n{project.document_root}\n"
            f"http://127.0.0.1:{project.http_port}  ·  {project.server.title()}  ·  "
            f"PHP {project.php_version or 'not selected'}  ·  "
            f"MySQL {'requested' if project.mysql_enabled else 'not requested'}\n"
            f"Runtime: {runtime_state}  ·  Nginx: {project.nginx_package or 'select a local package'}\n"
            f"PHP: {project.php_package or 'select a local package'}"
        )
        if project.id in self._missing_roots and not active:
            self.detail_var.set(self.detail_var.get() + "\nDocument root is unavailable. Choose its new location.")
            self.relink_button.pack(anchor="w", pady=(8, 0))
        else:
            self.relink_button.pack_forget()

    def _relink(self) -> None:
        """Explicitly reassign an external root after a move; never guess drives."""
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        if project is None or self._io.busy or self._is_active(project.id):
            return
        chosen = filedialog.askdirectory(parent=self, title="Reassign document root")
        if chosen:
            self._submit_io(lambda: self.service.update_project(replace(project, document_root=chosen)), lambda _result: self.refresh())

    def _copy_url(self) -> None:
        """Copy the configured loopback address without claiming it is served."""
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        if project is None:
            return
        self.clipboard_clear()
        self.clipboard_append(f"http://127.0.0.1:{project.http_port}")
        self.status_var.set("Local URL copied.")

    def _add(self) -> None:
        """Open the new project dialog and atomically persist its result."""
        if self._io.busy or self._closing:
            return
        used_ports = {project.http_port for project in self._projects}
        suggested_port = next((port for port in range(8080, 65536) if port not in used_ports), None)
        if suggested_port is None:
            messagebox.showerror("Cannot add project", "No unused profile port available from 8080 onwards.", parent=self)
            return
        dialog = ProjectDialog(self, suggested_port=suggested_port, local_packages=self._local_packages())
        if dialog.result is None:
            return
        project = dialog.result
        def save() -> None:
            self.service.create_project(
                project.name,
                project.document_root,
                server=project.server,
                php_version=project.php_version,
                http_port=project.http_port,
                mysql_enabled=project.mysql_enabled,
                nginx_package=project.nginx_package,
                php_package=project.php_package,
            )
        self._submit_io(save, lambda _result: self.refresh())

    def _edit(self) -> None:
        """Update a saved project while keeping its identifier stable."""
        selected = self._selected_id()
        if selected is None or self._io.busy or self._closing or self._is_active(selected):
            return
        current = next((p for p in self._projects if p.id == selected), None)
        if current is None:
            return
        dialog = ProjectDialog(self, existing=current, local_packages=self._local_packages())
        if dialog.result is None:
            return
        self._submit_io(lambda: self.service.update_project(dialog.result), lambda _result: self.refresh())

    def _remove(self) -> None:
        """Remove the saved profile only, leaving project files untouched."""
        selected = self._selected_id()
        if selected is None or self._io.busy or self._closing or self._is_active(selected):
            return
        if not messagebox.askyesno(
            "Remove project",
            "Remove this profile?\nThe project's source files will not be deleted.",
            parent=self,
        ):
            return
        self._submit_io(lambda: self.service.delete_project(selected), lambda _result: self.refresh())

    def _local_packages(self) -> tuple[PackageSpec, ...]:
        """Use the Components worker's cached inventory without main-thread IO."""
        target = self.components_page.target
        return tuple(p for p in self.components_page.local.values()
                     if target and (p.os, p.arch) == (target.os, target.arch))

    def _is_active(self, project_id: str) -> bool:
        event = self._runtime_states.get(project_id)
        return bool(event and (event.state in {"starting", "stopping", "running"} or event.owned))

    def _runtime_action(self, action: str) -> None:
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        if project is None or not self._runtime_worker or self._closing or self._io.busy:
            return
        self._runtime_states[project.id] = RuntimeEvent(project.id, "stopping" if action == "stop" else "starting")
        self._runtime_worker.submit(action, project)
        self._render_projects()

    def _open_site(self) -> None:
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        if project and self._runtime_states.get(project.id, RuntimeEvent(project.id, "stopped")).state == "running":
            self._submit_io(lambda: webbrowser.open(f"http://127.0.0.1:{project.http_port}"), lambda _result: None)

    def _logs(self) -> None:
        project = next((p for p in self._projects if p.id == self._selected_id()), None)
        if project is None:
            return
        event = self._runtime_states.get(project.id)
        def read() -> str:
            directory = self.paths.project_config_dir(project.id)
            files = [*directory.glob("*.log"), *self.paths.logs.glob(f"*-{project.id}.log")]
            sections = [event.details] if event and event.details else []
            for file in files:
                with file.open("rb") as stream:
                    stream.seek(max(0, file.stat().st_size - 65536))
                    sections.append(f"{file.name}\n" + stream.read(65536).decode("utf-8", errors="replace"))
            return "\n\n".join(sections) or "No runtime logs yet."
        self._submit_io(read, lambda text: self._show_preview(project, text, logs=True))

    def _preview(self) -> None:
        """Display a rendered Nginx template without launching any service."""
        selected = self._selected_id()
        if selected is None or self._io.busy or self._closing:
            return
        project = next((p for p in self._projects if p.id == selected), None)
        if project is None or project.server != "nginx":
            return
        self._submit_io(lambda: render_nginx_config(project, self.paths.project_config_dir(project.id)), lambda rendered: self._show_preview(project, rendered))

    def _show_preview(self, project: ProjectProfile, rendered: str, *, logs: bool = False) -> None:
        popup = tk.Toplevel(self)
        popup.title(f"{'Runtime logs' if logs else 'Nginx preview'}: {project.name}")
        popup.geometry("820x570")
        popup.configure(background=BACKGROUND)
        ttk.Label(
            popup,
            text="Runtime logs and error details" if logs else "Preview only. PHP requests are denied until a FastCGI process is configured.",
            padding=10,
        ).pack(anchor="w")
        source = tk.Text(popup, wrap="none", font=("TkFixedFont", 11), background=SURFACE, foreground=INK, insertbackground=INK, relief="flat", padx=16, pady=16)
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

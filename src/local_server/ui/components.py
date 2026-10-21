"""Compact Components workspace backed by a cancellable, Tk-free worker."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk

from local_server.components.catalog import PackageCatalog, PackageSpec
from local_server.components.installer import ComponentInstaller
from local_server.components.manager import PackageEvent, PackageManager, PackageWorker
from local_server.core.paths import AppPaths
from local_server.core.platform import PlatformTarget
from local_server.core.store import ProjectStore

from .theme import BACKGROUND, INK, SURFACE, icon_button

STATES = {
    "available": "Available to download", "downloading": "Downloading",
    "verifying": "Verifying SHA-256", "extracting": "Extracting",
    "local": "Locally available · runtime untested", "error": "Error",
    "cancelled": "Available to download",
    "runtime-downloading": "Downloading runtime libraries",
    "runtime-verifying": "Verifying runtime libraries",
    "runtime-extracting": "Preparing runtime libraries",
    "runtime-copying": "Adding local runtime libraries",
}


class ComponentsPage(ttk.Frame):
    """Select reviewed versions, inspect prerequisites and manage local archives."""

    def __init__(self, parent: tk.Misc, paths: AppPaths, store: ProjectStore) -> None:
        super().__init__(parent)
        self.local: dict[str, PackageSpec] = {}
        self.states: dict[str, str] = {}
        self.errors: dict[str, str] = {}
        self.issues: dict[str, tuple[str, ...]] = {}
        self.active: PackageSpec | None = None
        self.component = tk.StringVar(value="nginx")
        self.version = tk.StringVar()
        self.status = tk.StringVar(value="Reading local packages…")
        self.note = tk.StringVar()
        self._busy = False
        self._loaded = False
        self._closing = False
        self.general_error = ""
        self.worker: PackageWorker | None = None
        self.target: PlatformTarget | None = None
        catalog = PackageCatalog.bundled()
        try:
            self.target = PlatformTarget.detect()
            self.catalog = {p.key: p for p in catalog.packages if (p.os, p.arch) == (self.target.os, self.target.arch)}
            self.worker = PackageWorker(PackageManager(ComponentInstaller(paths, self.target, runtime_bundles=catalog.runtime_bundles), store), tuple(self.catalog.values()))
        except NotImplementedError as exc:
            self.catalog = {}
            self.status.set(str(exc))
        self.packages = dict(self.catalog)

        heading = ttk.Frame(self)
        heading.pack(fill="x")
        ttk.Label(heading, text="Portable packages", font=("TkDefaultFont", 14, "bold")).pack(side="left")
        self.refresh_button = icon_button(heading, "↻", "Refresh packages and dependency checks", command=self.refresh)
        self.refresh_button.pack(side="right")
        ttk.Label(self, text="Archives only · server startup comes later", style="Muted.TLabel").pack(anchor="w", pady=(6, 16))
        pickers = ttk.Frame(self)
        pickers.pack(fill="x", pady=(0, 14))
        self.component_picker = ttk.Combobox(pickers, textvariable=self.component, values=("nginx", "apache", "php", "mysql"), state="readonly", width=14)
        self.component_picker.pack(side="left", padx=(0, 12))
        self.version_picker = ttk.Combobox(pickers, textvariable=self.version, state="readonly", width=38)
        self.version_picker.pack(side="left", fill="x", expand=True)
        self.component_picker.bind("<<ComboboxSelected>>", lambda _event: self._versions())
        self.version_picker.bind("<<ComboboxSelected>>", lambda _event: self._choose_version())
        table_frame = ttk.Frame(self)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, columns=("component", "version", "target", "state"), show="headings", selectmode="browse", height=8)
        for key, label, width in (("component", "Component", 100), ("version", "Version / variant", 180), ("target", "Platform", 160), ("state", "Availability", 330)):
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=70, stretch=key == "state")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selected())

        ttk.Label(self, textvariable=self.note, style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(12, 6))
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(anchor="w", pady=(6, 12))
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        self.download_button = ttk.Button(actions, text="↓ Download", style="Primary.TButton", command=lambda: self._start("download"), state="disabled")
        self.download_button.pack(side="left")
        self.cancel_button = icon_button(actions, "×", "Cancel download and clean up", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=8)
        self.remove_button = ttk.Button(actions, text="Remove", command=self._remove, state="disabled")
        self.remove_button.pack(side="left")
        self.details_button = icon_button(actions, "ⓘ", "Package source, license, requirements and error details", command=self._details)
        self.details_button.pack(side="right")
        ttk.Label(self, text=f"Storage · {paths.components}", style="Muted.TLabel", wraplength=800).pack(anchor="w", pady=(16, 0))
        self._versions()
        self.refresh()
        self.after(100, self._poll)

    def refresh(self) -> None:
        """Recheck receipts and system dependencies in the package worker."""
        if self.worker and not self._busy:
            self._busy = True
            self.status.set("Reading local packages…")
            self.worker.start("refresh")
            self._actions()

    def cancel_and_wait(self) -> bool:
        """Request cleanup on window close and report whether a worker remains."""
        self._closing = True
        if self.worker:
            self.worker.cancel()
            return self.worker.busy
        return False

    def _package(self) -> PackageSpec | None:
        selection = self.tree.selection()
        return self.packages.get(selection[0]) if selection else None

    def _versions(self) -> None:
        options = [p for p in self.packages.values() if p.component == self.component.get()]
        self.options = {f"{p.version} · {p.variant} · {p.os}/{p.arch}": p for p in options}
        self.version_picker.configure(values=tuple(self.options))
        if self.version.get() not in self.options:
            self.version.set(next(iter(self.options), "No reviewed package for this platform"))
        self._render()
        self._choose_version()

    def _choose_version(self) -> None:
        package = self.options.get(self.version.get())
        if package and self.tree.exists(package.key):
            self.tree.selection_set(package.key)
            self.tree.see(package.key)
        elif not package:
            self.tree.selection_remove(*self.tree.selection())
        self._selected()

    def _render(self) -> None:
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for package in self.packages.values():
            state = self.states.get(package.key, "local" if package.key in self.local else "available")
            label = STATES.get(state, state)
            if self.issues.get(package.key):
                label += " · prerequisite missing"
            self.tree.insert("", "end", iid=package.key, values=(package.component.title(), f"{package.version} · {package.variant}", f"{package.os}/{package.arch}", label))
        if selected and self.tree.exists(selected[0]):
            self.tree.selection_set(selected)

    def _selected(self) -> None:
        package = self._package()
        if package:
            self.component.set(package.component)
            options = [p for p in self.packages.values() if p.component == package.component]
            self.options = {f"{p.version} · {p.variant} · {p.os}/{p.arch}": p for p in options}
            self.version_picker.configure(values=tuple(self.options))
            self.version.set(f"{package.version} · {package.variant} · {package.os}/{package.arch}")
            self.note.set(" · ".join((package.license, "x86 via WoW64" if package.binary_arch == "x86" else package.binary_arch, *self.issues.get(package.key, ()))))
        else:
            self.note.set("No reviewed package for this platform." if not self.catalog else "Choose a version.")
        self._actions()

    def _actions(self) -> None:
        package = self._package()
        idle = self._loaded and not self._busy and not self._closing
        downloadable = bool(package and package.key in self.catalog and package.key not in self.local and not self.issues.get(package.key))
        self.download_button.configure(state="normal" if idle and downloadable else "disabled", text="↻ Retry" if package and package.key in self.errors else "↓ Download")
        self.remove_button.configure(state="normal" if idle and package and package.key in self.local else "disabled")
        self.cancel_button.configure(state="normal" if self._busy and self.active else "disabled")
        self.refresh_button.configure(state="disabled" if self._busy or self._closing else "normal")

    def _start(self, action: str) -> None:
        package = self._package()
        if not self.worker or not package or self._busy:
            return
        self.active = package if action == "download" else None
        self._busy = True
        self.errors.pop(package.key, None)
        self.progress.configure(value=0)
        self.status.set(f"{package.component.title()} {package.version} · {'Preparing download' if action == 'download' else 'Removing'}…")
        self.worker.start(action, package)
        self._actions()

    def _cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.status.set("Cancelling and cleaning up…")
            self.cancel_button.configure(state="disabled")

    def _remove(self) -> None:
        package = self._package()
        if package and messagebox.askyesno("Remove local package", f"Remove {package.component} {package.version} ({package.variant})?\nProject sources and database data will be kept.", parent=self):
            self._start("remove")

    def _details(self) -> None:
        package = self._package()
        if not package and not self.general_error:
            return
        text = self.general_error
        if package:
            text = f"{package.component.title()} {package.version} · {package.variant}\n{package.os}/{package.arch} (binary: {package.binary_arch})\n\nSource: {package.source}\nArchive: {package.url}\nSHA-256: {package.sha256}\nChecksum evidence: {package.checksum_source}\nLicense: {package.license}\n\n" + "\n".join(package.requirements) + f"\n\n{package.notes}\n\nExtracted archives are not verified running servers.\n" + "\n".join(self.issues.get(package.key, ())) + "\n\n" + self.errors.get(package.key, "") + "\n\n" + self.general_error
        popup = tk.Toplevel(self)
        popup.title("Package details")
        popup.geometry("780x540")
        popup.configure(background=BACKGROUND)
        content = tk.Text(popup, wrap="word", background=SURFACE, foreground=INK, relief="flat", padx=16, pady=16)
        scroll = ttk.Scrollbar(popup, command=content.yview)
        scroll.pack(side="right", fill="y")
        content.configure(yscrollcommand=scroll.set)
        content.insert("1.0", text)
        content.configure(state="disabled")
        content.pack(fill="both", expand=True)

    def _poll(self) -> None:
        if self.worker:
            while True:
                try:
                    event = self.worker.events.get_nowait()
                except queue.Empty:
                    break
                self._event(event)
        self.after(100, self._poll)

    def _event(self, event: PackageEvent) -> None:
        if event.state in {"ready", "error", "cancelled"} and self.worker and self.worker.busy:
            self.after(20, lambda: self._event(event))
            return
        if event.package:
            self.states[event.package.key] = event.state
        if event.state == "ready":
            self.general_error = ""
            self.local = {p.key: p for p in event.local}
            self.packages = {**self.catalog, **self.local}
            self.issues = dict(event.issues)
            self.states = {k: v for k, v in self.states.items() if v == "error"}
            self._loaded = True
            self.status.set(f"{len(self.local)} local package(s) · runtime startup is not implemented" if self.catalog else "No reviewed downloads for this OS/architecture. Local archives can be removed.")
            self._versions()
        elif event.state in {"error", "cancelled"}:
            self.status.set("Package operation failed. Open details." if event.state == "error" else event.message)
            if event.package and event.state == "error":
                self.errors[event.package.key] = event.details
            elif event.state == "error" and not self._closing:
                self.general_error = event.details
                messagebox.showerror("Cannot read packages", event.message, parent=self)
            self.progress.stop()
            self.progress.configure(mode="determinate", value=0)
        else:
            percent = 100 * event.done / event.total if event.total else 0
            self.progress.configure(value=percent)
            title = f"{event.package.component.title()} {event.package.version} · " if event.package else ""
            self.status.set(f"{title}{STATES.get(event.state, event.state)}" + (f" · {percent:.0f}%" if event.total else ""))
        if event.state in {"ready", "error", "cancelled"}:
            self._busy = False
            self.active = None
        self._render()
        self._selected()

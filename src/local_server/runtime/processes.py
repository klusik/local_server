"""Explicitly tracked foreground processes for managed private binaries."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from local_server.core.paths import AppPaths

_PROCESS_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass(slots=True)
class ManagedProcess:
    """A directly tracked child process, not a system daemon."""

    name: str
    handle: subprocess.Popen[bytes]
    log_file: Path

    @property
    def running(self) -> bool:
        """Report whether the owned child process remains alive."""
        return self.handle.poll() is None


class ProcessSupervisor:
    """Start and stop non-daemonizing binaries installed in application storage."""

    def __init__(self, paths: AppPaths):
        self.paths = paths
        self._children: dict[str, ManagedProcess] = {}

    def start(
        self,
        name: str,
        argv: Sequence[str],
        *,
        cwd: Path,
    ) -> ManagedProcess:
        """Start one private executable with no shell or global service install."""
        if not _PROCESS_NAME.fullmatch(name):
            raise ValueError("Invalid managed process name")
        current = self._children.get(name)
        if current is not None and current.running:
            raise RuntimeError(f"Process {name} is already running")
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("argv must contain strings")
        executable = Path(argv[0]).resolve()
        try:
            executable.relative_to(self.paths.components.resolve())
        except ValueError as exc:
            raise ValueError("Executable must be inside the managed components directory") from exc
        if not executable.is_file():
            raise FileNotFoundError(executable)
        if not Path(cwd).is_dir():
            raise ValueError("Process working directory does not exist")

        self.paths.ensure()
        log_file = self.paths.logs / f"{name}.log"
        with log_file.open("ab") as log_stream:
            handle = subprocess.Popen(
                list(argv),
                cwd=cwd,
                stdout=log_stream,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
            )
        managed = ManagedProcess(name=name, handle=handle, log_file=log_file)
        self._children[name] = managed
        return managed

    def status(self, name: str) -> str:
        """Return running/stopped/unmanaged for a tracked child."""
        current = self._children.get(name)
        if current is None:
            return "unmanaged"
        return "running" if current.running else "stopped"

    def stop(self, name: str, *, timeout: float = 5.0) -> bool:
        """Stop only the named owned child, escalating after a bounded timeout."""
        current = self._children.pop(name, None)
        if current is None:
            return False
        if current.running:
            current.handle.terminate()
            try:
                current.handle.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                current.handle.kill()
                current.handle.wait()
        return True

    def stop_all(self) -> None:
        """Stop every child started through this supervisor."""
        for name in list(self._children):
            self.stop(name)

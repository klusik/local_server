"""Explicitly tracked foreground processes for managed private binaries."""

from __future__ import annotations

import re
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Mapping, TYPE_CHECKING

from local_server.core.paths import AppPaths
from local_server.core.paths import reject_links

if TYPE_CHECKING:
    from .windows_job import WindowsJob, WindowsProcess

_PROCESS_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass(slots=True)
class ManagedProcess:
    """A directly tracked child process, not a system daemon."""

    name: str
    handle: subprocess.Popen[bytes] | WindowsProcess
    log_file: Path
    job: WindowsJob | None = None

    @property
    def running(self) -> bool:
        """Report whether the owned child process remains alive."""
        return self.handle.poll() is None


class ProcessSupervisor:
    """Start and stop non-daemonizing binaries installed in application storage."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self._children: dict[str, ManagedProcess] = {}

    def start(
        self,
        name: str,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        contain: bool = False,
    ) -> ManagedProcess:
        """Start one private executable with no shell or global service install."""
        if not _PROCESS_NAME.fullmatch(name):
            raise ValueError("Invalid managed process name")
        current = self._children.get(name)
        if current is not None and current.running:
            raise RuntimeError(f"Process {name} is already running")
        if current is not None:
            self.stop(name)
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("argv must contain strings")
        executable = Path(argv[0]).resolve()
        reject_links(self.paths.components, Path(argv[0]))
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
        reject_links(self.paths.root, log_file)
        arguments = [str(executable), *argv[1:]]
        job = None
        if contain:
            if os.name != "nt":
                raise NotImplementedError("Contained runtime execution requires Windows")
            from .windows_job import WindowsJob
            job = WindowsJob()
        try:
            with log_file.open("ab") as log_stream:
                if job:
                    handle = job.start(arguments, cwd=cwd, env=env, log_descriptor=log_stream.fileno())
                else:
                    handle = subprocess.Popen(
                        arguments,
                        cwd=cwd,
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                        stdin=subprocess.DEVNULL,
                        shell=False,
                        close_fds=True,
                        env=dict(env) if env is not None else None,
                    )
        except BaseException:
            if job:
                job.close()
            raise
        managed = ManagedProcess(name=name, handle=handle, log_file=log_file, job=job)
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
        current = self._children.get(name)
        if current is None:
            return False
        if current.job:
            current.job.close()
            current.handle.wait(timeout=timeout)
        elif current.running:
            current.handle.terminate()
            try:
                current.handle.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                current.handle.kill()
                current.handle.wait()
        self._children.pop(name, None)
        return True

    def stop_all(self) -> None:
        """Stop every child started through this supervisor."""
        for name in list(self._children):
            self.stop(name)
